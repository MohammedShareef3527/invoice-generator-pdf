"""
Invoice Generator
-----------------
Turns a small JSON file (seller, customer, items) into a clean PDF invoice.

Usage:
    python invoice.py sample_invoice.json
    python invoice.py sample_invoice.json -o my_invoice.pdf
"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CENT = Decimal("0.01")

# Fonts that contain the rupee symbol, checked in order (Windows, Mac, Linux).
FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]
FONT_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


class InvoiceError(ValueError):
    """Raised when the input data is missing or invalid."""


# ---------------------------------------------------------------- money helpers
def money(value):
    """Convert anything number-like to a Decimal rounded to 2 places."""
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except Exception:
        raise InvoiceError(f"'{value}' is not a valid number")


def fmt(amount, symbol):
    """Format with Indian digit grouping: 1234567.5 -> 12,34,567.50"""
    amount = money(amount)
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return f"{sign}{symbol}{whole}.{frac}"


_ONES = ("Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen "
         "Fourteen Fifteen Sixteen Seventeen Eighteen Nineteen").split()
_TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def _below_thousand(n):
    words = []
    if n >= 100:
        words.append(_ONES[n // 100] + " Hundred")
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else ""))
    elif n > 0:
        words.append(_ONES[n])
    return " ".join(words)


def amount_in_words(amount):
    """1250.50 -> 'One Thousand Two Hundred Fifty Rupees and Fifty Paise Only' (Indian system)."""
    amount = money(amount)
    rupees, paise = int(amount), int((amount - int(amount)) * 100)
    if rupees == 0 and paise == 0:
        return "Zero Rupees Only"
    parts = []
    for value, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1000, "Thousand")):
        if rupees >= value:
            parts.append(_below_thousand(rupees // value) + " " + name)
            rupees %= value
    if rupees:
        parts.append(_below_thousand(rupees))
    text = " ".join(parts) + " Rupees" if parts else ""
    if paise:
        text += (" and " if text else "") + _below_thousand(paise) + " Paise"
    return text + " Only"


# ------------------------------------------------------------------- validation
def validate(data):
    for key in ("seller", "customer", "items"):
        if key not in data:
            raise InvoiceError(f"Missing '{key}' in invoice data")
    for key in ("name",):
        if not data["seller"].get(key):
            raise InvoiceError(f"seller.{key} is required")
        if not data["customer"].get(key):
            raise InvoiceError(f"customer.{key} is required")
    if not data["items"]:
        raise InvoiceError("Add at least one item")
    for i, item in enumerate(data["items"], 1):
        for key in ("description", "quantity", "rate"):
            if key not in item:
                raise InvoiceError(f"Item {i} is missing '{key}'")
        if money(item["quantity"]) <= 0:
            raise InvoiceError(f"Item {i}: quantity must be greater than 0")
        if money(item["rate"]) < 0:
            raise InvoiceError(f"Item {i}: rate cannot be negative")


def calculate(data):
    """Return line totals and the invoice totals as Decimals."""
    lines = []
    subtotal = Decimal("0.00")
    for item in data["items"]:
        qty, rate = money(item["quantity"]), money(item["rate"])
        total = (qty * rate).quantize(CENT, rounding=ROUND_HALF_UP)
        lines.append({"description": item["description"], "qty": qty, "rate": rate, "total": total})
        subtotal += total

    discount_pct = money(data.get("discount_percent", 0))
    gst_pct = money(data.get("gst_percent", 0))
    if not (0 <= discount_pct <= 100):
        raise InvoiceError("discount_percent must be between 0 and 100")
    if gst_pct < 0:
        raise InvoiceError("gst_percent cannot be negative")

    discount = (subtotal * discount_pct / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    taxable = subtotal - discount
    gst = (taxable * gst_pct / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    return {
        "lines": lines, "subtotal": subtotal, "discount": discount, "discount_pct": discount_pct,
        "taxable": taxable, "gst": gst, "gst_pct": gst_pct, "grand_total": taxable + gst,
    }


# --------------------------------------------------------------------- PDF build
def _register_fonts():
    """Use a TTF font so the rupee symbol prints; fall back to Helvetica + 'Rs.'"""
    regular = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
    bold = next((p for p in FONT_BOLD_CANDIDATES if os.path.exists(p)), None)
    if regular and bold:
        pdfmetrics.registerFont(TTFont("InvFont", regular))
        pdfmetrics.registerFont(TTFont("InvFont-Bold", bold))
        return "InvFont", "InvFont-Bold", "\u20b9"
    return "Helvetica", "Helvetica-Bold", "Rs. "


def generate_invoice(data, output_path):
    validate(data)
    calc = calculate(data)
    font, bold, sym = _register_fonts()
    accent = colors.HexColor(data.get("accent_color", "#1d4ed8"))

    base = getSampleStyleSheet()["Normal"]
    normal = ParagraphStyle("n", parent=base, fontName=font, fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=normal, fontSize=8.5, textColor=colors.HexColor("#555555"))
    right = ParagraphStyle("r", parent=normal, alignment=2)
    title = ParagraphStyle("t", parent=normal, fontName=bold, fontSize=22, textColor=accent, leading=26)
    h = ParagraphStyle("h", parent=normal, fontName=bold, fontSize=9, textColor=accent)

    def block(person):
        lines = [f"<b>{_x(person['name'])}</b>"]
        for key in ("address", "phone", "email"):
            if person.get(key):
                lines.append(_x(person[key]))
        if person.get("gstin"):
            lines.append("GSTIN: " + _x(person["gstin"]))
        return Paragraph("<br/>".join(lines), normal)

    invoice_no = data.get("invoice_number", f"INV-{datetime.now():%Y%m%d-%H%M}")
    inv_date = data.get("date", date.today().isoformat())

    doc = SimpleDocTemplate(
        output_path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title=f"Invoice {invoice_no}",
        author=data["seller"]["name"],
    )
    story = []

    head = Table(
        [[Paragraph("INVOICE", title),
          Paragraph(f"<b>Invoice No:</b> {_x(invoice_no)}<br/><b>Date:</b> {_x(inv_date)}"
                    + (f"<br/><b>Due:</b> {_x(data['due_date'])}" if data.get("due_date") else ""), right)]],
        colWidths=[90 * mm, 84 * mm],
    )
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [head, Spacer(1, 6 * mm)]

    parties = Table(
        [[Paragraph("FROM", h), Paragraph("BILL TO", h)],
         [block(data["seller"]), block(data["customer"])]],
        colWidths=[87 * mm, 87 * mm],
    )
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, 0), 3)]))
    story += [parties, Spacer(1, 7 * mm)]

    rows = [["#", "Description", "Qty", "Rate", "Amount"]]
    for i, ln in enumerate(calc["lines"], 1):
        qty = f"{ln['qty'].normalize():f}"
        rows.append([str(i), Paragraph(_x(ln["description"]), normal), qty,
                     fmt(ln["rate"], sym), fmt(ln["total"], sym)])
    items = Table(rows, colWidths=[10 * mm, 82 * mm, 18 * mm, 30 * mm, 34 * mm], repeatRows=1)
    items.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), bold), ("FONTNAME", (0, 1), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("BACKGROUND", (0, 0), (-1, 0), accent), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, accent),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [items, Spacer(1, 4 * mm)]

    tot = [["Subtotal", fmt(calc["subtotal"], sym)]]
    if calc["discount"] > 0:
        tot.append([f"Discount ({calc['discount_pct'].normalize():f}%)", "-" + fmt(calc["discount"], sym)])
    if calc["gst_pct"] > 0:
        half = (calc["gst"] / 2).quantize(CENT, rounding=ROUND_HALF_UP)
        pct_half = (calc["gst_pct"] / 2).normalize()
        tot.append([f"CGST ({pct_half:f}%)", fmt(half, sym)])
        tot.append([f"SGST ({pct_half:f}%)", fmt(calc["gst"] - half, sym)])
    tot.append(["TOTAL", fmt(calc["grand_total"], sym)])
    totals = Table(tot, colWidths=[40 * mm, 34 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), bold), ("FONTSIZE", (0, -1), (-1, -1), 11.5),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, accent), ("TEXTCOLOR", (0, -1), (-1, -1), accent),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [totals, Spacer(1, 4 * mm),
              Paragraph(f"<b>Amount in words:</b> {amount_in_words(calc['grand_total'])}", normal)]

    if data.get("payment_details"):
        story += [Spacer(1, 7 * mm), Paragraph("PAYMENT DETAILS", h),
                  Paragraph(_x(data["payment_details"]).replace("\n", "<br/>"), normal)]
    if data.get("notes"):
        story += [Spacer(1, 5 * mm), Paragraph("NOTES", h),
                  Paragraph(_x(data["notes"]).replace("\n", "<br/>"), normal)]
    story += [Spacer(1, 12 * mm), Paragraph("This is a computer-generated invoice.", small)]

    doc.build(story)
    return calc


def _x(text):
    """Escape characters that reportlab's mini-HTML would misread."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# -------------------------------------------------------------------------- CLI
def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate a PDF invoice from a JSON file.")
    parser.add_argument("input", help="Path to the invoice JSON file")
    parser.add_argument("-o", "--output", help="Output PDF path (default: <invoice number>.pdf)")
    args = parser.parse_args(argv)

    try:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
        out = args.output or f"{data.get('invoice_number', 'invoice')}.pdf"
        calc = generate_invoice(data, out)
    except FileNotFoundError:
        sys.exit(f"File not found: {args.input}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in {args.input}: {e}")
    except InvoiceError as e:
        sys.exit(f"Invoice error: {e}")

    print(f"Created {out}  |  Grand total: {calc['grand_total']:.2f}")


if __name__ == "__main__":
    main()
