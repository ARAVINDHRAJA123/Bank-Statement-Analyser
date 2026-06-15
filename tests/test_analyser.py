"""
Unit tests for Bank_Statement_Analyser.

Run from the repo root:
    pip install pytest
    pytest -q

These cover the pure, deterministic logic — parse_amount/parse_date,
assign_col (x-coordinate → column), extract_merchant, assign_category and
detect_anomalies — plus a regression test for the STATEMENT SUMMARY bug where
the statement's total-Debits figure was being written onto the last
transaction's empty debit field (see _parse_page_words).
"""
from datetime import date

import pytest

import Bank_Statement_Analyser as bsa


def word(text, x0, top):
    """Minimal stand-in for a pdfplumber word dict."""
    return {"text": text, "x0": x0, "top": top}


# ── parse_amount ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw, expected", [
    ("\u20b91,096,031.57", 1096031.57),
    ("1,905.85", 1905.85),
    ("\u20b975.00", 75.0),
    ("", 0.0),
    (None, 0.0),
    ("abc", 0.0),
    ("0.00", 0.0),
])
def test_parse_amount(raw, expected):
    assert bsa.parse_amount(raw) == expected


# ── parse_date / is_date ────────────────────────────────────────────────────
@pytest.mark.parametrize("raw, expected", [
    ("22/05/2026", date(2026, 5, 22)),
    ("21-03-26", date(2026, 3, 21)),
    ("27-May-2026", date(2026, 5, 27)),
    ("not a date", None),
    ("", None),
])
def test_parse_date(raw, expected):
    assert bsa.parse_date(raw) == expected


def test_is_date():
    assert bsa.is_date("01/01/2026") is True
    assert bsa.is_date("hello") is False


# ── assign_col (x-coordinate to column; start inclusive, end exclusive) ──────
@pytest.mark.parametrize("x0, expected", [
    (28, "date"),
    (59, "date"),
    (60, "narration"),     # boundary: belongs to narration, not date
    (420, "debit"),
    (500, "credit"),
    (580, "balance"),
    (27, None),            # left of the table
    (1000, None),          # right of the table
])
def test_assign_col(x0, expected):
    assert bsa.assign_col(x0) == expected


# ── extract_merchant ────────────────────────────────────────────────────────
@pytest.mark.parametrize("narration, expected", [
    ("UPI-SELVAKUMAR KRISHNA-SELVAKRISHNA1@OKAXIS-AXIS", "Selvakumar Krishna"),
    ("UPI-ANEESHKUMAR S-ANEESH2@OKHDFC-HDFC", "Aneeshkumar S"),
    ("UPI-MCDONALDS-MCD123@YBL-YESB", "Mcdonalds"),
])
def test_extract_merchant_upi(narration, expected):
    assert bsa.extract_merchant(narration) == expected


def test_extract_merchant_truncates_to_40():
    long = "UPI-" + "A" * 80
    assert len(bsa.extract_merchant(long)) <= 40


# ── assign_category ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("narration, credit, expected", [
    ("upi-mcdonalds-x", 0, "Food & Dining"),
    ("upi-uber india-x", 0, "Transport"),
    ("upi-netflix-x", 0, "Entertainment"),
    ("neft salary credit acme corp", 50000, "Salary / Income"),
    ("upi-unknownmerchant-x", 0, "Other Expense"),
    ("upi-unknownperson-x", 100, "Other Income"),
])
def test_assign_category(narration, credit, expected):
    assert bsa.assign_category(narration, credit) == expected


# ── detect_anomalies ────────────────────────────────────────────────────────
def test_detect_anomalies_flags_clear_outlier():
    rows = [{"debit": v} for v in [50, 60, 55, 45, 50, 52, 48, 5000]]
    flagged = bsa.detect_anomalies(rows)
    assert len(flagged) == 1
    assert flagged[0]["debit"] == 5000


def test_detect_anomalies_needs_minimum_sample():
    assert bsa.detect_anomalies([{"debit": 100}, {"debit": 200}]) == []


# ── REGRESSION: the STATEMENT SUMMARY totals bug ────────────────────────────
def test_summary_totals_do_not_pollute_last_transaction():
    """
    The last transaction is a credit (empty debit). The STATEMENT SUMMARY
    block below it carries the grand-total Debits figure in the debit column.
    Before the fix that figure was written onto the last txn's debit.
    """
    page = [
        word("Date", 30, 200), word("Narration", 70, 200),                 # header
        word("22/05/2026", 30, 210), word("UPI-ANEESHKUMAR", 70, 210),
        word("604.67", 500, 210), word("23,509.11", 580, 210),             # last txn
        word("STATEMENT", 80, 240), word("SUMMARY", 150, 240),             # summary title
        word("54,122.72", 70, 260), word("1,096,031.57", 420, 260),        # totals row
        word("1,065,417.96", 500, 260), word("23,509.11", 580, 260),
    ]
    rows, reached_summary = bsa._parse_page_words(page)

    assert reached_summary is True
    assert len(rows) == 1
    last = rows[0]
    assert last["debit"] == 0.0          # was 1096031.57 before the fix
    assert last["credit"] == 604.67
    assert last["balance"] == 23509.11


def test_legitimate_multiline_narration_still_merges():
    """A real continuation line (extra narration, no date) must still append."""
    page = [
        word("Date", 30, 200), word("Narration", 70, 200),
        word("01/05/2026", 30, 210), word("UPI-FOO", 70, 210),
        word("100.00", 420, 210),
        word("BARDESC", 70, 226),                                          # continuation
    ]
    rows, _ = bsa._parse_page_words(page)
    assert len(rows) == 1
    assert rows[0]["narration"] == "UPI-FOO BARDESC"
    assert rows[0]["debit"] == 100.0
