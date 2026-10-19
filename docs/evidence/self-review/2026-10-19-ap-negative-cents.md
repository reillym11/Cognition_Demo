# Self-review: AP negative extracted amounts (scan finding sfind-dee43a34705846aba98f20988244abb9)

`severity | file:line | finding | fixed?`

- low | backend/app/tools/ap/service.py `_match` | Negative subtotal/tax/total from PDF extraction (`parse_cents` allows `-`) reconciled and matched. They could then be approved, which lowered `po.invoiced_cents` and raised the PO's remaining value above its amount. | fixed: any negative cent field adds the `negative_amount` issue, so the invoice becomes `exception` and `submit` refuses it.
- low | backend/app/tools/ap/service.py `on_invoice_approved` | No floor on `invoiced_cents`. | fixed: a negative total raises `Conflict`, so approval can never lower `invoiced_cents`.

## Controls affected
- AP tool only. No foundation, protected-path, route or schema changes. `foundation/money.parse_cents` is unchanged because it is shared.

## Tests
- New `test_negative_amounts_are_exceptions_and_never_lower_po`. Backend ruff, mypy and pytest pass (78 passed, 1 skipped because the mocks are not running).
- Web lint/typecheck were not run (Node is missing on this VM). No web changes.

## Residual risk
- Credit notes are not supported. If they are needed later, they should be a separate document type with their own approval.
