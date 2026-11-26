"""Streamlit interface for extracting invoice data into an Excel workbook."""

from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

from invoice_extractor import (
    InvoiceExtractionError,
    create_excel,
    extract_invoice,
)

load_dotenv()

st.set_page_config(page_title="Invoice Data Extractor", page_icon="🧾", layout="centered")
st.title("Invoice Data Extractor")
st.write("Upload an invoice and export its key details and line items to Excel.")

uploaded_file = st.file_uploader(
    "Choose an invoice", type=["pdf", "png", "jpg", "jpeg", "webp"]
)

if uploaded_file:
    st.caption(f"Selected: {uploaded_file.name} ({uploaded_file.size:,} bytes)")
    if st.button("Extract invoice data", type="primary"):
        if not os.getenv("OPENAI_API_KEY"):
            st.error("OPENAI_API_KEY is not set. Add it to your environment or .env file.")
        else:
            with st.spinner("Reading invoice and extracting data…"):
                try:
                    invoice = extract_invoice(
                        uploaded_file.getvalue(), uploaded_file.name
                    )
                    workbook = create_excel(invoice)
                    st.success("Invoice data extracted successfully.")
                    st.subheader("Invoice details")
                    st.write(
                        {
                            "Vendor": invoice.vendor_name,
                            "Invoice number": invoice.invoice_number,
                            "Date": invoice.invoice_date,
                            "Total": str(invoice.total_amount),
                        }
                    )
                    if invoice.line_items:
                        st.subheader("Line items")
                        st.dataframe(
                            [item.model_dump() for item in invoice.line_items],
                            use_container_width=True,
                        )
                    st.download_button(
                        "Download Excel file",
                        data=workbook,
                        file_name="invoice_data.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                except InvoiceExtractionError as exc:
                    st.error(str(exc))
                except Exception as exc:  # Keep unexpected provider errors actionable.
                    st.error(f"Extraction failed unexpectedly: {exc}")
