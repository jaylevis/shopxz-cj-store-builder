"""Candidate discovery with a fulfillability gate. Read-only against CJ; resumable per pid."""

import re

from .config import BuildError, iso, now_jst, read_json, write_json
from .pricing import price_variant
from .rules import banned_hits, clean_description, excluded_category


def price_range(value):
    """CJ numeric fields may be '1.93', '2.21 -- 2.39' or '3.00-4.00'; return (min, max) floats."""
    nums = re.findall(r"\d+(?:\.\d+)?", str(value or ""))
    if not nums:
        return 0.0, 0.0
    return float(nums[0]), float(nums[-1])


def num_max(value):
    return price_range(value)[1]


def _looks_like_code(key):
    parts = [p.strip() for p in str(key).split("-") if p.strip()]
    return any(re.fullmatch(r"[A-Z]{0,3}\d{4,}(\s?\d+)?", p) for p in parts)


def _norm_name(name):
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()[:48]


def resolve_categories(client, wanted):
    """wanted: list of names (any level, case-insensitive substring) or raw categoryIds -> [(id, path)]."""
    tree = client.categories()
    flat = []
    for one in tree:
        for two in one.get("categoryFirstList") or []:
            for three in two.get("categorySecondList") or []:
                flat.append((three.get("categoryId"), f"{one.get('categoryFirstName')} > {two.get('categorySecondName')} > {three.get('categoryName')}"))
    out, missing = [], []
    for w in wanted:
        w_l = str(w).lower()
        hits = [f for f in flat if f[0] == w]  # raw categoryId
        if not hits:  # exact leaf name, then leaf-name substring; never match on parent names
            hits = [f for f in flat if f[1].split(" > ")[-1].lower() == w_l]
        if not hits:
            hits = [f for f in flat if w_l in f[1].split(" > ")[-1].lower()]
        if not hits:
            missing.append(w)
        out += hits
    if missing:
        raise BuildError("CATEGORY_NOT_FOUND", f"no CJ category matches {missing}", {"available_top": sorted({f[1].split(' > ')[0] for f in flat})})
    seen, uniq = set(), []
    for cid, path in out:
        if cid not in seen:
            seen.add(cid)
            uniq.append((cid, path))
    return uniq


def _best_freight(options, prefer, max_days):
    best = None
    for o in options or []:
        name = o.get("logisticName") or ""
        aging = o.get("logisticAging") or ""
        m = re.findall(r"\d+", aging)
        hi = int(m[-1]) if m else 999
        lo = int(m[0]) if m else 999
        if hi > max_days:
            continue
        rank = prefer.index(name) if name in prefer else len(prefer)
        if name not in prefer and not name.startswith("CJPacket"):
            continue  # unknown carriers (postal without tracking, pure air) are not used
        key = (rank, float(o.get("logisticPrice") or 999))
        if best is None or key < best[0]:
            best = (key, {"name": name, "usd": float(o.get("logisticPrice") or 0), "days_min": lo, "days_max": hi})
    return best[1] if best else None


def raw_candidates(client, profile, log):
    cat = profile["catalog"]
    cats = resolve_categories(client, cat["categories"]) if cat.get("categories") else [(None, "(keyword search)")]
    rows = {}
    for cid, path in cats:
        for kw in (cat.get("keywords") or [None]):
            for page in range(1, int(cat.get("max_pages_per_category", 3)) + 1):
                data = client.list_products(page=page, size=100, category_id=cid, keyword=kw,
                                            product_type="ORDINARY_PRODUCT")
                lst = data.get("list") or []
                log(f"  list {path} kw={kw} page {page}: {len(lst)} / total {data.get('total')}")
                for p in lst:
                    if p.get("isTestProduct") or str(p.get("saleStatus", "")) in ("0", "False"):
                        continue
                    lo, hi = price_range(p.get("sellPrice"))
                    if lo < cat["price_usd_min"] or hi > cat["price_usd_max"]:
                        continue
                    price = lo
                    if int(p.get("listedNum") or 0) < int(cat["min_listed_num"]):
                        continue
                    cat_path = " > ".join(filter(None, [p.get("oneCategoryName"), p.get("twoCategoryName"), p.get("threeCategoryName") or p.get("categoryName")]))
                    if excluded_category(cat_path, cat.get("excluded_category_keywords") or []):
                        continue
                    if banned_hits(p.get("productNameEn", "")):
                        continue
                    key = _norm_name(p.get("productNameEn"))
                    cur = rows.get(key)
                    if cur is None or int(p.get("listedNum") or 0) > cur["listedNum"]:
                        rows[key] = {"pid": p["pid"], "name_en": p.get("productNameEn"), "sku": p.get("productSku"),
                                     "sell_usd": price, "listedNum": int(p.get("listedNum") or 0),
                                     "category_path": cat_path, "category_id": p.get("categoryId"),
                                     "image": p.get("productImage"), "weight_g": num_max(p.get("productWeight")),
                                     "supplier": p.get("supplierName") or ""}
                if len(lst) < 100:
                    break
    out = sorted(rows.values(), key=lambda r: -r["listedNum"])
    want = int(cat["target_count"]) * int(cat.get("candidate_multiplier", 3))
    return out[:want]


