"""Product images: download originals, convert to WebP (fecify optimize-webp.py), optional AI re-shoot via
the configured fecify image provider (scripts/image-edit.js bridge). Originals are kept for audit only."""

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from .config import BuildError, SKILL_ROOT, discover_manager_skill, iso, now_jst, read_json, write_json

UA = {"User-Agent": "Mozilla/5.0 (compatible; cjbuild/0.1)"}


def _download(url, dest):
    if dest.exists():
        return dest
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    if len(data) < 2000:
        raise BuildError("IMAGE_DOWNLOAD", f"{url}: suspiciously small ({len(data)} bytes)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def _webp(manager, src, dst, max_width=1600, target_kb=300):
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    py = os.environ.get("PYTHON_BIN") or sys.executable
    r = subprocess.run([py, str(manager / "scripts" / "theme" / "optimize-webp.py"), "--input", str(src), "--out", str(dst),
                        "--max-width", str(max_width), "--target-kb", str(target_kb)],
                       capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not dst.exists():
        raise BuildError("WEBP_FAILED", f"{src.name}: {r.stderr[-300:] or r.stdout[-300:]}")
    return dst


def _ai_edit(manager, ref, dst, prompt, size="1024x1024", quality="medium"):
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["node", str(SKILL_ROOT / "scripts" / "image-edit.js"), "--ref", str(ref), "--out", str(dst),
                        "--prompt", prompt, "--size", size, "--quality", quality, "--manager-skill", str(manager)],
                       capture_output=True, encoding="utf-8", errors="replace", timeout=600)
    if r.returncode != 0 or not dst.exists():
        raise BuildError("AI_EDIT_FAILED", f"{ref.name}: {(r.stderr or r.stdout)[-400:]}")
    return dst


def process_images(workdir, profile, manager_skill=None, pids=None, ai=None, log=print):
    manager = discover_manager_skill(manager_skill)
    cand = read_json(workdir / "candidates.json")["rows"]
    sel = pids or read_json(workdir / "selection.json")["pids"]
    content = profile["content"]
    ai_mode = (content.get("image_mode") == "ai-edit") if ai is None else ai
    root = workdir / "images"
    man_path = root / "manifest.json"
    manifest = read_json(man_path) if man_path.is_file() else {"schema": "CJBUILD_IMAGES_v1", "products": {}}
    for pid in sel:
        r = cand[pid]
        if pid in manifest["products"] and manifest["products"][pid].get("complete"):
            continue
        entry = manifest["products"].get(pid) or {"originals": [], "webp": [], "ai": [], "variant_images": {}, "errors": []}
        urls = []
        for u in r["images"][: int(content.get("max_images_per_product", 6))]:
            if u not in urls:
                urls.append(u)
        vurls = {v["vid"]: v.get("image") for v in r["variants"] if v.get("image")}
        for u in vurls.values():
            if u not in urls and len(urls) < int(content.get("max_images_per_product", 6)) + len(vurls):
                urls.append(u)
        pdir = root / pid
        entry["originals"], entry["webp"] = [], []
        for i, u in enumerate(urls, start=1):
            h = hashlib.sha1(u.encode()).hexdigest()[:10]
            try:
                orig = _download(u, pdir / "orig" / f"{i:02d}-{h}{Path(u).suffix.lower() or '.jpg'}")
                webp = _webp(manager, orig, pdir / "webp" / f"{i:02d}-{h}.webp")
            except BuildError as exc:
                entry["errors"].append(exc.message)
                continue
            entry["originals"].append({"url": u, "file": str(orig)})
            entry["webp"].append({"url": u, "file": str(webp)})
        for vid, u in vurls.items():
            hit = next((w["file"] for w in entry["webp"] if w["url"] == u), None)
            if hit:
                entry["variant_images"][vid] = hit
        if ai_mode and entry["webp"]:
            entry["ai"] = []
            prompt = f"{content['image_style']}. Product: {r['name_en'][:120]}"
            for w in entry["webp"][: int(content.get("ai_images_per_product", 2))]:
                try:
                    out = _ai_edit(manager, Path(w["file"]), pdir / "ai" / Path(w["file"]).name, prompt)
                    entry["ai"].append({"source": w["file"], "file": str(out)})
                except BuildError as exc:
                    entry["errors"].append(exc.message)
        entry["complete"] = bool(entry["webp"]) and (not ai_mode or bool(entry["ai"]) or bool(entry["errors"]))
        manifest["products"][pid] = entry
        write_json(man_path, manifest)
        log(f"  {pid}: webp {len(entry['webp'])} ai {len(entry.get('ai', []))} errors {len(entry['errors'])}")
    manifest["updated_at"] = iso(now_jst())
    write_json(man_path, manifest)
    done = sum(1 for p in sel if manifest["products"].get(p, {}).get("complete"))
    errs = {p: manifest["products"][p]["errors"] for p in sel if manifest["products"].get(p, {}).get("errors")}
    return {"manifest": str(man_path), "complete": done, "selected": len(sel), "with_errors": errs}


def final_images(manifest_entry, prefer_ai=True):
    """Ordered list of local files to upload: AI versions first (if any), then remaining WebP originals."""
    ai_src = {a["source"]: a["file"] for a in manifest_entry.get("ai", [])} if prefer_ai else {}
    out = []
    for w in manifest_entry.get("webp", []):
        out.append(ai_src.get(w["file"], w["file"]))
    return out
