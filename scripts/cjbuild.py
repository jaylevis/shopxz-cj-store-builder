#!/usr/bin/env python3
"""shopxz-cj-store-builder CLI. All output is UTF-8 JSON on stdout; progress goes to stderr."""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cjbuild import VERSION  # noqa: E402
from cjbuild.cj_api import CJClient  # noqa: E402
from cjbuild.config import ASSETS, BuildError, emit, iso, now_jst, read_json, write_json  # noqa: E402


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def fetch_fx():
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=30) as r:
            d = json.load(r)
        return float(d["rates"]["JPY"]), f"open.er-api.com {d.get('time_last_update_utc')}"
    except Exception as exc:  # noqa: BLE001
        raise BuildError("FX_UNAVAILABLE", f"could not fetch USD/JPY: {exc}; set pricing.fx_usd_jpy manually")


def cmd_profile(a):
    p = read_json(ASSETS / "profiles" / "jp-core.json")
    if a.categories:
        p["catalog"]["categories"] = [c.strip() for c in a.categories.split(",") if c.strip()]
    if a.keywords:
        p["catalog"]["keywords"] = [k.strip() for k in a.keywords.split(",") if k.strip()]
    if a.count:
        p["catalog"]["target_count"] = int(a.count)
    if a.brand:
        p["content"]["brand_name"] = a.brand
    if a.fx:
        p["pricing"]["fx_usd_jpy"], p["pricing"]["fx_source"] = float(a.fx), "manual"
    else:
        p["pricing"]["fx_usd_jpy"], p["pricing"]["fx_source"] = fetch_fx()
    p["created_at"] = iso(now_jst())
    write_json(a.out, p)
    emit({"ok": True, "profile": str(a.out), "fx_usd_jpy": p["pricing"]["fx_usd_jpy"], "fx_source": p["pricing"]["fx_source"],
          "categories": p["catalog"]["categories"], "target_count": p["catalog"]["target_count"],
          "note": "review pricing.markup / min_margin and catalog filters before discover"})


def cmd_auth(a):
    c = CJClient()
    c.authenticate(force=a.force)
    cats = c.categories()
    emit({"ok": True, "authenticated": True, "top_categories": [x.get("categoryFirstName") for x in cats], "points": c.points})


def cmd_categories(a):
    c = CJClient()
    tree = c.categories()
    rows = []
    for one in tree:
        for two in one.get("categoryFirstList") or []:
            for three in two.get("categorySecondList") or []:
                path = f"{one.get('categoryFirstName')} > {two.get('categorySecondName')} > {three.get('categoryName')}"
                if not a.filter or a.filter.lower() in path.lower():
                    rows.append({"id": three.get("categoryId"), "path": path})
    emit({"ok": True, "count": len(rows), "categories": rows})


def cmd_discover(a):
    from cjbuild.discover import discover
    profile = read_json(a.profile)
    if not profile["pricing"].get("fx_usd_jpy"):
        raise BuildError("PROFILE_INVALID", "pricing.fx_usd_jpy missing")
    work = Path(a.workdir)
    work.mkdir(parents=True, exist_ok=True)
    emit({"ok": True, **discover(CJClient(), profile, work, log)})


def cmd_select(a):
    from cjbuild.discover import select
    emit({"ok": True, **select(Path(a.workdir), int(a.count), a.pids.split(",") if a.pids else None)})


def cmd_enrich_tasks(a):
    from cjbuild.enrich import build_tasks
    emit({"ok": True, **build_tasks(Path(a.workdir), read_json(a.profile))})


def cmd_enrich_apply(a):
    from cjbuild.enrich import apply_tasks
    emit({"ok": True, **apply_tasks(Path(a.workdir), read_json(a.profile))})


def cmd_images(a):
    from cjbuild.images import process_images
    ai = None if a.ai == "profile" else (a.ai == "on")
    emit({"ok": True, **process_images(Path(a.workdir), read_json(a.profile), a.manager_skill,
                                       a.pids.split(",") if a.pids else None, ai, log)})


def cmd_export(a):
    from cjbuild.export import export
    emit({"ok": True, **export(Path(a.workdir), read_json(a.profile), a.out, log)})


def cmd_phase1(a):
    from cjbuild.phase1 import phase1
    emit({"ok": True, **phase1(Path(a.workdir), a.manager_skill, a.out)})


def main():
    ap = argparse.ArgumentParser(prog="cjbuild", description="Build a fulfillable ShopXZ/Fecify catalog from CJ Dropshipping.")
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("profile", help="create a market profile from the jp-core preset (fetches USD/JPY)")
    s.add_argument("--out", required=True); s.add_argument("--categories"); s.add_argument("--keywords")
    s.add_argument("--count", type=int); s.add_argument("--brand"); s.add_argument("--fx", type=float)
    s.set_defaults(fn=cmd_profile)
    s = sub.add_parser("auth", help="verify CJ credentials (env file) and cache the access token")
    s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_auth)
    s = sub.add_parser("categories", help="list CJ leaf categories"); s.add_argument("--filter"); s.set_defaults(fn=cmd_categories)
    s = sub.add_parser("discover", help="read-only candidate discovery with fulfillability gate (resumable)")
    s.add_argument("--profile", required=True); s.add_argument("--workdir", required=True); s.set_defaults(fn=cmd_discover)
    s = sub.add_parser("select", help="pick N passing candidates (diverse across categories) or explicit pids")
    s.add_argument("--workdir", required=True); s.add_argument("--count", default=40); s.add_argument("--pids"); s.set_defaults(fn=cmd_select)
    s = sub.add_parser("enrich-tasks", help="emit Japanese copy tasks for the host AI")
    s.add_argument("--profile", required=True); s.add_argument("--workdir", required=True); s.set_defaults(fn=cmd_enrich_tasks)
    s = sub.add_parser("enrich-apply", help="validate filled tasks and write enriched.json")
    s.add_argument("--profile", required=True); s.add_argument("--workdir", required=True); s.set_defaults(fn=cmd_enrich_apply)
    s = sub.add_parser("images", help="download originals, convert to WebP, optional AI re-shoot")
    s.add_argument("--profile", required=True); s.add_argument("--workdir", required=True); s.add_argument("--manager-skill")
    s.add_argument("--pids"); s.add_argument("--ai", choices=["profile", "on", "off"], default="profile"); s.set_defaults(fn=cmd_images)
    s = sub.add_parser("export", help="write Fecify import data file + image root + shipping facts")
    s.add_argument("--profile", required=True); s.add_argument("--workdir", required=True); s.add_argument("--out"); s.set_defaults(fn=cmd_export)
    s = sub.add_parser("phase1", help="manager-skill Phase 1 validation + report on the export (read-only)")
    s.add_argument("--workdir", required=True); s.add_argument("--manager-skill"); s.add_argument("--out"); s.set_defaults(fn=cmd_phase1)
    a = ap.parse_args()
    try:
        a.fn(a)
    except BuildError as exc:
        emit(exc.to_dict())
        sys.exit(1)


if __name__ == "__main__":
    main()