def evaluate(client, profile, row, log):
    """Detail + stock + freight + pricing for one candidate. Returns the enriched row with gate verdict."""
    cat, ship, pr = profile["catalog"], profile["shipping"], profile["pricing"]
    reasons = []
    d = client.product(row["pid"])
    images = [u for u in (d.get("productImageSet") or []) if u]
    variants = d.get("variants") or []
    if len(images) < int(cat["min_images"]):
        reasons.append(f"images {len(images)} < {cat['min_images']}")
    if not variants:
        reasons.append("no variants")
    if len(variants) > int(cat["max_variants"]):
        reasons.append(f"variants {len(variants)} > {cat['max_variants']}")
    weight = num_max(d.get("packingWeight")) or num_max(d.get("productWeight")) or float(row.get("weight_g") or 0)
    if weight > float(cat["max_weight_g"]):
        reasons.append(f"weight {weight}g > {cat['max_weight_g']}g")
    # variant keys that are bare supplier codes (Y2681910141, X810 3) cannot be shown to customers as options
    codes = [v.get("variantKey") or v.get("variantNameEn") or "" for v in variants]
    if codes and sum(1 for k in codes if _looks_like_code(k)) > len(codes) // 2 and not cat.get("allow_code_variants"):
        reasons.append("variant options are supplier codes, not customer-facing values")
    text = " ".join([d.get("productNameEn") or "", clean_description(d.get("description")), str(d.get("materialNameEn") or "")])
    hits = banned_hits(text)
    if hits:
        reasons.append(f"banned keywords: {hits}")
    row.update({"name_en": d.get("productNameEn") or row["name_en"], "images": images, "weight_g": weight,
                "material_en": d.get("materialNameEn"), "description_html": d.get("description") or "",
                "variants": [{"vid": v["vid"], "name_en": v.get("variantNameEn"), "key": v.get("variantKey"),
                              "sku": v.get("variantSku"), "usd": price_range(v.get("variantSellPrice"))[1],
                              "weight_g": num_max(v.get("variantWeight")), "image": v.get("variantImage")}
                             for v in variants]})
    if reasons:
        row["gate"] = {"pass": False, "reasons": reasons}
        return row
    first = variants[0]["vid"]
    stock = {s.get("countryCode"): int(s.get("storageNum") or 0) for s in client.stock(first)}
    row["stock"] = stock
    cn, jp = stock.get("CN", 0), stock.get("JP", 0)
    if max(cn, jp) < int(cat["min_stock"]):
        reasons.append(f"stock CN {cn} / JP {jp} < {cat['min_stock']}")
    fr = {}
    opts = client.freight(first, profile["market"]["country"], "CN")
    fr["cn"] = _best_freight(opts, ship["from_cn"]["prefer_names"], int(ship["from_cn"]["max_transit_days"]))
    if jp > 0:
        opts = client.freight(first, profile["market"]["country"], "JP")
        fr["jp"] = _best_freight(opts, ship["from_jp"]["prefer_names"], int(ship["from_jp"]["max_transit_days"]))
    row["freight"] = fr
    use = "jp" if (cat.get("prefer_jp_warehouse") and fr.get("jp") and jp >= int(cat["min_stock"])) else "cn"
    if not fr.get(use):
        reasons.append("no acceptable shipping option to target country")
    else:
        prices = [price_variant(v["usd"], fr[use]["usd"], profile) for v in row["variants"]]
        for v, pv in zip(row["variants"], prices):
            v.update(pv)
        row["ship_from"] = use
        row["price_jpy_min"] = min(p["price_jpy"] for p in prices)
        row["price_jpy_max"] = max(p["price_jpy"] for p in prices)
        row["margin_min"] = min(p["margin"] for p in prices)
        if row["margin_min"] < float(pr["min_margin"]):
            reasons.append(f"margin {row['margin_min']:.2f} < {pr['min_margin']}")
    row["gate"] = {"pass": not reasons, "reasons": reasons}
    if not reasons:
        row["score"] = round(row["listedNum"] * 1.0 + row["margin_min"] * 100 + (30 if use == "jp" else 0) + min(len(images), 8) * 2, 2)
    return row


