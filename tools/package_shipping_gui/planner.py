from dataclasses import dataclass

from .parser import PackageBatch


@dataclass(frozen=True)
class SheetTab:
    sheet_id: int
    title: str
    current_h2: str | None = None


@dataclass(frozen=True)
class PlanRow:
    tracking_number: str
    store_code: str
    quantity: int
    order_number: str | None
    sheet_id: int | None
    sheet_title: str | None
    current_h2: str | None
    new_h2: int
    status: str
    message: str


@dataclass(frozen=True)
class UpdatePlan:
    amount: int
    total_quantity: int
    rows: list[PlanRow]

    @property
    def ready_rows(self) -> list[PlanRow]:
        return [row for row in self.rows if row.status == "ready"]

    @property
    def has_blockers(self) -> bool:
        return any(row.status != "ready" for row in self.rows)


def build_update_plan(
    batch: PackageBatch,
    *,
    order_numbers_by_tracking: dict[str, list[str]],
    sheet_tabs: list[SheetTab],
    allow_overwrite: bool,
) -> UpdatePlan:
    rows: list[PlanRow] = []
    for item in batch.items:
        order_numbers = order_numbers_by_tracking.get(item.tracking_number, [])
        if not order_numbers:
            rows.append(_blocked_row(batch.amount, item, None, "no order number found"))
            continue
        if len(order_numbers) > 1:
            rows.append(
                _blocked_row(
                    batch.amount,
                    item,
                    None,
                    f"multiple order numbers found: {', '.join(order_numbers)}",
                )
            )
            continue

        order_number = order_numbers[0]
        matches = _matching_tabs(order_number, sheet_tabs)
        if not matches:
            rows.append(_blocked_row(batch.amount, item, order_number, "no matching sheet tab found"))
            continue
        if len(matches) > 1:
            rows.append(
                _blocked_row(
                    batch.amount,
                    item,
                    order_number,
                    "multiple matching sheet tabs found: "
                    + ", ".join(tab.title for tab in matches),
                )
            )
            continue

        tab = matches[0]
        current_h2 = tab.current_h2 or ""
        if current_h2.strip() and not allow_overwrite:
            rows.append(
                PlanRow(
                    tracking_number=item.tracking_number,
                    store_code=item.store_code,
                    quantity=item.quantity,
                    order_number=order_number,
                    sheet_id=tab.sheet_id,
                    sheet_title=tab.title,
                    current_h2=current_h2,
                    new_h2=batch.amount,
                    status="blocked",
                    message=f"H2 is not empty: {current_h2}",
                )
            )
            continue

        rows.append(
            PlanRow(
                tracking_number=item.tracking_number,
                store_code=item.store_code,
                quantity=item.quantity,
                order_number=order_number,
                sheet_id=tab.sheet_id,
                sheet_title=tab.title,
                current_h2=current_h2,
                new_h2=batch.amount,
                status="ready",
                message="ready",
            )
        )

    return UpdatePlan(amount=batch.amount, total_quantity=batch.total_quantity, rows=rows)


def _blocked_row(amount, item, order_number, message):
    return PlanRow(
        tracking_number=item.tracking_number,
        store_code=item.store_code,
        quantity=item.quantity,
        order_number=order_number,
        sheet_id=None,
        sheet_title=None,
        current_h2=None,
        new_h2=amount,
        status="blocked",
        message=message,
    )


def _matching_tabs(order_number: str, sheet_tabs: list[SheetTab]) -> list[SheetTab]:
    return [
        tab
        for tab in sheet_tabs
        if tab.title.strip().endswith(order_number) or f" {order_number}" in tab.title.strip()
    ]
