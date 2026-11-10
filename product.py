"""Turn a pasted product link into a search query (product name)."""
import re
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# Shops serve full product tags to link-preview bots (Telegram shows them too)
PREVIEW_UA = "TelegramBot (like TwitterBot)"

BLOCK_HINTS = (
    "robot check", "captcha", "access denied", "are you a human", "page not found",
    "service unavailable", "503", "502", "403", "404", "forbidden",
    "something went wrong", "too many requests", "not found",
)

GENERIC_TITLES = {
    "amazon", "amazon.in", "amazon.com", "flipkart", "flipkart.com",
    "myntra", "online shopping", "amazon.in: online shopping",
}

JUNK_PATTERNS = [
    r"^amazon\.in\s*:\s*",
    r"^amazon\.com\s*:\s*",
    r"^buy\s+",
    r"\s+online\s+at\s+best.*$",
    r"\s*[|\-–]\s*flipkart\.com.*$",
    r"\s*[|\-–]\s*amazon\.in.*$",
    r"\s*[|\-–]\s*myntra.*$",
    r"\s+at\s+best\s+price.*$",
    r"\s+price\s+in\s+india.*$",
]


FLUFF = {
    "with", "and", "for", "the", "of", "in", "by", "new", "latest", "buy",
    "processor", "display", "graphics", "included", "warranty", "renewed",
}


def _clean(title: str) -> str:
    title = title.strip()
    for pat in JUNK_PATTERNS:
        title = re.sub(pat, "", title, flags=re.I)
    title = re.sub(r"\([^)]*\)", " ", title)  # drop (Previously Inspiron), (Black) etc.
    title = re.sub(r"[,/|;:]", " ", title)  # punctuation -> space
    words, seen = [], set()
    for w in title.split():
        key = w.lower()
        if key in FLUFF or key in seen:
            continue
        seen.add(key)
        words.append(w)
    return " ".join(words[:14])  # keep specs (RAM, storage, model) but stay short


def _is_bad(title: str) -> bool:
    """Title is empty, blocked page, store name only, or too short to search."""
    t = (title or "").strip().lower()
    if not t or any(h in t for h in BLOCK_HINTS) or t in GENERIC_TITLES:
        return True
    cleaned = _clean(title)
    return len(cleaned.split()) < 3 or cleaned.lower() in GENERIC_TITLES


def _slug_title(url: str) -> str:
    """Fallback: read product name from URL path (Amazon/Flipkart style)."""
    path = unquote(urlparse(url).path)
    best = ""
    for seg in (s for s in path.split("/") if s):
        if seg.lower() in {"dp", "p", "gp", "product", "itm"}:
            continue
        if seg.count("-") >= 2 and len(seg) > len(best):
            best = seg
    return _clean(best.replace("-", " "))


def _fetch_title(url: str, user_agent: str):
    """Return (title, final_url). Empty title on failure."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": user_agent, "Accept-Language": "en-IN,en;q=0.9"},
            timeout=12,
            allow_redirects=True,
        )
    except Exception:
        return "", url

    if resp.status_code >= 400:  # blocked / error page: title is useless
        return "", resp.url

    soup = BeautifulSoup(resp.text, "html.parser")
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"], resp.url
    if soup.title and soup.title.string:
        return soup.title.string, resp.url
    return "", resp.url


def get_product_query(url: str):
    """Return (search_query, final_url). Raise ValueError if name not found."""
    final_url = url

    for ua in (BROWSER_UA, PREVIEW_UA):
        title, final_url = _fetch_title(url, ua)
        if not _is_bad(title):
            return _clean(title), final_url

    slug = _slug_title(final_url)
    if len(slug.split()) >= 3:
        return slug, final_url

    raise ValueError("Could not read product name from this link.")