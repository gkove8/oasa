"""
Athens Bus Alert Bot — Netlify Scheduled Function
Runs every minute via Netlify cron. Checks OASA Telematics for bus arrivals
and sends a WhatsApp alert via Twilio when the bus is close.

State (cooldown) is stored in a Netlify Blobs key-value store so alerts
don't fire repeatedly for the same bus.
"""

import os
import json
import requests
from datetime import datetime, timedelta, timezone

# ── Config (set these as Netlify environment variables) ──────────────────────
LINE_NUMBER   = os.environ.get("LINE_NUMBER", "608")       # e.g. "608", "Β9"
STOP_ID       = os.environ.get("STOP_ID", "190004")        # OASA StopID
ALERT_MINUTES = int(os.environ.get("ALERT_MINUTES", "5"))  # Alert when ≤ N min away
COOLDOWN_MINS = int(os.environ.get("COOLDOWN_MINS", "15")) # Don't re-alert for N min

TWILIO_SID    = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_TOKEN  = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM   = os.environ["TWILIO_WHATSAPP_FROM"]         # e.g. "whatsapp:+14155238886"
ALERT_TO      = os.environ["ALERT_PHONE_NUMBER"]           # e.g. "whatsapp:+306912345678"

# Netlify Blobs (for cooldown state across invocations)
NETLIFY_TOKEN    = os.environ.get("NETLIFY_TOKEN", "")
NETLIFY_SITE_ID  = os.environ.get("NETLIFY_SITE_ID", "")
BLOB_STORE_NAME  = "bus-bot-state"
BLOB_KEY         = f"cooldown-{LINE_NUMBER}-{STOP_ID}"

OASA_BASE = "http://telematics.oasa.gr/api/"


# ── Netlify Blobs helpers ─────────────────────────────────────────────────────
def _blob_url(key: str) -> str:
    return f"https://api.netlify.com/api/v1/blobs/{NETLIFY_SITE_ID}/{BLOB_STORE_NAME}/{key}"


def get_blob(key: str) -> dict | None:
    try:
        resp = requests.get(
            _blob_url(key),
            headers={"Authorization": f"Bearer {NETLIFY_TOKEN}"},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def set_blob(key: str, value: dict):
    try:
        requests.put(
            _blob_url(key),
            headers={
                "Authorization": f"Bearer {NETLIFY_TOKEN}",
                "Content-Type": "application/json",
            },
            data=json.dumps(value),
            timeout=5,
        )
    except Exception:
        pass


# ── Cooldown logic ────────────────────────────────────────────────────────────
def is_in_cooldown() -> bool:
    state = get_blob(BLOB_KEY)
    if not state or "last_alert" not in state:
        return False
    last = datetime.fromisoformat(state["last_alert"])
    return datetime.now(timezone.utc) - last < timedelta(minutes=COOLDOWN_MINS)


def set_cooldown():
    set_blob(BLOB_KEY, {"last_alert": datetime.now(timezone.utc).isoformat()})


# ── OASA API ──────────────────────────────────────────────────────────────────
def get_line_code(line_number: str) -> str | None:
    resp = requests.get(f"{OASA_BASE}?act=webGetLines", timeout=10)
    resp.raise_for_status()
    for line in resp.json():
        if line.get("LineID", "").strip() == line_number.strip():
            return line["LineCode"]
    return None


def get_route_codes(line_code: str) -> list[str]:
    resp = requests.get(f"{OASA_BASE}?act=webGetRoutes&p1={line_code}", timeout=10)
    resp.raise_for_status()
    return [str(r["RouteCode"]) for r in resp.json()]


def get_arrivals(stop_id: str) -> list[dict]:
    resp = requests.get(f"{OASA_BASE}?act=getStopArrivals&p1={stop_id}", timeout=10)
    resp.raise_for_status()
    return resp.json() or []


# ── Twilio WhatsApp ───────────────────────────────────────────────────────────
def send_whatsapp(message: str):
    from twilio.rest import Client
    Client(TWILIO_SID, TWILIO_TOKEN).messages.create(
        body=message,
        from_=TWILIO_FROM,
        to=ALERT_TO,
    )


# ── Handler ───────────────────────────────────────────────────────────────────
def handler(event, context):
    print(f"[bus-bot] Checking line {LINE_NUMBER} at stop {STOP_ID}")

    if is_in_cooldown():
        print("[bus-bot] Cooldown active, skipping.")
        return {"statusCode": 200, "body": "cooldown"}

    line_code = get_line_code(LINE_NUMBER)
    if not line_code:
        print(f"[bus-bot] Could not resolve LineCode for '{LINE_NUMBER}'")
        return {"statusCode": 500, "body": "line not found"}

    route_codes = get_route_codes(line_code)
    arrivals = get_arrivals(STOP_ID)

    our_arrivals = [
        a for a in arrivals
        if str(a.get("route_code")) in route_codes
    ]

    if not our_arrivals:
        print(f"[bus-bot] Line {LINE_NUMBER} not in arrivals at stop {STOP_ID}")
        return {"statusCode": 200, "body": "no arrivals"}

    for arrival in our_arrivals:
        try:
            minutes = int(arrival["btime2"])
        except (KeyError, ValueError):
            continue

        print(f"[bus-bot] Line {LINE_NUMBER} arriving in {minutes} min(s)")

        if minutes <= ALERT_MINUTES:
            direction = arrival.get("route_descr", "")
            send_whatsapp(
                f"🚌 Bus {LINE_NUMBER} arriving in {minutes} minute(s)!\n"
                f"Stop: {STOP_ID}\n"
                f"Direction: {direction}"
            )
            set_cooldown()
            print(f"[bus-bot] Alert sent! Bus in {minutes} min(s).")
            return {"statusCode": 200, "body": f"alert sent: {minutes} min"}

    print(f"[bus-bot] Bus found but not close enough yet.")
    return {"statusCode": 200, "body": "not close enough"}
