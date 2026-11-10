"""Turn a pasted product link into a search query (product name).

Tries in order:
1. Fetch page as browser, then as link-preview bots (stores serve them tags)
2. Read product name from URL slug
3. Ask Google (Serper) what this URL / ASIN is
"""
import json
import os
import re
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "TelegramBot (like TwitterBot)",
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "WhatsApp/2.23.20.0 A",
    "Twitterbot/1.0",
]

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

ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})", re.I)


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
    """Read product name from URL path (Amazon/Flipkart style)."""
    path = unquote(urlparse(url).path)
    best = ""
    for seg in (s for s in path.split("/") if s):
        if seg.lower() in {"dp", "p", "gp", "product", "itm"}:
            continue
        if seg.count("-") >= 2 and len(seg) > len(best):
            best = seg
    return _clean(best.replace("-", " "))


def _jsonld_name(soup) -> str:
    """Product name from <script type=application/ld+json>."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                kind = node.get("@type")
                kinds = kind if isinstance(kind, list) else [kind]
                if "Product" in kinds and node.get("name"):
                    return str(node["name"])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return ""


def extract_title(html_text: str) -> str:
    """Best product-name candidate from page HTML."""
    soup = BeautifulSoup(html_text, "html.parser")

    candidates = []
    pt = soup.find(id="productTitle")  # Amazon
    if pt:
        candidates.append(pt.get_text(" ", strip=True))
    candidates.append(_jsonld_name(soup))
    for attrs in ({"property": "og:title"}, {"name": "twitter:title"}):
        m = soup.find("meta", attrs=attrs)
        if m and m.get("content"):
            candidates.append(m["content"])
    if soup.title and soup.title.string:
        candidates.append(soup.title.string)

    for c in candidates:
        if c and not _is_bad(c):
            return c
    return ""


def _fetch(url: str, user_agent: str):
    """Return (html, final_url). Empty html on error pages."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": user_agent, "Accept-Language": "en-IN,en;q=0.9"},
            timeout=12,
            allow_redirects=True,
        )
    except Exception:
        return "", url
    if resp.status_code >= 400:
        return "", resp.url
    return resp.text, resp.url


def _title_via_search(url: str) -> str:
    """Last resort: ask Google what this URL / ASIN is."""
    key = os.getenv("SERPER_API_KEY")
    if not key:
        return ""
    asin_match = ASIN_RE.search(url)
    asin = asin_match.group(1).lower() if asin_match else ""
    host = urlparse(url).netloc.lower().replace("www.", "")
    query = f"{asin} amazon.in" if asin else url
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "gl": "in"},
            timeout=12,
        )
        r.raise_for_status()
        for o in r.json().get("organic", [])[:5]:
            link = (o.get("link") or "").lower()
            same = (asin in link) if asin else (host and host in link)
            if same and not _is_bad(o.get("title", "")):
                return o["title"]
    except Exception:
        pass
    return ""


def get_product_query(url: str):
    """Return (search_query, final_url). Raise ValueError if name not found."""
    final_url = url

    # 1. page title, several user agents
    for ua in USER_AGENTS:
        page, final_url = _fetch(url, ua)
        if page:
            title = extract_title(page)
            if title:
                return _clean(title), final_url

    # 2. name inside URL
    slug = _slug_title(final_url)
    if len(slug.split()) >= 3:
        return slug, final_url

    # 3. Google lookup
    title = _title_via_search(final_url)
    if title:
        return _clean(title), final_url

    raise ValueError("Could not read product name from this link.")