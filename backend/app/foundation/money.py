import re
from dataclasses import dataclass

SUPPORTED_CURRENCIES = frozenset({"USD"})


@dataclass(frozen=True, slots=True)
class Money:
    """Integer minor units + explicit currency. Floats are rejected on purpose."""

    cents: int
    currency: str = "USD"

    def __post_init__(self) -> None:
        if isinstance(self.cents, bool) or not isinstance(self.cents, int):
            raise TypeError("Money.cents must be int")
        if self.currency not in SUPPORTED_CURRENCIES:
            raise ValueError(f"unsupported currency {self.currency!r} (prototype is USD-only)")

    def __add__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.cents + other.cents, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.cents - other.cents, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._same(other)
        return self.cents < other.cents

    def __le__(self, other: "Money") -> bool:
        self._same(other)
        return self.cents <= other.cents

    def _same(self, other: "Money") -> None:
        if other.currency != self.currency:
            raise ValueError("currency mismatch")

    def format(self) -> str:
        sign = "-" if self.cents < 0 else ""
        c = abs(self.cents)
        return f"{sign}${c // 100:,}.{c % 100:02d}"


def parse_cents(text: str) -> int:
    """'1,234.5' -> 123450. Decimal text only; never goes through float."""
    s = text.strip().replace(",", "").lstrip("$")
    m = re.fullmatch(r"(-?)(\d+)(?:\.(\d{1,2}))?", s)
    if not m:
        raise ValueError(f"not a money amount: {text!r}")
    cents = int(m[2]) * 100 + int((m[3] or "0").ljust(2, "0"))
    return -cents if m[1] else cents
