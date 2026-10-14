"""Export the selection as a Fecify product-import data file (+ local image root) and shipping/returns facts
for shopxz-japan-launch. Nothing here writes to the store; import goes through the manager skill's gated workflow."""

import csv
import json
import shutil
from pathlib import Path

from .config import BuildError, iso, now_jst, read_json, write_json
from .images import final_images

OPTION_FALLBACK = {"option1": "タイプ", "option2": "サイズ", "option3": "カラー"}


def _options_for(row, out):
    """Map CJ variantKey parts ('Blue-M') onto option1/2/3 with Japanese names and values."""
    opts = {}
    for v in row["variants"]:
        parts = [p.strip() for p in str(v.get("key") or v.get("name_en") or "").split("-") if p.strip()]
        v["_parts"] = parts
        for i, part in enumerate(parts):
            opts.setdefault(f"option{i + 1}", [])
            if part not in opts[f"option{i + 1}"]:
                opts[f"option{i + 1}"].append(part)
    result = []
    for i, (key, values) in enumerate(opts.items(), start=1):
        m = (out.get("options_ja") or {}).get(key) or {}
        vals = m.get("values_ja") or {}
        result.append({"name": m.get("name_ja") or OPTION_FALLBACK.get(key, key), "position": i,
                       "items": [vals.get(v, v) for v in values], "_map": vals})
    return result


