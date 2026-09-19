# Instrument master

`data/instruments.xlsx` contains one sheet named `instruments`, initially empty.
Keep one row per exact `instrument_id` used in `transactions.xlsx`. All fields
are text; unknown metadata stays blank. The master is local and excluded from
Git, like the transaction workbook.

| Column | Meaning |
|---|---|
| `instrument_id` | Required, unique transaction identifier. |
| `name` | Provider's instrument name. |
| `instrument_type` | `stock`, `mutual_fund`, `etf`, `etp`, `etc`, `etn`, `fx`, or `crypto`, when known. |
| `asset_class` | Exposure; automatically set only for stocks, FX and direct crypto. |
| `isin` | Exact ISIN when verified. |
| `quote_currency` | Currency or price unit reported by the provider. Preserve units such as `GBp`; they are not GBP. |
| `exchange` | Provider's exchange code, not necessarily a MIC. |
| `timezone` | Provider's IANA timezone, when available. |
| `history_provider` | Provider selected for future historical downloads. |
| `history_symbol` | Symbol understood by that provider. |
| `quote_provider` | Provider selected for future latest-value queries. |
| `quote_symbol` | Symbol understood by that provider. |

## Three operations

```python
from src.data_io.instruments import (
    find_missing_instruments,
    fetch_instrument_metadata,
    update_instrument,
)

missing = find_missing_instruments()  # list[str], first occurrence order
metadata = fetch_instrument_metadata("BTC/EUR")  # dict[str, str | None]
instrument_id = update_instrument(metadata)  # str
```

The first operation reads and validates both workbooks, deduplicates transaction
IDs and returns only those absent from the master. It does not identify incomplete
existing records; refresh those explicitly by ID.

The second operation only fetches metadata. The caller can inspect or correct its
dictionary before saving, and can loop over selected IDs. Network errors propagate;
an unavailable service is not interpreted as an unknown instrument.

The third operation inserts or updates one row by ID. Only nonempty supplied
fields overwrite existing values; `None`, empty strings and whitespace preserve
existing values. Unknown columns, non-text values and duplicate master IDs are
rejected. Provider and symbol must be supplied together. Saving uses a temporary
file and atomic replacement. Keep Excel closed and use a single writer. Formatting
is not preserved. Explicitly edit the workbook to clear a previously stored value.

Each operation accepts alternative workbook paths where applicable. Fetching
does not read transactions or depend on a saved master record. To refresh an
ambiguous listing, pass the existing provider and history symbol explicitly.

## Provider selection and identifiers

- **Yahoo** (`provider="yahoo"`) is the default, using the existing `yfinance`
  dependency. Accepts ISINs, exact Yahoo symbols including exchange suffixes, and
  pairs such as `USD/EUR`, `BTC/EUR`, `ETH/EUR`. `BASE/QUOTE` means quote currency
  per unit of base. Crypto symbols are searched first; otherwise an FX symbol is
  queried and its returned type and currency checked. No name-based fuzzy match.
- **EODHD** (`provider="eodhd"`) supports ISIN resolution in this module. Set
  `EODHD_API_TOKEN` in the process environment to enable it; `.env` files are not
  loaded automatically. With a token, ISINs use EODHD by default. Exact ISIN
  matches are retained. For `EUFUND` only, an empty ISIN field is also accepted
  when `Code` exactly equals the requested ISIN. Conflicting ISINs and other
  share classes are rejected. HTTPS uses the `certifi` trusted certificate
  bundle, with verification enabled. No credentials are stored in Excel.
- For multiple candidates, a `ValueError` lists the symbols. Retry with
  `fetch_instrument_metadata(isin, provider="eodhd", symbol="CODE.EXCHANGE")`
  using one of those candidates. The caller chooses the intended exchange and
  currency; the first search result is never selected arbitrarily.
- Yahoo ISIN searches are checked against `Ticker.get_isin()`. That experimental
  lookup does not verify every fund: unresolved or mismatched ISINs raise an
  error directing the caller to EODHD. An explicit symbol does not bypass this
  check. EODHD coverage and plan access must still be checked for each instrument.
- Other identifiers must be exact Yahoo symbols. Arbitrary internal aliases
  require a manually prepared metadata dictionary passed to `update_instrument`.

Unknown exposure and timezone stay blank. Provider classifications are retained:
if a source labels an ETC/ETN as an ETF, check the issuer and correct the returned
dictionary before saving. A fund's exposure is not inferred from its name.

Both price mappings initially use the metadata provider and selected symbol.
They are configuration for the next stage, not proof of historical coverage or
real-time access. Funds will use their latest published NAV. This module downloads
no prices and does not validate daily-history depth or quote freshness.

## Fund classes and exchange listings

`LU0840158819` is Storm Fund II - Storm Bond Fund RC EUR. EODHD returns it as
`LU0840158819.EUFUND`, with the ISIN in `Code` and an empty `ISIN` field. The
exact-code rule above handles this without matching similar names. Its
`asset_class` is `fixed_income` and its share-class currency is `EUR`; Finect's
`NOK High Yield Bond` category describes the investment universe, not the
currency of this class. Do not substitute IC EUR, RC NOK or RCI EUR classes.
Identity references: [Finect](https://www.finect.com/fondos-inversion/LU0840158819-Storm_bond_rc_eur)
and the [fund manager](https://stormcapital.no/storm-bond-fund/).

For `CH1199067674`, select `21BC.XETRA` explicitly:

```python
metadata = fetch_instrument_metadata(
    "CH1199067674", provider="eodhd", symbol="21BC.XETRA"
)
metadata.update(instrument_type="etp", asset_class="crypto")
update_instrument(metadata)
```

EODHD uses `XETRA`; the market's MIC is `XETR`. The master stores the provider
code in `exchange`. Frankfurt (`21BC.F`) also trades in EUR, so currency alone
cannot resolve the listing. Selection is explicit and stable; trading volume
is not used to switch the reference series automatically. EODHD labels this
product `ETF`; the reviewed classification is `etp` with `crypto` exposure.

For subsequent refreshes, pass the saved `history_provider` and `history_symbol`
to the fetch method. This keeps fetching independent from Excel and preserves
the chosen listing. Reapply reviewed classification fields before saving if
the provider's labels differ. The master already contains all inputs needed
for the later price downloader to use this listing directly.

Transactions keep the ISIN as `instrument_id` and their actual execution
currency. No schema change is necessary for one reference valuation series
per instrument. If execution-venue analysis is needed later, add an optional
`execution_mic` to transactions; it records where that trade happened and is
separate from the reference listing in the master. If multiple valuation
listings per ISIN are needed, introduce a separate listings table then.

## Recreate the empty workbook

For a fresh checkout only (this replaces the target file):

```python
import pandas as pd
from src.data_io.instruments import COLUMNS, DEFAULT_PATH

pd.DataFrame(columns=COLUMNS).to_excel(
    DEFAULT_PATH, sheet_name="instruments", index=False, engine="openpyxl"
)
```

Provider references: [Yahoo search through yfinance](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Search.html)
and [EODHD search API](https://eodhd.com/financial-apis/search-api-for-stocks-etfs-mutual-funds).
