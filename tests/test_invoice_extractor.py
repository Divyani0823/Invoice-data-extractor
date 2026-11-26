from decimal import Decimal

import pytest

from invoice_extractor import InvoiceExtractionError, parse_invoice_data


def test_parse_valid_invoice_json() -> None:
    parsed = parse_invoice_data(
        '{"vendor_name":"Northwind Paper Co.","invoice_number":"NW-1042",'
        '"invoice_date":"2025-03-15","total_amount":127.50,"line_items":['
        '{"description":"Recycled notebooks","quantity":5,"unit_price":20.0,"amount":100.0}]}'
    )

    assert parsed.vendor_name == "Northwind Paper Co."
    assert parsed.total_amount == Decimal("127.5")
    assert parsed.line_items[0].amount == Decimal("100.0")


def test_missing_required_fields_are_reported() -> None:
    with pytest.raises(InvoiceExtractionError, match="invoice number, invoice date"):
        parse_invoice_data(
            '{"vendor_name":"Northwind Paper Co.","invoice_number":null,'
            '"invoice_date":null,"total_amount":null,"line_items":[]}'
        )


def test_invalid_json_has_clear_error() -> None:
    with pytest.raises(InvoiceExtractionError, match="Could not validate"):
        parse_invoice_data("not json")
