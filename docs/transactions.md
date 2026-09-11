# Portfolio transaction schema

Store the workbook at `data/portfolio.xlsx`, with one sheet named `transactions`.
Each row represents one executed transaction. Keep current prices, market values,
P&L, and calculated FIFO links out of this input sheet.

## Columns

Use these exact column names. All fields are required except `transfer_id`, which
is required only for transfers.

| Column | Type / allowed values | Description |
|---|---|---|
| `transaction_id` | Unique text | Transaction reference, such as `T001`. Store identifiers as text. |
| `execution_date` | Date or datetime | Execution date, displayed as `YYYY-MM-DD`. Include time when needed to order same-day trades; otherwise preserve their execution order in the sheet. |
| `instrument_id` | Text | Stable identifier for the exact instrument: preferably ISIN, otherwise ticker plus exchange. Use it consistently. |
| `action` | One of the six actions below | Whether the transaction opens, closes, or transfers units. |
| `quantity` | Positive decimal | Shares or fund units. Preserve fractional units and original precision. |
| `unit_price` | Positive decimal | Executed price or NAV per unit, preserving original precision. |
| `currency` | Three-letter currency code | Price and fee currency, such as `EUR`, `USD`, or `GBP`. |
| `fees` | Nonnegative decimal | Total transaction fees in `currency`; use `0` when none. |
| `transfer_id` | Text or blank | Shared reference linking outgoing and incoming transfer transactions. Blank for other actions. |

## Actions

| Value | Meaning |
|---|---|
| `OPEN_LONG` | Buy shares or fund units to own them. |
| `CLOSE_LONG` | Sell or redeem units already owned, matching the oldest eligible lots first. |
| `OPEN_SHORT` | Open an actual short sale of borrowed shares. |
| `CLOSE_SHORT` | Buy back shares to cover a short position. |
| `TRANSFER_OUT` | Units leaving a fund in a qualifying traspaso. |
| `TRANSFER_IN` | Units entering the destination fund in that traspaso. |

Quantities are always positive; the action determines their effect. A closure
must not exceed the available units. Record a deliberate reversal as a closure
and a separate opening.

## Synthetic example

Identifiers below are fictional. `—` means an empty Excel cell. All prices and
fees are in EUR.

| transaction_id | execution_date | instrument_id | action | quantity | unit_price | currency | fees | transfer_id |
|---|---|---|---|---:|---:|---|---:|---|
| T001 | 2026-01-05 | FUND_A | OPEN_LONG | 100 | 10.00 | EUR | 0.00 | — |
| T002 | 2026-01-09 | STOCK_X | OPEN_LONG | 10 | 100.00 | EUR | 1.00 | — |
| T003 | 2026-01-15 | STOCK_Y | OPEN_SHORT | 20 | 50.00 | EUR | 1.00 | — |
| T004 | 2026-02-05 | FUND_A | OPEN_LONG | 50 | 12.00 | EUR | 0.00 | — |
| T005 | 2026-02-09 | STOCK_X | OPEN_LONG | 5 | 110.00 | EUR | 1.00 | — |
| T006 | 2026-02-15 | STOCK_Y | OPEN_SHORT | 10 | 55.00 | EUR | 1.00 | — |
| T007 | 2026-03-05 | FUND_A | CLOSE_LONG | 60 | 15.00 | EUR | 0.00 | — |
| T008 | 2026-03-09 | STOCK_X | CLOSE_LONG | 12 | 120.00 | EUR | 1.00 | — |
| T009 | 2026-03-15 | STOCK_Y | CLOSE_SHORT | 25 | 40.00 | EUR | 1.00 | — |
| T010 | 2026-04-09 | STOCK_X | CLOSE_LONG | 3 | 125.00 | EUR | 1.00 | — |
| T011 | 2026-04-10 | FUND_A | TRANSFER_OUT | 60 | 16.00 | EUR | 0.00 | TR001 |
| T012 | 2026-04-12 | FUND_B | TRANSFER_IN | 24 | 40.00 | EUR | 0.00 | TR001 |
| T013 | 2026-04-15 | STOCK_Y | CLOSE_SHORT | 5 | 42.00 | EUR | 1.00 | — |
| T014 | 2026-05-05 | FUND_B | TRANSFER_OUT | 6 | 44.00 | EUR | 0.00 | TR002 |
| T015 | 2026-05-07 | FUND_C | TRANSFER_IN | 12 | 22.00 | EUR | 0.00 | TR002 |
| T016 | 2026-06-05 | FUND_A | CLOSE_LONG | 30 | 17.00 | EUR | 0.00 | — |

## Cases covered

- **Partial closure:** T007 sells 60 of the 100 units bought in T001.
- **Closure across purchases:** T008 sells all 10 units from T002 and 2 from T005;
  T010 closes the remaining 3.
- **Short positions:** T003 and T006 open shorts. T009 covers 20 units from T003
  and 5 from T006 under the proposed FIFO tracking policy; T013 covers the last 5.
- **Partial transfer across lots:** TR001 consumes the remaining 40 units from
  T001 and 20 from T004. The EUR 960 transferred buys 24 FUND_B units.
- **Subsequent partial transfer:** TR002 moves EUR 264 from FUND_B into FUND_C,
  preserving the relevant original acquisition history.
- **Full closure after a transfer:** T016 sells the last 30 FUND_A units.

## FIFO and transfer history

The program will generate purchase lots and closure links from these records,
allocating fees proportionally. Keep long and short lots separate; FIFO short
matching is a tracking policy, not a determination of short-sale tax treatment.

For qualifying traspasos, retain both the destination entry date/value and the
original fiscal acquisition dates/costs. A transfer spanning several original
lots must preserve them separately, including through subsequent transfers.
Outgoing and incoming execution dates and unit quantities may differ.

Use transfer actions only for qualifying traspasos. An ordinary redemption
followed by a purchase uses `CLOSE_LONG` and `OPEN_LONG`. See the
[AEAT fund-transfer guidance](https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-ayuda-presentacion/irpf-2025/7-cumplimentacion-irpf/7_6-ganancias-perdidas-patrimoniales/7_6_3-reglas-especiales-calculo/7_6_3_3-acciones-participaciones-instituciones-inversion-colectiva.html).

This initial schema assumes complete acquisition history. Historical transfers
without their original transactions require additional opening-lot information
from the broker before fiscal FIFO can be reconstructed.
