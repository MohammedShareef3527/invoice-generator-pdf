import json
from decimal import Decimal

import pytest

from invoice import (InvoiceError, amount_in_words, calculate, fmt,
                     generate_invoice, main, money, validate)


def sample():
    return {
        "seller": {"name": "Shop"},
        "customer": {"name": "Buyer"},
        "items": [{"description": "Pen", "quantity": 3, "rate": 10.5}],
    }


def test_money_rounds_half_up():
    assert money("2.675") == Decimal("2.68")


def test_money_rejects_text():
    with pytest.raises(InvoiceError):
        money("abc")


def test_indian_grouping():
    assert fmt(1234567.5, "") == "12,34,567.50"
    assert fmt(999, "") == "999.00"
    assert fmt(100000, "Rs. ") == "Rs. 1,00,000.00"


def test_amount_in_words():
    assert amount_in_words(0) == "Zero Rupees Only"
    assert amount_in_words(1250.50) == "One Thousand Two Hundred Fifty Rupees and Fifty Paise Only"
    assert amount_in_words(100000) == "One Lakh Rupees Only"
    assert amount_in_words(12345678) == (
        "One Crore Twenty-Three Lakh Forty-Five Thousand Six Hundred Seventy-Eight Rupees Only")


def test_totals_with_discount_and_gst():
    data = sample()
    data["items"] = [{"description": "A", "quantity": 2, "rate": 100}]
    data["discount_percent"] = 10
    data["gst_percent"] = 18
    c = calculate(data)
    assert c["subtotal"] == Decimal("200.00")
    assert c["discount"] == Decimal("20.00")
    assert c["gst"] == Decimal("32.40")
    assert c["grand_total"] == Decimal("212.40")


def test_missing_items_rejected():
    data = sample()
    data["items"] = []
    with pytest.raises(InvoiceError):
        validate(data)


def test_bad_quantity_rejected():
    data = sample()
    data["items"][0]["quantity"] = 0
    with pytest.raises(InvoiceError):
        validate(data)


def test_discount_out_of_range():
    data = sample()
    data["discount_percent"] = 150
    with pytest.raises(InvoiceError):
        calculate(data)


def test_pdf_is_created(tmp_path):
    out = tmp_path / "x.pdf"
    generate_invoice(sample(), str(out))
    assert out.read_bytes()[:4] == b"%PDF"


def test_special_characters_do_not_break_pdf(tmp_path):
    data = sample()
    data["items"][0]["description"] = "Tom & Jerry <special> pens"
    out = tmp_path / "x.pdf"
    generate_invoice(data, str(out))
    assert out.exists()


def test_cli(tmp_path):
    src = tmp_path / "in.json"
    src.write_text(json.dumps(sample()))
    out = tmp_path / "out.pdf"
    main([str(src), "-o", str(out)])
    assert out.exists()
