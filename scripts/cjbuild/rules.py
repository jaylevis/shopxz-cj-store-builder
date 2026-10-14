"""Compliance rules: banned brand / prohibited keywords, description cleaning, Japanese text checks."""

import html
import re

from .config import ASSETS, read_json

_RULES = None


def rules():
    global _RULES
    if _RULES is None:
        _RULES = read_json(ASSETS / "banned-keywords.json")
    return _RULES


def banned_hits(text):
    """Return the banned keywords found in text (brands, prohibited goods, supplier names)."""
    t = (text or "").lower()
    hits = []
    for group in ("brands", "prohibited", "suppliers"):
        for kw in rules().get(group, []):
            if re.search(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])", t):
                hits.append(kw)
    return sorted(set(hits))


def excluded_category(path_text, extra=()):
    t = (path_text or "").lower()
    return [kw for kw in list(rules().get("excluded_categories", [])) + list(extra) if kw.lower() in t]


_TAG = re.compile(r"<[^>]+>")


def clean_description(html_text, limit=1800):
    """CJ descriptions are supplier HTML with embedded images; keep plain facts only."""
    if not html_text:
        return ""
    s = re.sub(r"<img[^>]*>", " ", html_text, flags=re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", s, flags=re.I)
    s = html.unescape(_TAG.sub(" ", s))
    s = re.sub(r"[ \t　]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s).strip()
    # drop supplier boilerplate lines
    keep = []
    for line in s.splitlines():
        l = line.strip()
        if not l or re.search(r"packaging list|package includes|note:|due to the light|please allow|tips:", l, re.I):
            continue
        keep.append(l)
    out = "\n".join(keep)
    return out[:limit]


JA = re.compile(r"[぀-ヿ㐀-鿿]")


def is_japanese(text, min_ratio=0.3):
    if not text:
        return False
    letters = [c for c in text if not c.isspace()]
    return bool(letters) and sum(1 for c in letters if JA.match(c)) / len(letters) >= min_ratio


ALLOWED_TAGS = {"p", "br", "ul", "ol", "li", "strong", "b", "em", "h2", "h3", "table", "tbody", "tr", "th", "td"}


def html_problems(body):
    probs = []
    for tag in re.findall(r"<\s*/?\s*([a-zA-Z0-9]+)", body or ""):
        if tag.lower() not in ALLOWED_TAGS:
            probs.append(f"tag <{tag}> not allowed")
    if re.search(r"https?://", body or ""):
        probs.append("external links are not allowed in body_html")
    if re.search(r"<script|onerror=|onclick=", body or "", re.I):
        probs.append("script/handlers not allowed")
    return sorted(set(probs))
