#!/usr/bin/env python3
"""Send the daily PDF to Telegram and/or email.

    .venv/Scripts/python.exe backtest/deliver.py                     # newest report
    .venv/Scripts/python.exe backtest/deliver.py --date 2026-09-01
    .venv/Scripts/python.exe backtest/deliver.py --test              # prove it works

Credentials come from paper/delivery.json, which is GIT-IGNORED and must stay so:
a Telegram bot token lets anyone post as the bot, and an email app password is a
password. Nothing here belongs in the repository, and this repository is public.

Create paper/delivery.json from paper/delivery.example.json and fill in whichever
channel you want. Both may be enabled at once; each is attempted independently, so
a broken mail server does not stop the Telegram copy from arriving.

    {
      "telegram": {"enabled": true, "bot_token": "123:ABC", "chat_id": "12345"},
      "email": {"enabled": false, "smtp_host": "smtp.gmail.com", "smtp_port": 587,
                "username": "you@example.com", "password": "app-password",
                "from": "you@example.com", "to": ["you@example.com"]}
    }

TELEGRAM SETUP, once: message @BotFather, /newbot, copy the token. Then message
your new bot once (a bot cannot open a conversation with you), and run this with
--chat-id to have it read the id back to you.

EMAIL SETUP: for Gmail this needs an APP PASSWORD, not the account password, and
the account needs 2FA switched on for app passwords to exist at all.

Exit status is 0 only if every ENABLED channel delivered. The 07:00 job checks it,
because a report that silently fails to send is worse than one that never existed:
you would sit waiting for a list that was never coming.
"""

from __future__ import annotations

import argparse
import json
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

TIMEOUT = 60


def send_telegram(cfg: dict, pdf: Path, caption: str) -> tuple[bool, str]:
    token, chat = cfg.get("bot_token", ""), str(cfg.get("chat_id", ""))
    if not token or not chat:
        return False, "bot_token or chat_id missing"
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        with pdf.open("rb") as fh:
            r = requests.post(url, data={"chat_id": chat, "caption": caption[:1024]},
                              files={"document": (pdf.name, fh, "application/pdf")},
                              timeout=TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        return False, f"request failed: {exc}"
    if r.status_code != 200:
        # Telegram puts the real reason in the body; the status alone is useless.
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    return True, "sent"


def send_email(cfg: dict, pdf: Path, subject: str, body: str) -> tuple[bool, str]:
    host, port = cfg.get("smtp_host", ""), int(cfg.get("smtp_port", 587))
    user, pw = cfg.get("username", ""), cfg.get("password", "")
    sender = cfg.get("from") or user
    to = cfg.get("to") or []
    if isinstance(to, str):
        to = [to]
    if not (host and sender and to):
        return False, "smtp_host, from or to missing"

    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, ", ".join(to)
    msg.set_content(body)
    msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf",
                       filename=pdf.name)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=TIMEOUT) as s:
                if user:
                    s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=TIMEOUT) as s:
                s.starttls()
                if user:
                    s.login(user, pw)
                s.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        return False, f"smtp failed: {exc}"
    return True, "sent"


def show_chat_id(token: str) -> int:
    """Read the chat id back from whatever has messaged the bot."""
    if not token:
        print("no bot_token configured")
        return 1
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"HTTP {r.status_code}: {r.text[:300]}")
        return 1
    res = r.json().get("result", [])
    if not res:
        print("No updates. Send your bot a message first - a bot cannot start the\n"
              "conversation - then run this again.")
        return 1
    seen = {}
    for u in res:
        c = (u.get("message") or u.get("channel_post") or {}).get("chat") or {}
        if c.get("id"):
            seen[c["id"]] = c.get("title") or c.get("username") or c.get("first_name", "")
    for cid, who in seen.items():
        print(f"  chat_id {cid}   {who}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=None)
    ap.add_argument("--reports", default="reports")
    ap.add_argument("--scans", default="scans")
    ap.add_argument("--config", default="paper/delivery.json")
    ap.add_argument("--chat-id", action="store_true",
                    help="print the Telegram chat id(s) that have messaged the bot")
    ap.add_argument("--test", action="store_true",
                    help="send the newest report now, whatever its date")
    args = ap.parse_args()

    cp = Path(args.config)
    if not cp.exists():
        print(f"no {cp}. Copy paper/delivery.example.json to it and fill in a channel.")
        return 1
    cfg = json.loads(cp.read_text(encoding="utf-8"))

    if args.chat_id:
        return show_chat_id(cfg.get("telegram", {}).get("bot_token", ""))

    rd = Path(args.reports)
    if args.date:
        pdf = rd / f"supertrend_{args.date}.pdf"
    else:
        found = sorted(rd.glob("supertrend_*.pdf"))
        if not found:
            print(f"no reports in {rd}")
            return 1
        pdf = found[-1]
    if not pdf.exists():
        print(f"no such report: {pdf}")
        return 1

    stamp = pdf.stem.replace("supertrend_", "")
    # A one-line summary in the message body itself, so the counts are visible
    # on a phone without opening the attachment.
    head = f"SuperTrend Breakout - {stamp}"
    detail = ""
    sc = Path(args.scans) / f"{stamp}.csv"
    if sc.exists():
        try:
            import pandas as pd
            d = pd.read_csv(sc)
            liv = d[~d.stale.astype(bool)] if "stale" in d else d
            detail = (f"\n{int((liv.state == 'DISARMED').sum())} to exit, "
                      f"{int((liv.state == 'NEW ARM').sum())} newly armed, "
                      f"{int((liv.state == 'ARMED').sum())} armed and waiting.")
        except Exception:  # noqa: BLE001
            detail = ""
    caption = head + detail

    results, any_enabled = [], False
    tg = cfg.get("telegram", {})
    if tg.get("enabled"):
        any_enabled = True
        ok, why = send_telegram(tg, pdf, caption)
        results.append(("telegram", ok, why))
    em = cfg.get("email", {})
    if em.get("enabled"):
        any_enabled = True
        ok, why = send_email(em, pdf, head, caption + f"\n\nAttached: {pdf.name}")
        results.append(("email", ok, why))

    if not any_enabled:
        print("no channel enabled in " + str(cp))
        return 1

    for name, ok, why in results:
        print(f"  {name:9s} {'OK' if ok else 'FAILED'}  {why}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
