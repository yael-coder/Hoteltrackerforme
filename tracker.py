import asyncio
import json
import os
import re
import logging
from datetime import datetime
from playwright.async_api import async_playwright
import aiohttp

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "819720248")
DATA_FILE = "hotels.json"
CHECK_INTERVAL_HOURS = 6


async def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_TOKEN not set – skipping message")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(url, json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            data = await resp.json()
            if not data.get("ok"):
                logger.error(f"Telegram API error: {data}")
                return False
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False
    logger.info(f"Telegram sent: {message[:70]}...")
    return True


async def get_updates(offset: int = 0) -> list:
    if not TELEGRAM_TOKEN:
        return []
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.get(url, params={"offset": offset, "timeout": 10}, timeout=aiohttp.ClientTimeout(total=15))
            data = await resp.json()
            return data.get("result", [])
    except Exception as e:
        logger.debug(f"getUpdates failed: {e}")
        return []


def load_hotels() -> list:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return []


def save_hotels(hotels: list):
    with open(DATA_FILE, "w") as f:
        json.dump(hotels, f, indent=2)


def extract_price(text: str) -> float | None:
    cleaned = re.sub(r'[,$€£¥\s]', '', text)
    for m in re.finditer(r'\d{2,5}(?:\.\d{1,2})?', cleaned):
        try:
            price = float(m.group())
            if 30 < price < 15000:
                return price
        except ValueError:
            continue
    return None


async def _make_page(playwright):
    browser = await playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
    )
    ctx = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        locale="en-US",
    )
    page = await ctx.new_page()
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return browser, page


async def scrape_booking(page, name, checkin, checkout):
    try:
        ci = datetime.strptime(checkin, "%d/%m/%Y").strftime("%Y-%m-%d")
        co = datetime.strptime(checkout, "%d/%m/%Y").strftime("%Y-%m-%d")
        await page.goto(f"https://www.booking.com/searchresults.html?ss={name.replace(' ', '+')}&checkin={ci}&checkout={co}&group_adults=2&no_rooms=1&selected_currency=USD", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3000)
        for sel in ['[data-testid="price-and-discounted-price"]', '.prco-valign-middle-helper', '.bui-price-display__value', '[class*="price"]']:
            for el in await page.query_selector_all(sel):
                price = extract_price(await el.inner_text())
                if price:
                    logger.info(f"Booking.com → ${price}")
                    return price
    except Exception as e:
        logger.error(f"Booking.com error: {e}")
    return None


