#!/bin/bash
set -e
mkdir -p 'services'
cat > 'services/__init__.py' <<'PE_EOF_1'
"""Service layer package."""
PE_EOF_1
mkdir -p 'services'
cat > 'services/notifications.py' <<'PE_EOF_2'
"""Outbound notification helpers."""
import logging

log = logging.getLogger(__name__)


def send_invoice_email(customer_id: str, invoice_id: str) -> None:
    log.info("sending invoice %s to %s", invoice_id, customer_id)


def send_credit_note_email(customer_id: str, invoice_id: str, amount: str) -> None:
    log.info("sending credit note %s for %s to %s", amount, invoice_id, customer_id)
PE_EOF_2
mkdir -p 'services'
cat > 'services/billing.py' <<'PE_EOF_3'
"""Billing service: invoices, proration, credit notes and gateway retries.

This module is intentionally self-contained so it can be exercised in
isolation by the worker process. Keep public functions small and push
formatting concerns into the ``_render_*`` helpers.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)

CENT = Decimal("0.01")
DEFAULT_CURRENCY = "CNY"
MAX_RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.5
GRACE_PERIOD_DAYS = 3


class BillingError(Exception):
    """Base class for billing failures."""


class InvoiceStateError(BillingError):
    """Raised when an operation is not valid for the invoice's current state."""


class CreditExceedsBalanceError(BillingError):
    """Raised when a credit note is larger than the open balance."""


class GatewayTimeout(BillingError):
    """Raised when the payment gateway does not answer in time."""


@dataclass
class LineItem:
    sku: str
    description: str
    quantity: int
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Invoice:
    invoice_id: str
    customer_id: str
    issued_on: date
    items: list[LineItem] = field(default_factory=list)
    currency: str = DEFAULT_CURRENCY
    state: str = "draft"
    credits: list[Decimal] = field(default_factory=list)
    paid_on: Optional[datetime] = None

    @property
    def subtotal(self) -> Decimal:
        return sum((i.amount for i in self.items), Decimal("0")).quantize(CENT)

    @property
    def credited(self) -> Decimal:
        return sum(self.credits, Decimal("0")).quantize(CENT)

    @property
    def balance(self) -> Decimal:
        return (self.subtotal - self.credited).quantize(CENT)

    @property
    def due_on(self) -> date:
        return self.issued_on + timedelta(days=GRACE_PERIOD_DAYS)


def _days_in_cycle(cycle_start: date) -> int:
    """Number of days in the monthly billing cycle containing ``cycle_start``."""
    first = cycle_start.replace(day=1)
    if first.month == 12:
        next_first = date(first.year + 1, 1, 1)
    else:
        next_first = date(first.year, first.month + 1, 1)
    return (next_first - first).days


def _compute_proration(
    plan_price: Decimal,
    days_used: int,
    days_in_cycle: int,
    *,
    rounding: str = ROUND_HALF_UP,
) -> Decimal:
    """Prorate ``plan_price`` for a partial billing cycle.

    Returns the amount owed for ``days_used`` out of ``days_in_cycle``,
    quantized to cents. ``days_used`` is clamped into ``[0, days_in_cycle]``
    so the result is never negative and never exceeds ``plan_price``.
    """
    if days_in_cycle <= 0:
        raise ValueError("days_in_cycle must be positive")
    days_used = max(0, min(days_used, days_in_cycle))
    ratio = Decimal(days_used) / Decimal(days_in_cycle)
    return (plan_price * ratio).quantize(CENT, rounding=rounding)


def build_invoice(
    customer_id: str,
    plan_sku: str,
    plan_price: Decimal,
    cycle_start: date,
    activated_on: date,
    extras: Iterable[LineItem] = (),
) -> Invoice:
    """Create a draft invoice for one billing cycle."""
    cycle_days = _days_in_cycle(cycle_start)
    used = cycle_days - max(0, (activated_on - cycle_start.replace(day=1)).days)
    prorated = _compute_proration(plan_price, used, cycle_days)
    invoice_id = f"INV-{customer_id}-{cycle_start:%Y%m}"
    inv = Invoice(invoice_id=invoice_id, customer_id=customer_id, issued_on=cycle_start)
    inv.items.append(LineItem(plan_sku, f"Plan {plan_sku} ({used}/{cycle_days} days)", 1, prorated))
    inv.items.extend(extras)
    log.debug("built %s with %d items", invoice_id, len(inv.items))
    return inv


