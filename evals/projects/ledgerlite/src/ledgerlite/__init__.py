"""Minimal double-entry ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Ledger:
    accounts: dict[str, Decimal] = field(default_factory=dict)

    def open(self, name: str) -> None:
        if name in self.accounts:
            raise ValueError(f"account {name} already exists")
        self.accounts[name] = Decimal("0")

    def transfer(self, source: str, target: str, amount: str) -> None:
        value = Decimal(amount)
        if value <= 0:
            raise ValueError("amount must be positive")
        self.accounts[source] -= value
        self.accounts[target] += value

    def balance(self, name: str) -> Decimal:
        return self.accounts[name]

    def total(self) -> Decimal:
        return sum(self.accounts.values(), Decimal("0"))
