"""Find prices across stores using Serper.dev (Google Shopping API)."""
import os
import re

import requests

import cache

SERPER_URL = "https://google.serper.dev/shopping"


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
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _is_relevant(query: str, title: str) -> bool:
    """Keep only results that look like the same product.
    Brand (first real word) must match and half of query words must appear."""
    q_list = re.findall(r"[a-z0-9]+", query.lower())
    t = _tokens(title)
    if not q_list or not t:
        return False
    brand = next((w for w in q_list if w.isalpha() and len(w) > 2), None)
    if brand and brand not in t:
        return False
    q = set(q_list)
    return len(q & t) / len(q) >= 0.5


def search_prices(query: str, limit: int = 5):
    """Return list of dicts sorted by price, cheapest first.
    Each dict: title, store, price, price_text, link."""
    cached = cache.get(query)
    if cached is not None:
        return cached[:limit]

    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError("SERPER_API_KEY missing in .env")

    resp = requests.post(
        SERPER_URL,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "gl": "in", "hl": "en", "num": 20},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("shopping", [])

    cheapest_per_store = {}
    for it in items:
        price = _parse_price(it.get("price", ""))
        link = it.get("link")
        if price is None or not link:
            continue
        if not _is_relevant(query, it.get("title", "")):
            continue
        store = it.get("source", "Unknown store")
        entry = {
            "title": it.get("title", ""),
            "store": store,
            "price": price,
            "price_text": it.get("price", ""),
            "link": link,
        }
        if store not in cheapest_per_store or price < cheapest_per_store[store]["price"]:
            cheapest_per_store[store] = entry

    results = sorted(cheapest_per_store.values(), key=lambda x: x["price"])
    if results:  # do not cache empty/bad lookups
        cache.put(query, results)
    return results[:limit]