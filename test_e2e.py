"""
End-to-end scraper tests — require a real Chromium browser (Playwright).
Run with:  pytest test_e2e.py -v
These are slow (~1-2 min) and depend on live sites, so they run on a
nightly schedule in CI rather than on every push.
"""
import pytest
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

from tracker import scrape_google_hotels, scrape_kayak, scrape_booking, _make_page

# Use a well-known hotel and dates ~6 months out so results are always available
HOTEL_NAME = "Marriott Times Square New York"
CHECKIN = (datetime.now() + timedelta(days=180)).strftime("%d/%m/%Y")
CHECKOUT = (datetime.now() + timedelta(days=181)).strftime("%d/%m/%Y")


@pytest.fixture
async def browser_page():
    async with async_playwright() as p:
        browser, page = await _make_page(p)
        yield page
        await browser.close()


async def test_google_hotels_returns_price(browser_page):
    price = await scrape_google_hotels(browser_page, HOTEL_NAME, CHECKIN, CHECKOUT)
    assert price is not None, "Google Hotels returned no price — selector may have changed"
    assert 40 < price < 15000, f"Price ${price} is outside the expected range"


async def test_kayak_returns_price(browser_page):
    price = await scrape_kayak(browser_page, HOTEL_NAME, CHECKIN, CHECKOUT)
    assert price is not None, "Kayak returned no price — selector may have changed"
    assert 40 < price < 15000, f"Price ${price} is outside the expected range"


async def test_booking_returns_price_or_blocked(browser_page):
    # Booking.com often triggers Cloudflare — we accept None but not an exception
    price = await scrape_booking(browser_page, HOTEL_NAME, CHECKIN, CHECKOUT)
    if price is not None:
        assert 40 < price < 15000, f"Price ${price} is outside the expected range"


async def test_at_least_one_source_returns_price():
    """Smoke test: at least one source must return a price."""
    async with async_playwright() as p:
        browser, page = await _make_page(p)
        try:
            google = await scrape_google_hotels(page, HOTEL_NAME, CHECKIN, CHECKOUT)
            kayak = await scrape_kayak(page, HOTEL_NAME, CHECKIN, CHECKOUT)
            booking = await scrape_booking(page, HOTEL_NAME, CHECKIN, CHECKOUT)
        finally:
            await browser.close()

    prices = [p for p in [google, kayak, booking] if p is not None]
    assert prices, (
        "All three scrapers returned None — the sites may have changed "
        "their HTML or are blocking the scraper entirely."
    )
