"""Add affiliate ids to Amazon / Flipkart links (optional)."""
import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def affiliate(url: str) -> str:
    try:
        parts = urlparse(url)
        host = parts.netloc.lower()
        query = dict(parse_qsl(parts.query))

        amazon_tag = os.getenv("AMAZON_TAG")
        flipkart_id = os.getenv("FLIPKART_AFFID")

        if "amazon." in host and amazon_tag:
            query["tag"] = amazon_tag
        elif "flipkart.com" in host and flipkart_id:
            query["affid"] = flipkart_id
        else:
            return url

        return urlunparse(parts._replace(query=urlencode(query)))
    except Exception:
        return url