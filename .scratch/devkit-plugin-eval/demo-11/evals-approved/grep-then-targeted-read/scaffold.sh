#!/bin/bash
set -e
mkdir -p 'src/billing'
cat > 'src/billing/models.py' <<'PE_EOF_1'
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional


@dataclass
class LineItem:
    sku: str
    description: str
    quantity: int
    unit_price: Decimal
    tax_code: str = "STD"

    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass
class Invoice:
    invoice_id: str
    customer_id: str
    issued_on: date
    due_on: date
    currency: str = "CNY"
    items: List[LineItem] = field(default_factory=list)
    paid_on: Optional[date] = None
    notes: str = ""

    def total(self) -> Decimal:
        return sum((i.subtotal() for i in self.items), Decimal("0"))

    @property
    def is_paid(self) -> bool:
        return self.paid_on is not None


@dataclass
class Payment:
    payment_id: str
    invoice_id: str
    amount: Decimal
    received_on: date
    method: str = "bank_transfer"
PE_EOF_1
mkdir -p 'src/billing'
cat > 'src/billing/invoice_service.py' <<'PE_EOF_2'
"""Invoice lifecycle: creation, taxation, discounts, late fees, reminders.

This module is intentionally monolithic; it is slated to be split in Q4.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, List, Optional

from .models import Invoice, LineItem, Payment

log = logging.getLogger(__name__)

DEFAULT_PAYMENT_TERMS_DAYS = 30
GRACE_PERIOD_DAYS = 5
STANDARD_VAT_RATE = Decimal("0.13")
REDUCED_VAT_RATE = Decimal("0.06")
ZERO_VAT_RATE = Decimal("0")
EARLY_PAYMENT_DISCOUNT = Decimal("0.02")
EARLY_PAYMENT_WINDOW_DAYS = 10
MAX_LINE_ITEMS = 500
REMINDER_SCHEDULE_DAYS = (3, 7, 14, 30)
CENTS = Decimal("0.01")

_TAX_TABLE: Dict[str, Decimal] = {
    "STD": STANDARD_VAT_RATE,
    "RED": REDUCED_VAT_RATE,
    "ZERO": ZERO_VAT_RATE,
}


class InvoiceError(Exception):
    """Base class for invoice-related failures."""


class InvoiceLocked(InvoiceError):
    """Raised when mutating an invoice that has already been paid."""


class TooManyLineItems(InvoiceError):
    pass


def _round(amount: Decimal) -> Decimal:
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def new_invoice_id(prefix: str = "INV") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def create_invoice(
    customer_id: str,
    items: Iterable[LineItem],
    issued_on: Optional[date] = None,
    terms_days: int = DEFAULT_PAYMENT_TERMS_DAYS,
    currency: str = "CNY",
) -> Invoice:
    issued_on = issued_on or date.today()
    items = list(items)
    if len(items) > MAX_LINE_ITEMS:
        raise TooManyLineItems(f"{len(items)} > {MAX_LINE_ITEMS}")
    inv = Invoice(
        invoice_id=new_invoice_id(),
        customer_id=customer_id,
        issued_on=issued_on,
        due_on=issued_on + timedelta(days=terms_days),
        currency=currency,
        items=items,
    )
    log.info("created invoice %s for %s", inv.invoice_id, customer_id)
    return inv


def add_line_item(inv: Invoice, item: LineItem) -> None:
    if inv.is_paid:
        raise InvoiceLocked(inv.invoice_id)
    if len(inv.items) >= MAX_LINE_ITEMS:
        raise TooManyLineItems(inv.invoice_id)
    inv.items.append(item)


def remove_line_item(inv: Invoice, sku: str) -> bool:
    if inv.is_paid:
        raise InvoiceLocked(inv.invoice_id)
    before = len(inv.items)
    inv.items = [i for i in inv.items if i.sku != sku]
    return len(inv.items) != before


def tax_for_item(item: LineItem) -> Decimal:
    rate = _TAX_TABLE.get(item.tax_code, STANDARD_VAT_RATE)
    return _round(item.subtotal() * rate)


def compute_tax(inv: Invoice) -> Decimal:
    return sum((tax_for_item(i) for i in inv.items), Decimal("0"))


def compute_subtotal(inv: Invoice) -> Decimal:
    return _round(inv.total())


def early_payment_discount(inv: Invoice, paid_on: date) -> Decimal:
    """2% off if paid within the early-payment window."""
    if paid_on <= inv.issued_on + timedelta(days=EARLY_PAYMENT_WINDOW_DAYS):
        return _round(compute_subtotal(inv) * EARLY_PAYMENT_DISCOUNT)
    return Decimal("0")


def days_overdue(inv: Invoice, as_of: Optional[date] = None) -> int:
    as_of = as_of or date.today()
    if inv.is_paid:
        as_of = min(as_of, inv.paid_on)  # type: ignore[arg-type]
    delta = (as_of - inv.due_on).days - GRACE_PERIOD_DAYS
    return max(delta, 0)


def compute_total_due(inv: Invoice, as_of: Optional[date] = None) -> Decimal:
    subtotal = compute_subtotal(inv)
    tax = compute_tax(inv)
    late = compute_late_fee(inv, as_of)
    return _round(subtotal + tax + late)


def apply_payment(inv: Invoice, payment: Payment) -> Decimal:
    """Apply a payment; returns the remaining balance (may be negative)."""
    if payment.invoice_id != inv.invoice_id:
        raise InvoiceError("payment/invoice mismatch")
    due = compute_total_due(inv, payment.received_on)
    discount = early_payment_discount(inv, payment.received_on)
    remaining = _round(due - discount - payment.amount)
    if remaining <= 0:
        inv.paid_on = payment.received_on
    log.info("payment %s applied to %s, remaining %s", payment.payment_id, inv.invoice_id, remaining)
    return remaining


def reminder_dates(inv: Invoice) -> List[date]:
    return [inv.due_on + timedelta(days=d) for d in REMINDER_SCHEDULE_DAYS]


def next_reminder(inv: Invoice, as_of: Optional[date] = None) -> Optional[date]:
    as_of = as_of or date.today()
    if inv.is_paid:
        return None
    for d in reminder_dates(inv):
        if d >= as_of:
            return d
    return None


def invoices_overdue(invoices: Iterable[Invoice], as_of: Optional[date] = None) -> List[Invoice]:
    return [i for i in invoices if days_overdue(i, as_of) > 0]


def summarize(invoices: Iterable[Invoice]) -> Dict[str, Decimal]:
    out: Dict[str, Decimal] = {"count": Decimal(0), "subtotal": Decimal(0), "tax": Decimal(0)}
    for inv in invoices:
        out["count"] += 1
        out["subtotal"] += compute_subtotal(inv)
        out["tax"] += compute_tax(inv)
    return out


# ---------------------------------------------------------------------------
# Late fees
# ---------------------------------------------------------------------------

LATE_FEE_RATE = Decimal("0.015")  # per 30-day period, simple (not compounding)
LATE_FEE_CAP_RATIO = Decimal("0.20")


def compute_late_fee(inv: Invoice, as_of: Optional[date] = None) -> Decimal:
    """Late fee = subtotal * LATE_FEE_RATE per started 30-day period overdue,
    capped at LATE_FEE_CAP_RATIO of the subtotal."""
    overdue = days_overdue(inv, as_of)
    if overdue <= 0:
        return Decimal("0")
    periods = (overdue + 29) // 30
    subtotal = compute_subtotal(inv)
    fee = subtotal * LATE_FEE_RATE * periods
    cap = subtotal * LATE_FEE_CAP_RATIO
    return _round(min(fee, cap))


def waive_late_fee(inv: Invoice, reason: str) -> None:
    if not reason.strip():
        raise InvoiceError("waiver requires a reason")
    inv.notes = (inv.notes + f"\n[late fee waived] {reason}").strip()
    log.warning("late fee waived on %s: %s", inv.invoice_id, reason)


def export_rows(invoices: Iterable[Invoice]) -> List[Dict[str, str]]:
    rows = []
    for inv in invoices:
        rows.append(
            {
                "invoice_id": inv.invoice_id,
                "customer_id": inv.customer_id,
                "issued_on": inv.issued_on.isoformat(),
                "due_on": inv.due_on.isoformat(),
                "subtotal": str(compute_subtotal(inv)),
                "tax": str(compute_tax(inv)),
                "late_fee": str(compute_late_fee(inv)),
                "paid": "yes" if inv.is_paid else "no",
            }
        )
    return rows
PE_EOF_2
