import json
import os
import tempfile
import pytest
from tracker import extract_prices_from_text, _parse_add_command, load_hotels, save_hotels, DATA_FILE


# ── extract_prices_from_text ──────────────────────────────────────────────────

def test_extract_plain_number():
    assert 250 in extract_prices_from_text("Total: 250")

def test_extract_dollar_sign():
    assert 199 in extract_prices_from_text("Price: $199")

def test_extract_comma_number():
    assert 1200 in extract_prices_from_text("$1,200 per night")

def test_extract_ignores_too_low():
    # below the 40-floor
    prices = extract_prices_from_text("$5 coffee, $30 lunch")
    assert not any(p <= 40 for p in prices)

def test_extract_ignores_too_high():
    # above the 15000 ceiling
    prices = extract_prices_from_text("salary 50000 a year")
    assert not any(p >= 15000 for p in prices)

def test_extract_multiple():
    prices = extract_prices_from_text("Booking.com $220 Kayak $215")
    assert 220 in prices
    assert 215 in prices

def test_extract_empty():
    assert extract_prices_from_text("no numbers here") == []


# ── _parse_add_command ────────────────────────────────────────────────────────

def test_parse_add_valid():
    hotel = _parse_add_command("/add Marriott NYC | 15/06/2026 | 17/06/2026 | 350")
    assert hotel is not None
    assert hotel["name"] == "Marriott NYC"
    assert hotel["checkin"] == "15/06/2026"
    assert hotel["checkout"] == "17/06/2026"
    assert hotel["paid_price"] == 350.0
    assert hotel["price_history"] == []

def test_parse_add_dollar_sign_in_price():
    hotel = _parse_add_command("/add Beach Hotel | 01/07/2026 | 03/07/2026 | $450")
    assert hotel["paid_price"] == 450.0

def test_parse_add_comma_in_price():
    hotel = _parse_add_command("/add Grand Resort | 10/08/2026 | 12/08/2026 | 1,200")
    assert hotel["paid_price"] == 1200.0

def test_parse_add_missing_parts():
    assert _parse_add_command("/add Only One Part") is None

def test_parse_add_bad_date():
    assert _parse_add_command("/add Hotel | 2026-06-15 | 2026-06-17 | 200") is None

def test_parse_add_bad_price():
    assert _parse_add_command("/add Hotel | 15/06/2026 | 17/06/2026 | free") is None


# ── load_hotels / save_hotels ─────────────────────────────────────────────────

def test_save_and_load(tmp_path, monkeypatch):
    data_file = str(tmp_path / "hotels.json")
    monkeypatch.setattr("tracker.DATA_FILE", data_file)

    hotels = [
        {"name": "Test Inn", "checkin": "01/09/2026", "checkout": "02/09/2026",
         "paid_price": 100, "price_history": []}
    ]
    save_hotels(hotels)
    loaded = load_hotels()
    assert loaded == hotels

def test_load_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("tracker.DATA_FILE", str(tmp_path / "nonexistent.json"))
    assert load_hotels() == []
