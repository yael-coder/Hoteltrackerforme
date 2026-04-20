# 🏨 Hotel Price Tracker

Automatically tracks hotel prices across Booking.com, Expedia, and Agoda and sends you a Telegram alert when prices drop!

---

## Setup Instructions

### Step 1 – Add your Telegram credentials
Open `tracker.py` and replace:
- `YOUR_BOT_TOKEN` with your Telegram Bot Token
- The Chat ID is already set to `819720248`

Or set them as environment variables (recommended for Render):
- `TELEGRAM_TOKEN`
- `CHAT_ID`

---

### Step 2 – Add more hotels
Edit `hotels.json` to add more hotels:

```json
[
  {
    "name": "Fairfield Inn & Suites by Marriott South Kingstown Newport Area",
    "checkin": "10/09/2026",
    "checkout": "11/09/2026",
    "paid_price": 281,
    "price_history": []
  },
  {
    "name": "Another Hotel Name",
    "checkin": "15/10/2026",
    "checkout": "16/10/2026",
    "paid_price": 150,
    "price_history": []
  }
]
```

---

### Step 3 – Deploy to Render (runs 24/7 for free)

1. Create a free account at **render.com**
2. Click **New → Background Worker**
3. Connect your GitHub repo (upload these files first)
4. Set environment variables:
   - `TELEGRAM_TOKEN` = your bot token
   - `CHAT_ID` = `819720248`
5. Click **Deploy**!

That's it! The tracker will check prices every 6 hours and message you on Telegram when it finds a lower price. 🎉

---

## How it works
- Checks prices every **6 hours**
- Scrapes **Booking.com**, **Expedia**, and **Agoda**
- Sends a Telegram message if ANY site has a lower price than what you paid
- Tells you exactly how much you can save and on which site
