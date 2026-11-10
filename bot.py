"""Telegram price-compare bot.
Paste product link (or type product name) -> get cheapest stores."""
import asyncio
import html
import logging
import re

from dotenv import load_dotenv

load_dotenv()

import os  # noqa: E402

from telegram import Update  # noqa: E402
from telegram.constants import ParseMode  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from links import affiliate  # noqa: E402
from product import get_product_query  # noqa: E402
from search import search_prices  # noqa: E402

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("pricebot")

URL_RE = re.compile(r"https?://\S+")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Pratik Gharge Here Paste any product link (Amazon, Flipkart, etc.) "
        "or type a product name. I will find the best price."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return

    status = await update.message.reply_text("🔎 Checking prices...")

    try:
        match = URL_RE.search(text)
        if match:
            query, _final = await asyncio.to_thread(get_product_query, match.group())
        else:
            query = text

        log.info("QUERY: %s", query)
        results = await asyncio.to_thread(search_prices, query)
        log.info("RESULTS: %s", [(r["store"], r["price_text"], r["title"][:50]) for r in results])
    except ValueError as e:
        await status.edit_text(f" {e}\nTry typing the product name instead.")
        return
    except Exception:
        log.exception("lookup failed")
        await status.edit_text(" Something went wrong. Try again later.")
        return

    if not results:
        await status.edit_text(
            f"No prices found for:\n{query}\nTry a shorter product name."
        )
        return

    lines = [f"🛒 <b>{html.escape(query)}</b>\n"]
    for i, r in enumerate(results):
        link = html.escape(affiliate(r["link"]), quote=True)
        store = html.escape(r["store"])
        price = html.escape(r["price_text"])
        badge = "🏆 Best deal: " if i == 0 else f"{i + 1}. "
        name = html.escape(r["title"][:60])
        lines.append(f'{badge}<a href="{link}">{store}</a> — <b>{price}</b>\n    <i>{name}</i>')

    lines.append("\n<i>Prices can change. Check final price on store.</i>")

    await status.edit_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN missing in .env")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    base_url = os.getenv("RENDER_EXTERNAL_URL")  # Render sets this automatically
    port = int(os.getenv("PORT", "10000"))  # Render sets this too

    if base_url:
        log.info("Webhook mode")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=f"{base_url}/{token}",
        )
    else:
        log.info("Polling mode (local)")
        app.run_polling()


if __name__ == "__main__":
    main()