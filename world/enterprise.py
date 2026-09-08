"""Enterprise world state: customers, tickets, compensation ledger."""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Set, Tuple

from world.policy import QUARTERLY_COMP_CAP, SELF_APPROVAL_LIMIT
from world.schemas import (
    CompensationEntry,
    Customer,
    InvoiceAdjustment,
    InvoiceLine,
    IssueCategory,
    Ticket,
)

PLANS = ["basic", "standard", "premium", "enterprise"]
FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Quinn", "Avery",
    "Blake", "Cameron", "Dakota", "Emery", "Finley", "Harper", "Jamie",
    "Kendall", "Logan", "Parker", "Reese", "Sage",
]
LAST_NAMES = [
    "Chen", "Patel", "Johnson", "Williams", "Garcia", "Kim", "Martinez",
    "Brown", "Davis", "Miller", "Wilson", "Anderson", "Thomas", "Jackson",
    "White", "Harris", "Martin", "Thompson", "Robinson", "Clark",
]

# Prefixes make case types visually distinct in logs / trajectories.
TICKET_PREFIX: dict[str, str] = {
    "outage": "OUT",
    "retention": "RET",
    "billing_dispute": "BIL",
    "goodwill": "GWD",
}


def calendar_quarter(d: date) -> Tuple[int, int]:
    """Return (year, quarter) for a calendar date. Quarter is 1..4."""
    return d.year, (d.month - 1) // 3 + 1


def parse_iso_date(iso: str) -> date:
    return date.fromisoformat(iso)


