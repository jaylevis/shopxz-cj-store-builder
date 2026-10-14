"""Run the manager skill's Phase 1 (schema-check, apply-rules, validate-data, report) on the exported mapped data.
Read-only: no create API is called. Import (make-confirm + import-file) stays with the manager workflow."""

import json
import subprocess
from pathlib import Path

from .config import BuildError, discover_manager_skill


def _run(manager, script, args, ok=(0,)):
    r = subprocess.run(["node", str(manager / "scripts" / "product-file-import" / script), *args],
                       capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode not in ok:
        raise BuildError("PHASE1_FAILED", f"{script} exit {r.returncode}: {(r.stderr or r.stdout)[-600:]}")
    return r.stdout.strip(), r.returncode


def phase1(workdir, manager_skill=None, out_dir=None):
    manager = discover_manager_skill(manager_skill)
    src = Path(workdir) / "fecify-import"
    out = Path(out_dir or (Path(workdir) / "fecify-phase1"))
    out.mkdir(parents=True, exist_ok=True)
    mapped, rules = src / "products_mapped.ndjson", src / "rules.json"
    if not mapped.is_file():
        raise BuildError("EXPORT_MISSING", "run export first")
    enriched, products = out / "products_enriched.ndjson", out / "products_products.ndjson"
    issues, report_json, report_md = out / "products_issues.ndjson", out / "products_report.json", out / "products_report.md"
    _run(manager, "schema-check.js", [f"--mapped={mapped}", f"--rules={rules}"])
    _run(manager, "apply-rules.js", [str(mapped), str(rules), f"--out={enriched}", f"--products={products}"])
    v_out, code = _run(manager, "validate-data.js", [str(enriched), f"--report={report_json}", f"--issues={issues}",
                                                      f"--image-root={src / 'images'}"], ok=(0, 1, 2))
    _run(manager, "report.js", [f"--summary={src / 'products_summary.json'}", f"--issues={issues}", f"--mapped={mapped}",
                                f"--rules={rules}", f"--out={report_md}"])
    try:
        v = json.loads(v_out)
    except ValueError:
        v = {"raw": v_out[-400:]}
    return {"exit_code": code, "validation": v, "report_md": str(report_md), "products_ndjson": str(products),
            "image_root": str(src / "images"),
            "next": ("show products_report.md to the merchant; after an explicit confirmation run "
                     "make-confirm.js <report_md> then import-file.js <products_ndjson> --image-root=<image_root> "
                     "--confirm-file=<_confirm.json> via the manager skill") if code != 2 else "fix must-fix issues first"}
