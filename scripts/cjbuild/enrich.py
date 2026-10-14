"""AI copy enrichment handshake: the CLI emits tasks, the host AI model fills them, the CLI validates and merges.

No external translation service is ever called here; copy must come from the host AI (or the merchant).
"""

import re

from .config import BuildError, iso, now_jst, read_json, write_json
from .rules import banned_hits, clean_description, html_problems, is_japanese

OUTPUT_SCHEMA = {
    "title_ja": "日本語の商品名（30〜60文字、ブランド名・サプライヤー名なし、型番羅列なし）",
    "handle_en": "URL用の英語スラッグ（小文字英数字とハイフンのみ、3〜6語）",
    "bullets_ja": ["3〜5個の特徴（各40文字以内、事実のみ）"],
    "body_html_ja": "商品説明HTML（<p><ul><li><strong><h3>のみ使用、300〜700文字、素材・サイズ感・使い方・注意点。効能の断定や在庫・期限の煽りは禁止。外部リンク禁止）",
    "options_ja": {"<英語オプション名>": {"name_ja": "カラー/サイズ など", "values_ja": {"<英語値>": "日本語値"}}},
    "tags_ja": ["3〜6個の検索タグ"],
    "meta_title": "60文字以内",
    "meta_description": "80〜120文字",
}


def build_tasks(workdir, profile):
    cand = read_json(workdir / "candidates.json")["rows"]
    sel = read_json(workdir / "selection.json")["pids"]
    tasks = []
    for pid in sel:
        r = cand[pid]
        options = {}
        for v in r["variants"]:
            key = v.get("key") or v.get("name_en") or ""
            # CJ variantKey is like "Blue" or "Blue-M"; option names are not given, so expose raw keys
            parts = [p.strip() for p in str(key).split("-") if p.strip()]
            for idx, part in enumerate(parts):
                options.setdefault(f"option{idx + 1}", [])
                if part not in options[f"option{idx + 1}"]:
                    options[f"option{idx + 1}"].append(part)
        tasks.append({"pid": pid, "input": {
            "title_en": r["name_en"], "category_path": r["category_path"], "material_en": r.get("material_en"),
            "weight_g": r.get("weight_g"), "options": options, "price_jpy": r["price_jpy_min"],
            "description_text": clean_description(r.get("description_html")),
            "ship_from": r["ship_from"], "images": r["images"][:3]},
            "output": None})
    doc = {"schema": "CJBUILD_ENRICH_TASKS_v1", "created_at": iso(now_jst()),
           "instructions": {"language": profile["market"]["language"], "tone": profile["content"]["tone"],
                            "brand_name": profile["content"].get("brand_name") or "(none; do not invent one)",
                            "rules": ["Write every field in natural Japanese for Japanese consumers.",
                                      "Never mention CJ, AliExpress, dropshipping, China shipping or any brand name.",
                                      "No medical/health claims, no scarcity or countdown wording, no fabricated specs.",
                                      "Keep facts consistent with description_text; omit unknown facts instead of guessing.",
                                      "options_ja must map every English option value given in input.options."],
                            "output_schema": OUTPUT_SCHEMA},
           "tasks": tasks}
    write_json(workdir / "enrich" / "tasks.json", doc)
    return {"tasks": str(workdir / "enrich" / "tasks.json"), "count": len(tasks),
            "next": "host AI fills tasks[].output per instructions.output_schema, then run enrich-apply"}


def _validate_output(task, out, profile):
    errs = []
    req = ["title_ja", "handle_en", "bullets_ja", "body_html_ja", "options_ja", "tags_ja", "meta_title", "meta_description"]
    for k in req:
        if k not in out or out[k] in (None, "", [], {}):
            errs.append(f"missing {k}")
    if errs:
        return errs
    t = out["title_ja"]
    if not (8 <= len(t) <= 70) or not is_japanese(t, 0.25):
        errs.append("title_ja length/language")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+){1,7}", out["handle_en"]):
        errs.append("handle_en must be a lowercase ascii slug")
    if not (3 <= len(out["bullets_ja"]) <= 5) or any(len(b) > 60 or not is_japanese(b, 0.2) for b in out["bullets_ja"]):
        errs.append("bullets_ja count/length/language")
    body = out["body_html_ja"]
    plain = re.sub(r"<[^>]+>", "", body)
    if not (200 <= len(plain) <= 1200) or not is_japanese(plain, 0.3):
        errs.append(f"body_html_ja length {len(plain)}/language")
    errs += html_problems(body)
    if not (3 <= len(out["tags_ja"]) <= 8):
        errs.append("tags_ja count")
    if len(out["meta_title"]) > 70:
        errs.append("meta_title > 70")
    if not (40 <= len(out["meta_description"]) <= 140):
        errs.append("meta_description length")
    joined = " ".join([t, body, " ".join(out["bullets_ja"]), " ".join(out["tags_ja"]), out["meta_title"], out["meta_description"]])
    hits = banned_hits(joined)
    if hits:
        errs.append(f"banned words: {hits}")
    for opt, values in task["input"]["options"].items():
        m = (out["options_ja"] or {}).get(opt) or {}
        if not m.get("name_ja"):
            errs.append(f"options_ja.{opt}.name_ja missing")
        missing = [v for v in values if v not in (m.get("values_ja") or {})]
        if missing:
            errs.append(f"options_ja.{opt} values missing {missing}")
    return errs


def apply_tasks(workdir, profile):
    doc = read_json(workdir / "enrich" / "tasks.json")
    enriched, problems, handles = {}, {}, set()
    for task in doc["tasks"]:
        out = task.get("output")
        if not out:
            problems[task["pid"]] = ["output not filled"]
            continue
        errs = _validate_output(task, out, profile)
        if out.get("handle_en") in handles:
            errs.append("duplicate handle_en")
        if errs:
            problems[task["pid"]] = errs
            continue
        handles.add(out["handle_en"])
        enriched[task["pid"]] = out
    if problems:
        write_json(workdir / "enrich" / "problems.json", problems)
        raise BuildError("ENRICH_INVALID", f"{len(problems)} task outputs rejected; fix tasks.json and re-run",
                         {"problems": problems})
    write_json(workdir / "enrich" / "enriched.json",
               {"schema": "CJBUILD_ENRICHED_v1", "applied_at": iso(now_jst()), "products": enriched})
    return {"enriched": str(workdir / "enrich" / "enriched.json"), "count": len(enriched)}