async def scrape_expedia(page, name, checkin, checkout):
    try:
        ci = datetime.strptime(checkin, "%d/%m/%Y").strftime("%m/%d/%Y")
        co = datetime.strptime(checkout, "%d/%m/%Y").strftime("%m/%d/%Y")
        await page.goto(f"https://www.expedia.com/Hotel-Search?destination={name.replace(' ', '+')}&startDate={ci}&endDate={co}&adults=2", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(4000)
        for sel in ['[data-stid="price-summary"]', '[class*="uitk-type-500"]', '[class*="price-summary"]', '[class*="price"]']:
            for el in await page.query_selector_all(sel):
                price = extract_price(await el.inner_text())
                if price:
                    logger.info(f"Expedia → ${price}")
                    return price
    except Exception as e:
        logger.error(f"Expedia error: {e}")
    return None


async def scrape_google_hotels(page, name, checkin, checkout):
    try:
        ci = datetime.strptime(checkin, "%d/%m/%Y").strftime("%Y-%m-%d")
        co = datetime.strptime(checkout, "%d/%m/%Y").strftime("%Y-%m-%d")
        await page.goto(f"https://www.google.com/travel/hotels?q={name.replace(' ', '+')}&checkin={ci}&checkout={co}&adults=2", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(5000)
        for sel in ['[class*="kR1eme"]', '[class*="prxnNd"]', '[data-item-name="total-price"]', 'span[aria-label*="$"]', '[class*="price"]']:
            for el in await page.query_selector_all(sel):
                price = extract_price(await el.inner_text())
                if price:
                    logger.info(f"Google Hotels → ${price}")
                    return price
    except Exception as e:
        logger.error(f"Google Hotels error: {e}")
    return None


async def check_hotel_prices(hotel):
    results = {}
    async with async_playwright() as p:
        browser, page = await _make_page(p)
        try:
            for fn, label in [(scrape_booking, "Booking.com"), (scrape_expedia, "Expedia"), (scrape_google_hotels, "Google Hotels")]:
                price = await fn(page, hotel["name"], hotel["checkin"], hotel["checkout"])
                if price:
                    results[label] = price
                await page.wait_for_timeout(1500)
        finally:
            await browser.close()
    return results


async def run_check():
    hotels = load_hotels()
    if not hotels:
        return
    for hotel in hotels:
        prices = await check_hotel_prices(hotel)
        hotel.setdefault("price_history", []).append({
            "timestamp": datetime.now().isoformat(),
            "prices": prices,
        })
        if not prices:
            continue
        min_price = min(prices.values())
        min_site = min(prices, key=prices.get)
        paid = hotel["paid_price"]
        if min_price < paid:
            savings = paid - min_price
            pct = (savings / paid) * 100
            nights = (datetime.strptime(hotel["checkout"], "%d/%m/%Y") - datetime.strptime(hotel["checkin"], "%d/%m/%Y")).days
            price_lines = "\n".join(f"  • {s}: ${p:,.0f}" for s, p in sorted(prices.items(), key=lambda x: x[1]))
            await send_telegram(
                f"🏨 <b>Price Drop Alert!</b>\n\n<b>{hotel['name']}</b>\n"
                f"📅 {hotel['checkin']} → {hotel['checkout']} ({nights} night{'s' if nights != 1 else ''})\n\n"
                f"💳 You paid:  <b>${paid:,.0f}</b>\n"
                f"🔥 Now from: <b>${min_price:,.0f}</b> on {min_site}\n"
                f"💰 Saving:   <b>${savings:,.0f} ({pct:.0f}%)</b>\n\n"
                f"<b>All prices:</b>\n{price_lines}"
            )
    save_hotels(hotels)


async def price_check_loop():
    while True:
        try:
            await run_check()
        except Exception as e:
            logger.error(f"Check error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_HOURS * 3600)


def _parse_add_command(text):
    parts = [p.strip() for p in text[len("/add"):].strip().split("|")]
    if len(parts) != 4:
        return None
    name, checkin, checkout, paid_str = parts
    try:
        datetime.strptime(checkin, "%d/%m/%Y")
        datetime.strptime(checkout, "%d/%m/%Y")
        paid = float(paid_str.replace("$", "").replace(",", ""))
    except ValueError:
        return None
    return {"name": name, "checkin": checkin, "checkout": checkout, "paid_price": paid, "price_history": []}


async def handle_commands():
    offset = 0
    while True:
        for update in await get_updates(offset):
            offset = update["update_id"] + 1
            text = update.get("message", {}).get("text", "").strip()
            cmd = text.split()[0].lower() if text else ""

            if cmd == "/check":
                await send_telegram("🔍 Running price check now…")
                try:
                    await run_check()
                    await send_telegram("✅ Done.")
                except Exception as e:
                    await send_telegram(f"❌ Failed: {e}")

            elif cmd == "/prices":
                hotels = load_hotels()
                if not hotels:
                    await send_telegram("No hotels tracked yet.")
                else:
                    msg = "<b>Latest Price Data:</b>\n\n"
                    for h in hotels:
                        history = h.get("price_history", [])
                        nights = (datetime.strptime(h["checkout"], "%d/%m/%Y") - datetime.strptime(h["checkin"], "%d/%m/%Y")).days
                        msg += f"🏨 <b>{h['name']}</b>\n"
                        msg += f"📅 {h['checkin']} → {h['checkout']} ({nights} night{'s' if nights != 1 else ''})\n"
                        msg += f"💳 Paid: <b>${h['paid_price']:,.0f}</b>\n"
                        last_with_prices = next((e for e in reversed(history) if e.get("prices")), None)
                        if last_with_prices:
                            prices = last_with_prices["prices"]
                            ts = last_with_prices["timestamp"][:16].replace("T", " ")
                            min_price = min(prices.values())
                            min_site = min(prices, key=prices.get)
                            savings = h["paid_price"] - min_price
                            msg += f"🕐 Last check: {ts}\n"
                            msg += f"🔥 Best now:  <b>${min_price:,.0f}</b> on {min_site}\n"
                            if savings > 0:
                                pct = (savings / h["paid_price"]) * 100
                                msg += f"💰 You'd save: <b>${savings:,.0f} ({pct:.0f}%)</b>\n"
                            else:
                                msg += f"📈 No drop yet (${abs(savings):,.0f} above paid)\n"
                            for site, price in sorted(prices.items(), key=lambda x: x[1]):
                                msg += f"  • {site}: ${price:,.0f}\n"
                        elif history:
                            msg += "⚠️ Last check found no prices\n"
                        else:
                            msg += "⏳ No checks run yet\n"
                        msg += "\n"
                    await send_telegram(msg.strip())

            elif cmd == "/list":
                hotels = load_hotels()
                if not hotels:
                    await send_telegram("No hotels tracked yet.")
                else:
                    await send_telegram("<b>Tracked Hotels:</b>\n\n" + "\n\n".join(
                        f"• <b>{h['name']}</b>\n  📅 {h['checkin']} → {h['checkout']}\n  💳 ${h['paid_price']:,.0f}"
                        for h in hotels
                    ))

            elif cmd == "/status":
                hotels = load_hotels()
                total_checks = sum(len(h.get("price_history", [])) for h in hotels)
                await send_telegram(
                    f"✅ <b>Tracker is running</b>\n"
                    f"📋 Hotels tracked: {len(hotels)}\n"
                    f"🔍 Total checks done: {total_checks}\n"
                    f"⏰ Check interval: every {CHECK_INTERVAL_HOURS}h\n"
                    f"🕐 Server time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                )

            elif cmd == "/add":
                hotel = _parse_add_command(text)
                if not hotel:
                    await send_telegram("❌ Use: <code>/add Name | DD/MM/YYYY | DD/MM/YYYY | price</code>")
                else:
                    hotels = load_hotels()
                    hotels.append(hotel)
                    save_hotels(hotels)
                    await send_telegram(f"✅ Added: <b>{hotel['name']}</b>")

            elif cmd == "/help":
                await send_telegram(
                    "<b>Commands:</b>\n\n"
                    "/prices – latest scraped prices for all hotels\n"
                    "/check – run a price check right now\n"
                    "/list – show tracked hotels\n"
                    "/status – tracker health + check count\n"
                    "/add – add a hotel\n"
                    "  <code>/add Name | DD/MM/YYYY | DD/MM/YYYY | price</code>"
                )

        await asyncio.sleep(5)


async def main():
    hotels = load_hotels()
    await send_telegram(
        f"🏨 <b>Hotel Price Tracker started!</b>\n\n"
        f"📋 Tracking {len(hotels)} hotel{'s' if len(hotels) != 1 else ''}\n"
        f"⏰ Checks every {CHECK_INTERVAL_HOURS}h\n\n"
        f"Commands: /prices /check /list /status /add /help"
    )
    await asyncio.gather(handle_commands(), price_check_loop())


if __name__ == "__main__":
    asyncio.run(main())