def finalize_invoice(invoice: Invoice) -> Invoice:
    """Move a draft invoice into the ``open`` state."""
    if invoice.state != "draft":
        raise InvoiceStateError(f"{invoice.invoice_id} is {invoice.state}, expected draft")
    if not invoice.items:
        raise InvoiceStateError(f"{invoice.invoice_id} has no line items")
    invoice.state = "open"
    return invoice


def _apply_credit_note(invoice: Invoice, amount: Decimal, reason: str) -> Decimal:
    """Attach a credit of ``amount`` to ``invoice`` and return the new balance.

    Raises:
        InvoiceStateError: if the invoice is not in the ``open`` state.
        CreditExceedsBalanceError: if ``amount`` is greater than the open balance.
    """
    if invoice.state != "open":
        raise InvoiceStateError(f"cannot credit {invoice.invoice_id} in state {invoice.state}")
    amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    if amount > invoice.balance:
        raise CreditExceedsBalanceError(
            f"credit {amount} exceeds balance {invoice.balance} on {invoice.invoice_id}"
        )
    invoice.credits.append(amount)
    log.info("credited %s on %s: %s", amount, invoice.invoice_id, reason)
    if invoice.balance == Decimal("0"):
        invoice.state = "settled"
    return invoice.balance


def issue_credit_note(invoice: Invoice, amount: Decimal, reason: str) -> Decimal:
    """Public wrapper around :func:`_apply_credit_note` with input validation."""
    if amount <= 0:
        raise ValueError("credit amount must be positive")
    if not reason.strip():
        raise ValueError("a reason is required for audit purposes")
    return _apply_credit_note(invoice, amount, reason.strip())


def _with_retry(
    fn: Callable[[], Decimal],
    *,
    attempts: int = MAX_RETRY_ATTEMPTS,
    backoff: float = RETRY_BACKOFF_SECONDS,
) -> Decimal:
    """Call ``fn`` until it succeeds or ``attempts`` is exhausted."""
    last: Optional[BaseException] = None
    for n in range(1, attempts + 1):
        try:
            return fn()
        except GatewayTimeout as exc:
            last = exc
            log.warning("gateway timeout, attempt %d/%d", n, attempts)
            time.sleep(backoff * n)
    assert last is not None
    raise last


def charge_invoice(invoice: Invoice, gateway: Callable[[str, Decimal], Decimal]) -> Decimal:
    """Charge the open balance through ``gateway`` and settle the invoice."""
    if invoice.state != "open":
        raise InvoiceStateError(f"cannot charge {invoice.invoice_id} in state {invoice.state}")
    amount = invoice.balance
    captured = _with_retry(lambda: gateway(invoice.invoice_id, amount))
    if captured != amount:
        log.error("partial capture on %s: wanted %s got %s", invoice.invoice_id, amount, captured)
        raise BillingError("partial capture")
    invoice.state = "settled"
    invoice.paid_on = datetime.utcnow()
    return captured


def _render_summary(invoice: Invoice) -> str:
    lines = [f"{invoice.invoice_id} [{invoice.state}] {invoice.currency}"]
    for item in invoice.items:
        lines.append(f"  {item.sku:<12} x{item.quantity:<3} {item.amount:>10}")
    if invoice.credits:
        lines.append(f"  credits {invoice.credited:>24}")
    lines.append(f"  balance {invoice.balance:>24}")
    return "\n".join(lines)


def monthly_report(invoices: Iterable[Invoice]) -> dict[str, Decimal]:
    """Aggregate totals by state for the reporting job."""
    totals: dict[str, Decimal] = {}
    for inv in invoices:
        totals[inv.state] = totals.get(inv.state, Decimal("0")) + inv.balance
    for state, total in totals.items():
        totals[state] = total.quantize(CENT)
    return totals
PE_EOF_3
