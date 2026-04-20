import asyncio
import json
import os
import logging
from datetime import datetime
from playwright.async_api import async_playwright
import aiohttp

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "819720248")
DATA_FILE = "hotels.json"
CHECK_INTERVAL_HOURS = 6  # Check every 6 hours


async def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        await session.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"})
    logger.info(f"Telegram message sent: {message[:50]}...")


def load_hotels():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return []


def save_hotels(hotels):
    with open(DATA_FILE, "w") as f:
        json.dump(hotels, f, indent=2)


async def scrape_booking(page, hotel_name: str, checkin: str, checkout: str) -> float | None:
    """Scrape Booking.com for hotel price"""
    try:
        checkin_dt = datetime.strptime(checkin, "%d/%m/%Y")
        checkout_dt = datetime.strptime(checkout, "%d/%m/%Y")
        checkin_fmt = checkin_dt.strftime("%Y-%m-%d")
        checkout_fmt = checkout_dt.strftime("%Y-%m-%d")

        search_url = (
            f"https://www.booking.com/searchresults.html"
            f"?ss={hotel_name.replace(' ', '+')}"
            f"&checkin={checkin_fmt}&checkout={checkout_fmt}"
            f"&group_adults=2&no_rooms=1&selected_currency=USD"
        )

        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Try to find price on results page
        price_selectors = [
            '[data-testid="price-and-discounted-price"]',
            '.prco-valign-middle-helper',
            '[class*="price"]',
        ]

        for selector in price_selectors:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    text = await el.inner_text()
                    # Extract number from price string
                    import re
                    numbers = re.findall(r'[\d,]+', text.replace(',', ''))
                    for num in numbers:
                        price = float(num.replace(',', ''))
                        if 50 < price < 5000:  # Sanity check
                            logger.info(f"Booking.com price found: ${price}")
                            return price
            except:
                continue

        logger.warning("Booking.com: Could not extract price")
        return None
    except Exception as e:
        logger.error(f"Booking.com scrape error: {e}")
        return None


async def scrape_expedia(page, hotel_name: str, checkin: str, checkout: str) -> float | None:
    """Scrape Expedia for hotel price"""
    try:
        checkin_dt = datetime.strptime(checkin, "%d/%m/%Y")
        checkout_dt = datetime.strptime(checkout, "%d/%m/%Y")
        checkin_fmt = checkin_dt.strftime("%m/%d/%Y")
        checkout_fmt = checkout_dt.strftime("%m/%d/%Y")

        search_url = (
            f"https://www.expedia.com/Hotel-Search"
            f"?destination={hotel_name.replace(' ', '+')}"
            f"&startDate={checkin_fmt}&endDate={checkout_fmt}"
            f"&adults=2"
        )

        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)

        import re
        price_selectors = [
            '[data-stid="price-summary"]',
            '[class*="price-summary"]',
            '[class*="strike-through"]',
        ]

        for selector in price_selectors:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    text = await el.inner_text()
                    numbers = re.findall(r'\d+', text.replace(',', ''))
                    for num in numbers:
                        price = float(num)
                        if 50 < price < 5000:
                            logger.info(f"Expedia price found: ${price}")
                            return price
            except:
                continue

        logger.warning("Expedia: Could not extract price")
        return None
    except Exception as e:
        logger.error(f"Expedia scrape error: {e}")
        return None


async def scrape_agoda(page, hotel_name: str, checkin: str, checkout: str) -> float | None:
    """Scrape Agoda for hotel price"""
    try:
        checkin_dt = datetime.strptime(checkin, "%d/%m/%Y")
        checkout_dt = datetime.strptime(checkout, "%d/%m/%Y")

        search_url = (
            f"https://www.agoda.com/search"
            f"?city=&textToSearch={hotel_name.replace(' ', '+')}"
            f"&checkIn={checkin_dt.strftime('%Y-%m-%d')}"
            f"&checkOut={checkout_dt.strftime('%Y-%m-%d')}"
            f"&adults=2&rooms=1"
        )

        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)

        import re
        price_selectors = [
            '[data-selenium="display-price"]',
            '[class*="Price"]',
        ]

        for selector in price_selectors:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    text = await el.inner_text()
                    numbers = re.findall(r'\d+', text.replace(',', ''))
                    for num in numbers:
                        price = float(num)
                        if 50 < price < 5000:
                            logger.info(f"Agoda price found: ${price}")
                            return price
            except:
                continue

        logger.warning("Agoda: Could not extract price")
        return None
    except Exception as e:
        logger.error(f"Agoda scrape error: {e}")
        return None


async def check_hotel_prices(hotel: dict) -> dict:
    """Check prices for a hotel across all sites"""
    results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )

        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        name = hotel["name"]
        checkin = hotel["checkin"]
        checkout = hotel["checkout"]

        logger.info(f"Checking prices for: {name}")

        # Scrape each site
        booking_price = await scrape_booking(page, name, checkin, checkout)
        if booking_price:
            results["Booking.com"] = booking_price

        expedia_price = await scrape_expedia(page, name, checkin, checkout)
        if expedia_price:
            results["Expedia"] = expedia_price

        agoda_price = await scrape_agoda(page, name, checkin, checkout)
        if agoda_price:
            results["Agoda"] = agoda_price

        await browser.close()

    return results


async def run_check():
    hotels = load_hotels()
    if not hotels:
        logger.info("No hotels to track.")
        return

    for hotel in hotels:
        prices = await check_hotel_prices(hotel)

        if not prices:
            logger.warning(f"No prices found for {hotel['name']}")
            continue

        min_price = min(prices.values())
        min_site = min(prices, key=prices.get)
        paid = hotel["paid_price"]

        # Update price history
        if "price_history" not in hotel:
            hotel["price_history"] = []
        hotel["price_history"].append({
            "timestamp": datetime.now().isoformat(),
            "prices": prices,
            "min": min_price
        })

        logger.info(f"{hotel['name']}: Current min = ${min_price} on {min_site} | Paid = ${paid}")

        # Alert if price dropped
        if min_price < paid:
            savings = paid - min_price
            msg = (
                f"🏨 <b>Price Drop Alert!</b>\n\n"
                f"Hotel: {hotel['name']}\n"
                f"📅 Check-in: {hotel['checkin']}\n"
                f"💰 You paid: <b>${paid}</b>\n"
                f"🔥 New price: <b>${min_price}</b> on {min_site}\n"
                f"💵 You can save: <b>${savings:.0f}</b>!\n\n"
                f"All prices found:\n"
            )
            for site, price in prices.items():
                msg += f"  • {site}: ${price}\n"

            await send_telegram(msg)
        else:
            logger.info(f"No price drop. Best: ${min_price} vs paid ${paid}")

    save_hotels(hotels)


async def main():
    logger.info("🏨 Hotel Price Tracker started!")
    await send_telegram("🏨 Hotel Price Tracker is now running! I'll notify you when prices drop.")

    while True:
        try:
            await run_check()
        except Exception as e:
            logger.error(f"Error during check: {e}")

        logger.info(f"Sleeping {CHECK_INTERVAL_HOURS} hours until next check...")
        await asyncio.sleep(CHECK_INTERVAL_HOURS * 3600)


if __name__ == "__main__":
    asyncio.run(main())
