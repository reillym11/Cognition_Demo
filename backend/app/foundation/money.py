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
