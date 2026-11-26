"""Invoice extraction, validation, and Excel export helpers."""

from __future__ import annotations

import base64
import json
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from openai import OpenAI
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class InvoiceExtractionError(Exception):
    """An invoice could not be read or did not contain required data."""


class LineItem(BaseModel):
    """One invoice line item."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="Description of the invoiced item")
    quantity: Decimal | None = Field(default=None, description="Quantity, if shown")
    unit_price: Decimal | None = Field(default=None, description="Unit price, if shown")
    amount: Decimal = Field(description="Extended amount for this line")

    @field_validator("quantity", "unit_price", "amount", mode="before")
    @classmethod
    def parse_decimal(cls, value: Any) -> Any:
        if value is None or isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Must be a valid number") from exc


class InvoiceData(BaseModel):
    """Validated invoice fields returned by the extraction model."""

    model_config = ConfigDict(extra="forbid")

    vendor_name: str | None = Field(description="Vendor or supplier name")
    invoice_number: str | None = Field(description="Invoice identifier")
    invoice_date: str | None = Field(description="Invoice date as printed")
    total_amount: Decimal | None = Field(description="Invoice grand total")
    line_items: list[LineItem] = Field(default_factory=list)

    @field_validator("total_amount", mode="before")
    @classmethod
    def parse_total(cls, value: Any) -> Any:
        if value is None or isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Must be a valid number") from exc


def parse_invoice_data(raw_json: str) -> InvoiceData:
    """Parse model JSON and reject absent/blank required invoice fields."""
    try:
        invoice = InvoiceData.model_validate_json(raw_json)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise InvoiceExtractionError(f"Could not validate extracted invoice data: {exc}") from exc

    missing = [
        label
        for label, value in (
            ("vendor name", invoice.vendor_name),
            ("invoice number", invoice.invoice_number),
            ("invoice date", invoice.invoice_date),
            ("total amount", invoice.total_amount),
        )
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if missing:
        raise InvoiceExtractionError(
            "The invoice is missing required fields: " + ", ".join(missing) + "."
        )
    return invoice


def _build_input_content(file_bytes: bytes, filename: str) -> list[dict[str, Any]]:
    """Create a Responses API image or PDF input block."""
    encoded = base64.b64encode(file_bytes).decode("ascii")
    if filename.lower().endswith(".pdf"):
        return [
            {
                "type": "input_file",
                "filename": filename,
                "file_data": f"data:application/pdf;base64,{encoded}",
            }
        ]
    suffix = filename.rsplit(".", 1)[-1].lower()
    mime_type = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix}"
    return [{"type": "input_image", "image_url": f"data:{mime_type};base64,{encoded}"}]


def extract_invoice(file_bytes: bytes, filename: str) -> InvoiceData:
    """Extract invoice fields with OpenAI and validate the structured response."""
    if not file_bytes:
        raise InvoiceExtractionError("The uploaded file is empty or unreadable.")
    if not filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".webp")):
        raise InvoiceExtractionError("Unsupported file type. Upload a PDF or image.")

    try:
        client = OpenAI()
        response = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Extract the invoice vendor name, invoice number, invoice date, "
                                "grand total, and line items. Use null for unavailable scalar "
                                "fields; do not guess. Preserve printed date and currency amount. "
                                "If the file is not a readable invoice, return null scalar fields."
                            ),
                        },
                        *_build_input_content(file_bytes, filename),
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "invoice_data",
                    "strict": True,
                    "schema": InvoiceData.model_json_schema(),
                }
            },
        )
    except Exception as exc:
        raise InvoiceExtractionError(
            f"Could not read the uploaded invoice or contact the extraction service: {exc}"
        ) from exc

    if not response.output_text:
        raise InvoiceExtractionError("The extraction service returned no invoice data.")
    return parse_invoice_data(response.output_text)


def create_excel(invoice: InvoiceData) -> bytes:
    """Return a formatted Excel workbook containing invoice details and items."""
    workbook = Workbook()
    details = workbook.active
    details.title = "Invoice"
    details.append(["Field", "Value"])
    details.append(["Vendor name", invoice.vendor_name])
    details.append(["Invoice number", invoice.invoice_number])
    details.append(["Invoice date", invoice.invoice_date])
    details.append(["Total amount", float(invoice.total_amount or 0)])

    items = workbook.create_sheet("Line Items")
    items.append(["Description", "Quantity", "Unit price", "Amount"])
    for item in invoice.line_items:
        items.append(
            [
                item.description,
                float(item.quantity) if item.quantity is not None else None,
                float(item.unit_price) if item.unit_price is not None else None,
                float(item.amount),
            ]
        )

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="244062")
        for column in sheet.columns:
            width = max(len(str(cell.value or "")) for cell in column) + 2
            sheet.column_dimensions[column[0].column_letter].width = min(width, 48)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