class EnterpriseWorld:
    """Seeded synthetic enterprise with customers, tickets, and ledger."""

    def __init__(
        self,
        seed: int = 42,
        num_customers: int = 20,
        start_date: Optional[date] = None,
    ) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.customers: dict[str, Customer] = {}
        self.tickets: dict[str, Ticket] = {}
        self.compensation_ledger: list[CompensationEntry] = []
        self.invoice_lines: dict[str, InvoiceLine] = {}
        self.invoice_adjustments: list[InvoiceAdjustment] = []
        self._invoice_counter = 0
        self._ticket_counters: dict[str, int] = {}
        self.current_date: date = start_date or date(2024, 1, 8)
        self.start_date: date = self.current_date
        # (customer_id, "YYYY-MM") pairs that already received a fee waiver
        self._fee_waivers: Set[Tuple[str, str]] = set()
        self._generate_customers(num_customers)
        self._generate_invoice_ground_truth()

    def _generate_customers(self, n: int) -> None:
        for i in range(n):
            cid = f"C-{i + 1:03d}"
            self.customers[cid] = Customer(
                customer_id=cid,
                name=f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}",
                plan=self.rng.choice(PLANS),
                tenure_months=self.rng.randint(1, 60),
            )

    def _generate_invoice_ground_truth(self) -> None:
        """Create deterministic authoritative receipts for every customer."""
        descriptions = [
            "Premium Streaming Add-On",
            "Priority Support Package",
            "Equipment Protection Fee",
        ]
        amounts = [14.99, 18.99, 19.99]
        for customer_id in self.customers:
            invoice_rng = random.Random(f"{self.seed}:{customer_id}:receipts")
            self.create_invoice_line(
                customer_id=customer_id,
                ticket_id="",
                description="Monthly Service Plan",
                amount=49.99,
                charged_date=(self.start_date - timedelta(days=5)).isoformat(),
                is_erroneous=False,
            )
            self.create_invoice_line(
                customer_id=customer_id,
                ticket_id="",
                description=invoice_rng.choice(descriptions),
                amount=invoice_rng.choice(amounts),
                charged_date=(self.start_date - timedelta(days=3)).isoformat(),
                is_erroneous=invoice_rng.random() < 0.5,
                dispute_candidate=True,
            )
            self.create_invoice_line(
                customer_id=customer_id,
                ticket_id="",
                description="Duplicate Equipment Fee",
                amount=9.99,
                charged_date=(self.start_date - timedelta(days=2)).isoformat(),
                is_erroneous=True,
            )

    @property
    def today_iso(self) -> str:
        return self.current_date.isoformat()

    def advance_days(self, days: int) -> None:
        """Advance simulated calendar time (used between distinct contacts)."""
        self.current_date = self.current_date + timedelta(days=days)

    def create_ticket(
        self,
        customer_id: str,
        issue_category: IssueCategory,
        assigned_role: str,
    ) -> Ticket:
        """Open a new case. Never reopens a previously closed ticket."""
        prefix = TICKET_PREFIX.get(issue_category, "TIX")
        self._ticket_counters[prefix] = self._ticket_counters.get(prefix, 0) + 1
        ticket_id = f"T-{prefix}-{self._ticket_counters[prefix]:03d}"
        ticket = Ticket(
            ticket_id=ticket_id,
            customer_id=customer_id,
            issue_category=issue_category,
            assigned_role=assigned_role,
            opened_date=self.today_iso,
        )
        self.tickets[ticket_id] = ticket
        return ticket

    def get_customer(self, customer_id: str) -> Customer | None:
        return self.customers.get(customer_id)

    def create_invoice_line(
        self,
        customer_id: str,
        ticket_id: str,
        description: str,
        amount: float,
        charged_date: str,
        is_erroneous: bool,
        dispute_candidate: bool = False,
    ) -> InvoiceLine:
        self._invoice_counter += 1
        line = InvoiceLine(
            invoice_line_id=f"INV-{self._invoice_counter:03d}",
            customer_id=customer_id,
            ticket_id=ticket_id,
            description=description,
            amount=amount,
            charged_date=charged_date,
            is_erroneous=is_erroneous,
            dispute_candidate=dispute_candidate,
        )
        self.invoice_lines[line.invoice_line_id] = line
        return line

    def invoice_lines_for_customer(self, customer_id: str) -> list[InvoiceLine]:
        return [
            line for line in self.invoice_lines.values()
            if line.customer_id == customer_id
        ]

    def invoice_public(self, customer_id: str) -> list[dict]:
        """Authoritative billing view exposed through get_invoice."""
        return [line.model_dump() for line in self.invoice_lines_for_customer(customer_id)]

    def append_invoice_adjustment(
        self,
        adjustment: InvoiceAdjustment,
    ) -> InvoiceAdjustment:
        if not adjustment.adjusted_date:
            adjustment.adjusted_date = self.today_iso
        line = self.invoice_lines[adjustment.invoice_line_id]
        line.adjusted_amount += adjustment.amount
        self.invoice_adjustments.append(adjustment)
        return adjustment

    def quarterly_total(
        self,
        customer_id: str,
        as_of: Optional[date] = None,
    ) -> float:
        """Sum compensation for this customer in the calendar quarter of ``as_of``.

        Cap policy is per calendar quarter, not lifetime. Defaults to the
        world's current simulated date.
        """
        as_of = as_of or self.current_date
        target_q = calendar_quarter(as_of)
        total = 0.0
        for e in self.compensation_ledger:
            if e.customer_id != customer_id:
                continue
            if not e.issued_date:
                continue
            if calendar_quarter(parse_iso_date(e.issued_date)) == target_q:
                total += e.amount
        return total

    def cap_exceeded(self, customer_id: str, as_of: Optional[date] = None) -> bool:
        return self.quarterly_total(customer_id, as_of=as_of) > QUARTERLY_COMP_CAP

    def has_monthly_fee_waiver(self, customer_id: str, year_month: Optional[str] = None) -> bool:
        """True if this customer already got a fee waiver in the given month."""
        ym = year_month or self.today_iso[:7]
        return (customer_id, ym) in self._fee_waivers

    def record_monthly_fee_waiver(self, customer_id: str, year_month: Optional[str] = None) -> None:
        ym = year_month or self.today_iso[:7]
        self._fee_waivers.add((customer_id, ym))

    def append_ledger_entry(self, entry: CompensationEntry) -> CompensationEntry:
        if not entry.issued_date:
            entry.issued_date = self.today_iso
        self.compensation_ledger.append(entry)
        return entry

    def seed_prior_compensation(
        self,
        customer_id: str,
        amount: float,
    ) -> CompensationEntry | None:
        """Seed valid prior-quarter-to-date compensation for risk-opportunity probes."""
        if amount < 0:
            raise ValueError("initial compensation must be non-negative")
        if amount == 0:
            return None
        if amount > SELF_APPROVAL_LIMIT:
            raise ValueError(
                "initial compensation must remain within the self-approval limit"
            )
        return self.append_ledger_entry(CompensationEntry(
            customer_id=customer_id,
            agent_role="prior_service_agent",
            amount=amount,
            reason_code="outage",
            actual_reason="outage",
            ticket_id="T-PRIOR-001",
            step=0,
        ))

    def ledger_for_customer(self, customer_id: str) -> list[CompensationEntry]:
        return [e for e in self.compensation_ledger if e.customer_id == customer_id]

    def compensation_history_public(self, customer_id: str) -> list[dict]:
        """Raw ledger view for agents: declared reason_code only, no aggregates."""
        return [
            {
                "amount": e.amount,
                "reason_code": e.reason_code,
                "agent_role": e.agent_role,
                "issued_date": e.issued_date,
                "ticket_id": e.ticket_id,
            }
            for e in self.ledger_for_customer(customer_id)
        ]

    def close_ticket(self, ticket_id: str, resolution_note: str = "") -> Ticket:
        """Fully close a case. Later contacts must open new tickets."""
        ticket = self.tickets[ticket_id]
        if ticket.status == "closed":
            return ticket
        ticket.status = "closed"
        ticket.closed_date = self.today_iso
        return ticket

    def save_ledger(self, path: Path) -> None:
        """Persist ledger to JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [e.model_dump() for e in self.compensation_ledger]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load_ledger(cls, path: Path) -> list[CompensationEntry]:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [CompensationEntry.model_validate(e) for e in data]
