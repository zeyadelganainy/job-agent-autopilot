#!/usr/bin/env python3
"""Long-running Telegram bot — the interactive half of the loop.

Commands:
  /scan          run a fresh scan and show the digest
  /list          show jobs waiting on your decision
  /pick a b c    generate resume + cover letter for those job ids, sent back as files
  /skip a b c    dismiss those job ids

Run:  python bot.py
"""
import asyncio
import html
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from jobagent.config import env, load_config
from jobagent.pipeline import (
    format_digest,
    pending,
    pick_and_generate,
    picks_to_ids,
    scan,
)
from jobagent.store import Store

CFG = load_config()


def _authorized(update: Update) -> bool:
    """Only respond to your own chat id."""
    allowed = env("TELEGRAM_CHAT_ID")
    return allowed is None or str(update.effective_chat.id) == str(allowed)


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Job agent ready.\n/scan – find jobs\n/list – pending\n"
        "/pick 1 2 3 – generate docs for those numbers\n/skip 1 2 – dismiss"
    )


async def cmd_scan(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text("Scanning…")
    try:
        await asyncio.to_thread(scan, CFG)
    except Exception as e:
        await update.message.reply_text(f"Scan failed — {e}")
        return
    # Show the full pending list so its 1..N numbering matches /pick and /skip.
    await update.message.reply_text(format_digest(pending(CFG)), parse_mode="HTML")


async def cmd_list(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(format_digest(pending(CFG)), parse_mode="HTML")


async def cmd_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    ids, bad = picks_to_ids(context.args, CFG)
    if bad:
        await update.message.reply_text(f"Ignoring invalid: {' '.join(bad)}")
    if not ids:
        n = len(pending(CFG))
        await update.message.reply_text(
            f"Usage: /pick 1 2 3 — numbers from the list (1–{n})." if n
            else "Nothing to pick yet. Run /scan first.")
        return
    await update.message.reply_text(f"Generating docs for {len(ids)} job(s)…")

    def _work():
        return list(pick_and_generate(ids, CFG))

    try:
        results = await asyncio.to_thread(_work)
    except Exception as e:
        await update.message.reply_text(f"Generation failed — {e}")
        return
    for row, paths in results:
        if not paths:
            await update.message.reply_text(f"Skipped {row.get('title', '?')} (not found)")
            continue
        msg = f"<b>{html.escape(str(row['title']))}</b> — {html.escape(str(row['company']))}"
        if row.get("url"):
            msg += f'\n🔗 <a href="{html.escape(str(row["url"]))}">Apply / view posting</a>'
        await update.message.reply_text(msg, parse_mode="HTML")
        for p in paths:
            with open(p, "rb") as f:
                await update.message.reply_document(f, filename=os.path.basename(p))


async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    ids, bad = picks_to_ids(context.args, CFG)
    store = Store(CFG["paths"]["db"])
    for jid in ids:
        store.set_status(jid, "skipped")
    note = f" (ignored: {' '.join(bad)})" if bad else ""
    await update.message.reply_text(f"Skipped {len(ids)} job(s).{note}")


def main():
    token = env("TELEGRAM_BOT_TOKEN", required=True)
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("pick", cmd_pick))
    app.add_handler(CommandHandler("skip", cmd_skip))
    print("Bot running. Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
