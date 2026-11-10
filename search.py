"""Find prices across stores using Serper.dev (Google Shopping API).
Marks each result as exact match or similar, by comparing model / spec numbers."""
import os
import re

import requests

import cache

SERPER_URL = "https://google.serper.dev/shopping"

UNIT_RE = re.compile(r"(\d)\s+(gb|tb|mb|inch|hz|mp|mah|kg|w)\b", re.I)
MEM_RE = re.compile(r"(\d+)(gb|tb)")
SKIP_RE = re.compile(r"(lp)?ddr\d|\d+(st|nd|rd|th)|5g|4g")  # stores often omit these


def _parse_price(text: str):
    if not text:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def _tokens(text: str):
    text = UNIT_RE.sub(r"\1\2", (text or "").lower())  # "512 GB" -> "512gb"
    toks = set(re.findall(r"[a-z0-9]+", text))
    for t in list(toks):
        m = MEM_RE.fullmatch(t)
        if m:
            toks.add(m.group(1))  # "512gb" also counts as "512"
    return toks


def _spec_tokens(query: str):
    """Tokens that identify exact variant: model numbers, RAM, storage, sizes."""
    text = UNIT_RE.sub(r"\1\2", query.lower())
    out = []
    for t in re.findall(r"[a-z0-9]+", text):
        if not any(c.isdigit() for c in t):
            continue
        if SKIP_RE.fullmatch(t):  # 14th gen, DDR4: stores often skip it
            continue
        if t.isdigit() and len(t) == 1:  # lone "3" from "Core 3" etc.
            continue
        out.append(t)
    return out


def _spec_hit(spec: str, result_tokens) -> bool:
    if spec in result_tokens:
        return True
    m = MEM_RE.fullmatch(spec)
    return bool(m and m.group(1) in result_tokens)


def match_level(query: str, title: str):
    """Return 'exact', 'similar' or None."""
    q_list = re.findall(r"[a-z0-9]+", query.lower())
    t = _tokens(title)
    if not q_list or not t:
        return None

    brand = next((w for w in q_list if w.isalpha() and len(w) > 2), None)
    if brand and brand not in t:
        return None

    q = set(q_list)
    overlap = len(q & t) / len(q)

    specs = _spec_tokens(query)
    if specs:
        hit = sum(_spec_hit(s, t) for s in specs) / len(specs)
    else:
        hit = 1.0

    if hit == 1.0 and overlap >= 0.5:
        return "exact"
    if hit >= 0.7 and overlap >= 0.4:
        return "similar"
    return None


def search_prices(query: str, limit: int = 8):
    """Return list of dicts: title, store, price, price_text, link, match.
    Exact matches first (cheapest first), then similar."""
    cached = cache.get(query)
    if cached is not None:
        return cached[:limit]

    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError("SERPER_API_KEY missing in .env")

    resp = requests.post(
        SERPER_URL,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "gl": "in", "hl": "en", "num": 40},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("shopping", [])

    best = {}  # one entry per (store, match level): cheapest
    for it in items:
        price = _parse_price(it.get("price", ""))
        link = it.get("link")
        if price is None or not link:
            continue
        level = match_level(query, it.get("title", ""))
        if not level:
            continue
        store = it.get("source", "Unknown store")
        key = (store, level)
        entry = {
            "title": it.get("title", ""),
            "store": store,
            "price": price,
            "price_text": it.get("price", ""),
            "link": link,
            "match": level,
        }
        if key not in best or price < best[key]["price"]:
            best[key] = entry

    results = sorted(
        best.values(), key=lambda r: (r["match"] != "exact", r["price"])
    )
    if results:  # do not cache empty lookups
        cache.put(query, results)
    return results[:limit]