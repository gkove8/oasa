# Athens Bus Alert Bot — Netlify Edition 🚌

Runs as a **Netlify scheduled function** every minute. No always-on server needed.

---

## Project structure

```
bus-bot-netlify/
├── netlify.toml                         # Cron schedule + build config
├── public/
│   └── index.html                       # Minimal publish target (required)
└── netlify/
    └── functions/
        ├── bus_check.py                 # The bot logic
        └── requirements.txt             # Python dependencies
```

---

## Step 1 — Find your LINE_NUMBER and STOP_ID

Use the `find_ids.py` script from the original bot package:

```bash
pip install requests
python find_ids.py
```

---

## Step 2 — Set up Twilio WhatsApp sandbox

1. Sign up at [twilio.com](https://twilio.com)
2. Go to **Messaging > Try it out > Send a WhatsApp message**
3. Send the join code from your WhatsApp to activate the sandbox
4. Note: Account SID, Auth Token, and the sandbox number (`whatsapp:+14155238886`)

---

## Step 3 — Get your Netlify token and site ID (for cooldown state)

The bot uses **Netlify Blobs** to remember the last alert time across invocations.

1. Go to [app.netlify.com/user/applications](https://app.netlify.com/user/applications)
2. Create a **Personal access token** — copy it
3. Your Site ID is in **Site configuration > General > Site details**

---

## Step 4 — Set environment variables in Netlify

Go to **Site configuration > Environment variables** and add:

| Variable | Value |
|---|---|
| `LINE_NUMBER` | Your bus line e.g. `608` |
| `STOP_ID` | Your stop ID e.g. `190004` |
| `ALERT_MINUTES` | `5` |
| `COOLDOWN_MINS` | `15` |
| `TWILIO_ACCOUNT_SID` | From Twilio console |
| `TWILIO_AUTH_TOKEN` | From Twilio console |
| `TWILIO_WHATSAPP_FROM` | `whatsapp:+14155238886` |
| `ALERT_PHONE_NUMBER` | `whatsapp:+306912345678` |
| `NETLIFY_TOKEN` | Your personal access token |
| `NETLIFY_SITE_ID` | Your site ID |

---

## Step 5 — Deploy

Push to GitHub and connect to Netlify, or drag-drop the folder into Netlify's deploy UI.

The `bus_check` function will fire automatically every minute once deployed.

---

## Monitoring

- Check **Functions > bus_check > Logs** in the Netlify dashboard to see each invocation
- Logs print the arrival status or reason for skipping

---

## Notes

- Netlify scheduled functions require a **paid plan** (Starter or above) for sub-hourly cron schedules. The free tier supports cron no more frequently than once per hour. If you're on free tier, set `schedule = "*/5 * * * *"` (every 5 min) or consider Render instead.
- Netlify Blobs is available on all plans including free.
- The OASA Telematics API is public and requires no authentication key.