def discover(client, profile, workdir, log=print):
    cand_path = workdir / "candidates.json"
    state = read_json(cand_path) if cand_path.is_file() else {"schema": "CJBUILD_CANDIDATES_v1", "rows": {}}
    if not state.get("raw"):
        state["raw"] = raw_candidates(client, profile, log)
        state["raw_at"] = iso(now_jst())
        write_json(cand_path, state)
    log(f"raw candidates: {len(state['raw'])}")
    for i, row in enumerate(state["raw"], start=1):
        if row["pid"] in state["rows"]:
            continue
        try:
            state["rows"][row["pid"]] = evaluate(client, profile, dict(row), log)
        except BuildError as exc:
            if exc.code == "CJ_POINTS_LOW":
                write_json(cand_path, state)
                raise
            state["rows"][row["pid"]] = dict(row, gate={"pass": False, "reasons": [f"{exc.code}: {exc.message}"]})
        if i % 10 == 0:
            write_json(cand_path, state)
            log(f"  evaluated {i}/{len(state['raw'])}, points remaining {(client.points or {}).get('remaining')}")
    state["evaluated_at"] = iso(now_jst())
    state["points"] = client.points
    write_json(cand_path, state)
    passed = sorted((r for r in state["rows"].values() if r.get("gate", {}).get("pass")), key=lambda r: -r.get("score", 0))
    return {"candidates": str(cand_path), "raw": len(state["raw"]), "evaluated": len(state["rows"]),
            "passed": len(passed), "top": [{"pid": r["pid"], "name": r["name_en"][:60], "ship_from": r["ship_from"],
                                           "price_jpy": [r["price_jpy_min"], r["price_jpy_max"]],
                                           "margin": r["margin_min"], "score": r["score"]} for r in passed[:15]],
            "points": client.points, "calls": client.calls}


def select(workdir, count, pids=None):
    state = read_json(workdir / "candidates.json")
    rows = [r for r in state["rows"].values() if r.get("gate", {}).get("pass")]
    if pids:
        chosen = [r for r in rows if r["pid"] in set(pids)]
        missing = set(pids) - {r["pid"] for r in chosen}
        if missing:
            raise BuildError("SELECT_INVALID", f"pids not among passing candidates: {sorted(missing)}")
    else:
        # diversity: round-robin across leaf categories by score
        by_cat = {}
        for r in sorted(rows, key=lambda r: -r.get("score", 0)):
            by_cat.setdefault(r["category_path"], []).append(r)
        chosen = []
        while len(chosen) < count and any(by_cat.values()):
            for k in list(by_cat):
                if by_cat[k] and len(chosen) < count:
                    chosen.append(by_cat[k].pop(0))
    sel = {"schema": "CJBUILD_SELECTION_v1", "selected_at": iso(now_jst()), "pids": [r["pid"] for r in chosen]}
    write_json(workdir / "selection.json", sel)
    return {"selection": str(workdir / "selection.json"), "count": len(chosen),
            "items": [{"pid": r["pid"], "name": r["name_en"][:60], "category": r["category_path"].split(" > ")[-1],
                       "price_jpy": r["price_jpy_min"]} for r in chosen]}
