import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PackageItem:
    tracking_number: str
    store_code: str
    quantity: int


@dataclass(frozen=True)
class PackageBatch:
    items: list[PackageItem]
    amount: int
    total_quantity: int


PACKAGE_LINE_RE = re.compile(
    r"包裹\s*#(?P<tracking>[A-Za-z0-9]+)\s+(?P<store>[A-Za-z]+)\s*[x×]\s*(?P<qty>\d+)",
    re.IGNORECASE,
)
AMOUNT_RE = re.compile(r"\$(\d+)")


def parse_package_text(text: str) -> PackageBatch:
    items: list[PackageItem] = []
    for line in text.splitlines():
        match = PACKAGE_LINE_RE.search(line.strip())
        if not match:
            continue
        items.append(
            PackageItem(
                tracking_number=match.group("tracking"),
                store_code=match.group("store"),
                quantity=int(match.group("qty")),
            )
        )

    if not items:
        raise ValueError("no package lines found")

    amount_match = AMOUNT_RE.search(text)
    if not amount_match:
        raise ValueError("shipping amount like $58 is required")

    total_quantity = sum(item.quantity for item in items)
    stated_total = _extract_stated_total(text)
    if stated_total is not None and stated_total != total_quantity:
        raise ValueError(
            f"quantity total mismatch: package rows sum to {total_quantity}, stated total is {stated_total}"
        )

    return PackageBatch(
        items=items,
        amount=int(amount_match.group(1)),
        total_quantity=total_quantity,
    )


def extract_order_numbers(email_text: str) -> list[str]:
    candidates: list[str] = []

    patterns = [
        r"mgo-(\d{5,})",
        r"注文番号[：:\s]*\d{6}-\d{8}-(\d{6,})",
        r"order_number=\d{6}-\d{8}-(\d{6,})",
        r"出荷番号[：:\s]*\d{8}-(\d{4,})",
        r"ご注文番号\s*[\r\n]+(\d{5,})",
        r"注文番号\s*[\r\n]+(\d{5,})",
        r"受注番号[】\]：:\s]*(?:mgo-)?(\d{5,})",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, email_text, re.IGNORECASE):
            _append_unique(candidates, match.group(1))

    return candidates


def _extract_stated_total(text: str) -> int | None:
    for line in text.splitlines():
        compact = line.strip().replace(" ", "")
        if not re.fullmatch(r"\d+(?:\+\d+)*=\d+", compact):
            continue
        left, right = compact.split("=", 1)
        if sum(int(value) for value in left.split("+")) != int(right):
            raise ValueError(f"quantity total expression is inconsistent: {line.strip()}")
        return int(right)
    return None


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
