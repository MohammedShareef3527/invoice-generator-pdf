# Invoice Generator

A Python tool that turns a simple JSON file into a clean, print-ready **PDF invoice**. Built for small shops and freelancers who need professional bills without paying for billing software.

See [`sample_invoice.pdf`](sample_invoice.pdf) for example output.

## Features

- **Professional PDF layout**: seller and customer details, itemised table, totals, payment details and notes
- **GST support**: enter one GST percentage and it is split into CGST and SGST automatically
- **Discounts**: optional percentage discount applied before tax
- **Indian formatting**: ₹ symbol, lakh/crore digit grouping (`12,34,567.50`) and the total in words
- **Accurate money maths**: uses Python's `Decimal`, so there are no floating-point rounding errors
- **Input validation**: clear error messages for missing fields, zero quantities and invalid numbers
- **Brand colour**: change the accent colour per client
- **Tested**: 11 automated tests with pytest

## How to run

```bash
pip install -r requirements.txt
python invoice.py sample_invoice.json
```

This creates a PDF named after the invoice number. To choose the file name:

```bash
python invoice.py sample_invoice.json -o my_invoice.pdf
```

## Input format

Copy `sample_invoice.json` and edit it:

| Field | Required | Notes |
|---|---|---|
| `seller` | yes | `name` required; `address`, `phone`, `email`, `gstin` optional |
| `customer` | yes | `name` required; `address`, `phone`, `email`, `gstin` optional |
| `items` | yes | list of `description`, `quantity`, `rate` |
| `invoice_number`, `date`, `due_date` | no | defaults to an auto number and today's date |
| `discount_percent` | no | 0 to 100 |
| `gst_percent` | no | for example 18 |
| `payment_details`, `notes` | no | free text; use `\n` for new lines |
| `accent_color` | no | hex colour, for example `#1d4ed8` |

## How it works

1. `validate()` checks the JSON has everything needed
2. `calculate()` works out line totals, discount, GST and the grand total using `Decimal`
3. `generate_invoice()` lays out the PDF with ReportLab's Platypus (tables and paragraphs)
4. `amount_in_words()` converts the total using the Indian system (thousand, lakh, crore)
5. The tool looks for a font that contains the ₹ symbol (Segoe UI, Arial or DejaVu) and falls back to `Rs.` if none is found

## Run the tests

```bash
pytest
```

## Tech Stack

Python 3, ReportLab, pytest

## Possible Future Improvements

- A simple GUI or web form for entering invoice data
- IGST support for inter-state sales
- Company logo on the invoice
- Auto-incrementing invoice numbers saved between runs