def export(workdir, profile, out_dir=None, log=print):
    cand = read_json(workdir / "candidates.json")["rows"]
    sel = read_json(workdir / "selection.json")["pids"]
    enriched = read_json(workdir / "enrich" / "enriched.json")["products"]
    manifest = read_json(workdir / "images" / "manifest.json")["products"]
    out_dir = Path(out_dir or (workdir / "fecify-import"))
    image_root = out_dir / "images"
    if image_root.exists():
        shutil.rmtree(image_root)
    image_root.mkdir(parents=True)
    products, summary, skipped = [], [], {}
    cap = int(profile["pricing"].get("stock_cap", 50))
    for pid in sel:
        r, out, imgs = cand[pid], enriched.get(pid), manifest.get(pid)
        if not out or not imgs or not imgs.get("webp"):
            skipped[pid] = "missing enrichment or images"
            continue
        files = final_images(imgs, prefer_ai=profile["content"].get("image_mode") == "ai-edit")
        pdir = image_root / out["handle_en"]
        pdir.mkdir(parents=True, exist_ok=True)
        rel_images = []
        for i, f in enumerate(files, start=1):
            dst = pdir / f"{i:02d}.webp"
            shutil.copyfile(f, dst)
            rel_images.append({"src": str(dst.relative_to(image_root)).replace("\\", "/"), "position": i, "_from": f})
        options = _options_for(r, out)
        vmap = {Path(f).name: rel for f, rel in ((p["_from"], p["src"]) for p in rel_images)}
        stock = r.get("stock") or {}
        qty = min(cap, max(stock.get("JP", 0), stock.get("CN", 0)) if r["ship_from"] == "cn" else stock.get("JP", 0))
        variants = []
        for idx, v in enumerate(r["variants"], start=1):
            row = {"price": str(v["price_jpy"]), "qty": str(qty), "weight": str(int(v.get("weight_g") or r["weight_g"] or 0)),
                   "weight_unit": "g", "sku": f"CJ-{pid[-8:]}-{idx:02d}", "compare_at_price": "", "cost_price": str(v["landed_jpy"])}
            for i, part in enumerate(v.get("_parts") or []):
                row[f"option{i + 1}"] = options[i]["_map"].get(part, part) if i < len(options) else part
            vimg = (imgs.get("variant_images") or {}).get(v["vid"])
            if vimg:
                ai = {a["source"]: a["file"] for a in imgs.get("ai", [])}
                chosen = ai.get(vimg, vimg) if profile["content"].get("image_mode") == "ai-edit" else vimg
                rel = next((p["src"] for p in rel_images if p["_from"] == chosen), "")
                row["image"] = rel
            variants.append(row)
        body = out["body_html_ja"]
        if out.get("bullets_ja"):
            body = "<ul>" + "".join(f"<li>{b}</li>" for b in out["bullets_ja"]) + "</ul>" + body
        products.append({
            "_id": pid, "title": out["title_ja"], "handle": out["handle_en"], "price": str(r["price_jpy_min"]),
            "qty": str(qty), "sku": f"CJ-{pid[-8:]}", "weight": str(int(r["weight_g"] or 0)), "weight_unit": "g",
            "body_html": body, "vendor": "", "spu": "", "status": "上架",
            "meta_title": out["meta_title"], "meta_description": out["meta_description"],
            "images": [{"src": p["src"], "position": p["position"]} for p in rel_images],
            "options": [{"name": o["name"], "position": o["position"], "items": o["items"]} for o in options],
            "variants": variants, "tags": out["tags_ja"], "collection_ids": [],
            "_source": {"cj_pid": pid, "ship_from": r["ship_from"], "freight": r["freight"].get(r["ship_from"]),
                        "category_path": r["category_path"], "margin_min": r["margin_min"]},
        })
        summary.append({"pid": pid, "handle": out["handle_en"], "title": out["title_ja"], "price_jpy": r["price_jpy_min"],
                        "variants": len(variants), "images": len(rel_images), "ship_from": r["ship_from"],
                        "margin": r["margin_min"], "category": r["category_path"]})
    if not products:
        raise BuildError("EXPORT_EMPTY", "no product is complete (enrichment + images)", {"skipped": skipped})
    write_json(out_dir / "products.json", products)
    # mapped ndjson for the manager pipeline (step 5 onwards): one product per line, schema = _mapped.schema.json
    with open(out_dir / "products_mapped.ndjson", "w", encoding="utf-8", newline="\n") as fh:
        for prod in products:
            rec = {k: v for k, v in prod.items() if k != "_source"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    write_json(out_dir / "products_summary.json", {"source": str(out_dir / "products_mapped.ndjson"), "format": "ndjson",
                                                   "encoding": "utf-8", "encodingConfidence": 1, "rowCount": len(products),
                                                   "sampleRate": 1, "note": "generated by shopxz-cj-store-builder export"})
    write_json(out_dir / "rules.json", {"defaults": {"bodyHtml": "none", "autoBodyHtml": False, "autoMeta": False,
                                                     "sku": {"enabled": False, "mode": "none"}, "collectionMatch": False,
                                                     "importConcurrency": 3, "uploadConcurrency": 3, "randomPrecision": 2},
                                        "rules": [], "note": "all fields are explicit; nothing is derived or randomised"})
    with open(out_dir / "summary.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    write_json(out_dir / "policies.json", shipping_facts(cand, sel, profile))
    return {"out_dir": str(out_dir), "products": len(products), "skipped": skipped,
            "image_root": str(image_root), "mapped": str(out_dir / "products_mapped.ndjson"),
            "next": "python scripts/cjbuild.py phase1 --workdir <run>  (manager-skill validation + report; import only after merchant confirmation)"}


def shipping_facts(cand, sel, profile):
    """Truthful shipping facts derived from the chosen CJ logistics, for policies and shopxz-japan-launch."""
    rows = [cand[p] for p in sel if cand[p].get("gate", {}).get("pass")]
    by = {}
    for r in rows:
        f = r["freight"].get(r["ship_from"]) or {}
        by.setdefault(r["ship_from"], []).append(f)
    out = {"schema": "CJBUILD_POLICIES_v1", "generated_at": iso(now_jst()),
           "handling_business_days": profile["shipping"]["handling_business_days"], "lanes": {}}
    for lane, fs in by.items():
        out["lanes"][lane] = {"products": len(fs), "carriers": sorted({f.get("name") for f in fs if f}),
                              "transit_days_min": min(f["days_min"] for f in fs), "transit_days_max": max(f["days_max"] for f in fs),
                              "freight_usd_avg": round(sum(f["usd"] for f in fs) / len(fs), 2)}
    worst = max((l["transit_days_max"] for l in out["lanes"].values()), default=None)
    out["policy_text_ja"] = {
        "発送時期": f"ご注文確定後（入金確認後）{out['handling_business_days'][0]}〜{out['handling_business_days'][1]}営業日以内に発送いたします。",
        "お届け日数": (f"発送後、通常{min(l['transit_days_min'] for l in out['lanes'].values())}〜{worst}日程度でお届けします（追跡番号付き）。"
                  "海外倉庫から発送する商品は、通関状況によりお届けが前後する場合があります。") if worst else "",
        "note": "shopxz-japan-launch profile: shipping.handling_business_days and shipping.transit_business_days should use these values",
    }
    out["transit_business_days"] = [min(l["transit_days_min"] for l in out["lanes"].values()), worst] if worst else None
    return out
