"""
Athens Bus Alert Bot — Netlify Scheduled Function
Runs every minute via Netlify cron. Checks OASA Telematics for bus arrivals
and sends an email alert when the bus is close.

State (cooldown) is stored in Netlify Blobs so alerts don't fire repeatedly.
"""

import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

# ── Config (set these as Netlify environment variables) ──────────────────────
LINE_NUMBER   = os.environ.get("LINE_NUMBER", "608")       # e.g. "608", "Β9"
STOP_ID       = os.environ.get("STOP_ID", "190004")        # OASA StopID
ALERT_MINUTES = int(os.environ.get("ALERT_MINUTES", "5"))  # Alert when <= N min away
COOLDOWN_MINS = int(os.environ.get("COOLDOWN_MINS", "15")) # Don't re-alert for N min

GMAIL_ADDRESS  = os.environ["GMAIL_ADDRESS"]       # your Gmail e.g. costa@gmail.com
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASSWORD"]  # Google App Password
ALERT_EMAIL    = os.environ["ALERT_EMAIL"]         # where to send alerts

# Netlify Blobs (for cooldown state across invocations)
NETLIFY_TOKEN   = os.environ.get("NETLIFY_TOKEN", "")
NETLIFY_SITE_ID = os.environ.get("NETLIFY_SITE_ID", "")
BLOB_STORE_NAME = "bus-bot-state"
BLOB_KEY        = f"cooldown-{LINE_NUMBER}-{STOP_ID}"

OASA_BASE = "http://telematics.oasa.gr/api/"


# ── OASA API — all calls are POST requests with params in the URL ─────────────
def oasa_post(act, p1=None, p2=None):
    url = f"{OASA_BASE}?act={act}"
    if p1:
        url += f"&p1={p1}"
    if p2:
        url += f"&p2={p2}"
    resp = requests.post(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_line_code(line_number):
    lines = oasa_post("webGetLines")
    for line in lines:
        if line.get("LineID", "").strip() == line_number.strip():
            return line["LineCode"]
    return None


def get_route_codes(line_code):
    routes = oasa_post("webGetRoutes", p1=line_code)
    return [str(r["RouteCode"]) for r in routes]


def get_arrivals(stop_id):
    result = oasa_post("getStopArrivals", p1=stop_id)
    return result or []


# ── Netlify Blobs helpers ─────────────────────────────────────────────────────
def _blob_url(key):
    return f"https://api.netlify.com/api/v1/blobs/{NETLIFY_SITE_ID}/{BLOB_STORE_NAME}/{key}"


def get_blob(key):
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


def set_blob(key, value):
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
def is_in_cooldown():
    state = get_blob(BLOB_KEY)
    if not state or "last_alert" not in state:
        return False
    last = datetime.fromisoformat(state["last_alert"])
    return datetime.now(timezone.utc) - last < timedelta(minutes=COOLDOWN_MINS)


def set_cooldown():
    set_blob(BLOB_KEY, {"last_alert": datetime.now(timezone.utc).isoformat()})


# ── Gmail SMTP ────────────────────────────────────────────────────────────────
def send_email(message):
    msg = MIMEText(message)
    msg["Subject"] = f"Bus {LINE_NUMBER} arriving soon!"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = ALERT_EMAIL
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
        smtp.send_message(msg)


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
            send_email(
                f"Bus {LINE_NUMBER} arriving in {minutes} minute(s)!\n"
                f"Stop: {STOP_ID}\n"
                f"Direction: {direction}"
            )
            set_cooldown()
            print(f"[bus-bot] Alert sent! Bus in {minutes} min(s).")
            return {"statusCode": 200, "body": f"alert sent: {minutes} min"}

    print(f"[bus-bot] Bus found but not close enough yet.")
    return {"statusCode": 200, "body": "not close enough"}
