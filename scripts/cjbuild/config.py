"""Credentials, token cache, manager-skill discovery and small IO helpers.

Credentials never live inside the skill package. The CJ env file (CJ_EMAIL / CJ_API_KEY) is read from
FECIFY_CJ_ENV or %LOCALAPPDATA%/Fecify/cj/cj.env; the access token is cached next to it.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
ASSETS = SKILL_ROOT / "assets"
JST = timezone(timedelta(hours=9))
MANAGER_NAME = "fecify-site-manager-v6"


class BuildError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}

    def to_dict(self):
        return {"ok": False, "error": self.code, "message": self.message, "details": self.details}


def now_jst():
    return datetime.now(JST)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def emit(obj):
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cj_data_dir():
    if os.environ.get("FECIFY_CJ_ENV"):
        return Path(os.environ["FECIFY_CJ_ENV"]).resolve().parent
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Fecify" / "cj"


def load_cj_credentials():
    env_file = Path(os.environ.get("FECIFY_CJ_ENV") or (cj_data_dir() / "cj.env"))
    creds = {"CJ_EMAIL": os.environ.get("CJ_EMAIL", ""), "CJ_API_KEY": os.environ.get("CJ_API_KEY", "")}
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                creds.setdefault(k.strip(), "")
                if not creds.get(k.strip()):
                    creds[k.strip()] = v.strip()
    if not creds.get("CJ_EMAIL") or not creds.get("CJ_API_KEY"):
        raise BuildError("CJ_CREDENTIALS_MISSING",
                         f"CJ_EMAIL / CJ_API_KEY not found (env or {env_file}); never pass them on the command line")
    return creds


def token_cache_path():
    return cj_data_dir() / "token.json"


def load_cached_token():
    p = token_cache_path()
    if not p.is_file():
        return None
    try:
        t = read_json(p)
        exp = datetime.fromisoformat(t["expiry"])
        if exp - datetime.now(exp.tzinfo) > timedelta(days=1):
            return t["accessToken"]
    except (KeyError, ValueError, OSError):
        return None
    return None


def save_cached_token(token, expiry_text):
    write_json(token_cache_path(), {"accessToken": token, "expiry": expiry_text})


def discover_manager_skill(explicit=None):
    cands = []
    if explicit:
        cands.append(Path(explicit))
    if os.environ.get("FECIFY_SKILL_DIR"):
        cands.append(Path(os.environ["FECIFY_SKILL_DIR"]))
    cands += [SKILL_ROOT.parent / MANAGER_NAME, Path.home() / ".claude" / "skills" / MANAGER_NAME,
              Path.home() / ".codex" / "skills" / MANAGER_NAME]
    for c in cands:
        if (c / "scripts" / "proxy" / "api-call.js").is_file():
            pkg = c / "package.json"
            if pkg.is_file():
                try:
                    name = read_json(pkg).get("name")
                    if name and name != MANAGER_NAME:
                        raise BuildError("MANAGER_VERSION_MISMATCH", f"{c} is {name}; {MANAGER_NAME} required")
                except (OSError, ValueError):
                    pass
            return c.resolve()
    raise BuildError("MANAGER_NOT_FOUND", f"{MANAGER_NAME} not found (set FECIFY_SKILL_DIR or --manager-skill)")
