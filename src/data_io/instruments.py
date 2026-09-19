"""Find missing instruments, fetch metadata, and maintain an Excel master."""

import json
import os
import re
import ssl
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote, urlencode
from urllib.request import urlopen

import certifi
import pandas as pd
import yfinance as yf

from src.data_io.transactions import DEFAULT_PATH as TRANSACTIONS_PATH
from src.data_io.transactions import _read_transactions

Instrument = dict[str, str | None]
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data/instruments.xlsx"
COLUMNS = [
    "instrument_id",
    "name",
    "instrument_type",
    "asset_class",
    "isin",
    "quote_currency",
    "exchange",
    "timezone",
    "history_provider",
    "history_symbol",
    "quote_provider",
    "quote_symbol",
]
INSTRUMENT_TYPES = {
    "EQUITY": "stock",
    "COMMON STOCK": "stock",
    "ETF": "etf",
    "ETP": "etp",
    "ETC": "etc",
    "ETN": "etn",
    "MUTUALFUND": "mutual_fund",
    "FUND": "mutual_fund",
    "CURRENCY": "fx",
    "CRYPTOCURRENCY": "crypto",
}
ISIN_PATTERN = r"[A-Z]{2}[A-Z0-9]{9}\d"


def _read_instruments(path: str | Path) -> pd.DataFrame:
    """Read the master, rejecting malformed schemas and duplicate IDs."""
    with pd.ExcelFile(path, engine="openpyxl") as workbook:
        if workbook.sheet_names != ["instruments"]:
            raise ValueError("Expected one sheet named instruments.")
        frame = pd.read_excel(workbook, dtype=object, keep_default_na=False)
    if list(frame.columns) != COLUMNS:
        raise ValueError("Columns do not match the instrument schema.")
    for column in COLUMNS:
        if not frame[column].map(lambda value: isinstance(value, str)).all():
            raise ValueError(f"{column} must contain text.")
    frame = frame.astype("string").replace(r"^\s*$", pd.NA, regex=True)
    ids = frame["instrument_id"]
    if ids.isna().any() or ids.duplicated().any():
        raise ValueError("Instrument IDs must be nonempty and unique.")
    return frame


def find_missing_instruments(
    transactions_path: str | Path = TRANSACTIONS_PATH,
    instruments_path: str | Path = DEFAULT_PATH,
) -> list[str]:
    """Return IDs absent from the master, in first-transaction order."""
    transactions = _read_transactions(transactions_path)
    instruments = _read_instruments(instruments_path)
    ids = transactions["instrument_id"].drop_duplicates()
    return ids[~ids.isin(instruments["instrument_id"])].tolist()


def _select_symbol(symbols: list[str], symbol: str | None) -> str:
    """Require one candidate or an explicit selection among candidates."""
    candidates = sorted(set(symbols))
    if not candidates:
        raise ValueError("No matching instrument found in this provider.")
    if symbol is not None and symbol in candidates:
        return symbol
    if symbol is None and len(candidates) == 1:
        return candidates[0]
    raise ValueError(f"Select a symbol from these candidates: {candidates}")


def _fetch_eodhd(instrument_id: str, symbol: str | None) -> Instrument:
    """Resolve an exact ISIN through EODHD's authenticated search API."""
    token = os.environ.get("EODHD_API_TOKEN")
    if not token:
        raise ValueError("Set EODHD_API_TOKEN to use EODHD.")
    params = urlencode({"api_token": token, "fmt": "json", "limit": 500})
    url = f"https://eodhd.com/api/search/{quote(instrument_id)}?{params}"
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(url, timeout=30, context=context) as response:
        results = json.load(response)
    if not isinstance(results, list):
        raise ValueError("EODHD did not return a search result list.")
    matches = {
        f"{item['Code']}.{item['Exchange']}": item
        for item in results
        if item.get("ISIN") == instrument_id
        or (
            not item.get("ISIN")
            and item.get("Exchange") == "EUFUND"
            and item.get("Code") == instrument_id
        )
    }
    selected = _select_symbol(list(matches), symbol)
    item = matches[selected]
    return {
        "name": item.get("Name"),
        "instrument_type": INSTRUMENT_TYPES.get(item.get("Type", "").upper()),
        "isin": instrument_id,
        "quote_currency": item.get("Currency"),
        "exchange": item.get("Exchange"),
        "history_symbol": selected,
    }


def _fetch_yahoo(instrument_id: str, symbol: str | None) -> Instrument:
    """Resolve ISINs, Yahoo symbols, or BASE/QUOTE pairs using Yahoo."""
    is_isin = re.fullmatch(ISIN_PATTERN, instrument_id) is not None
    is_pair = re.fullmatch(r"[A-Z0-9]+/[A-Z]{3}", instrument_id) is not None
    if is_isin:
        results = yf.Search(
            instrument_id,
            max_results=100,
            news_count=0,
            enable_fuzzy_query=False,
        ).quotes
        candidates = [item["symbol"] for item in results if "symbol" in item]
    elif is_pair:
        base, currency = instrument_id.split("/")
        results = yf.Search(
            base + "-" + currency,
            news_count=0,
            enable_fuzzy_query=False,
        ).quotes
        candidates = [
            item["symbol"]
            for item in results
            if item.get("symbol") == base + "-" + currency
            and item.get("quoteType") == "CRYPTOCURRENCY"
        ]
        if not candidates:
            candidates = [base + currency + "=X"]
    else:
        candidates = [instrument_id]
    selected = _select_symbol(candidates, symbol)
    ticker = yf.Ticker(selected)
    info = ticker.get_info()
    if info.get("symbol") != selected or not info.get("quoteType"):
        raise ValueError(f"No Yahoo metadata for {selected}.")
    if is_isin and ticker.get_isin() != instrument_id:
        raise ValueError("Yahoo could not verify this ISIN; try EODHD.")
    kind = INSTRUMENT_TYPES.get(info["quoteType"].upper())
    if is_pair and (
        kind not in {"fx", "crypto"} or info.get("currency") != currency
    ):
        raise ValueError("The returned instrument does not match the pair.")
    return {
        "name": info.get("longName") or info.get("shortName"),
        "instrument_type": kind,
        "isin": instrument_id if is_isin else None,
        "quote_currency": info.get("currency"),
        "exchange": info.get("exchange"),
        "timezone": info.get("exchangeTimezoneName"),
        "history_symbol": selected,
    }


def fetch_instrument_metadata(
    instrument_id: str,
    *,
    provider: str | None = None,
    symbol: str | None = None,
) -> Instrument:
    """Fetch one record without writing; use symbol to resolve ambiguity."""
    if not isinstance(instrument_id, str) or not instrument_id.strip():
        raise ValueError("instrument_id must be nonempty text.")
    is_isin = re.fullmatch(ISIN_PATTERN, instrument_id) is not None
    if provider is None:
        provider = (
            "eodhd"
            if is_isin and os.environ.get("EODHD_API_TOKEN")
            else "yahoo"
        )
    if provider == "eodhd" and is_isin:
        metadata = _fetch_eodhd(instrument_id, symbol)
    elif provider == "yahoo":
        metadata = _fetch_yahoo(instrument_id, symbol)
    else:
        raise ValueError("Use yahoo, or eodhd for ISIN identifiers.")
    record = dict.fromkeys(COLUMNS)
    record.update(metadata)
    record.update(
        instrument_id=instrument_id,
        asset_class={"stock": "equity", "fx": "fx", "crypto": "crypto"}.get(
            record["instrument_type"]
        ),
        history_provider=provider,
        quote_provider=provider,
        quote_symbol=record["history_symbol"],
    )
    return record


def update_instrument(
    metadata: Instrument,
    path: str | Path = DEFAULT_PATH,
) -> str:
    """Upsert one record atomically; None and blank fields preserve values."""
    if metadata.keys() - set(COLUMNS):
        raise ValueError("Unknown instrument fields.")
    if any(
        value is not None and not isinstance(value, str)
        for value in metadata.values()
    ):
        raise ValueError("Instrument fields must be text or None.")
    instrument_id = metadata.get("instrument_id")
    if not instrument_id or not instrument_id.strip():
        raise ValueError("instrument_id is required.")
    frame = _read_instruments(path).set_index("instrument_id")
    if instrument_id not in frame.index:
        frame = frame.reindex([*frame.index, instrument_id])
    for field, value in metadata.items():
        if field != "instrument_id" and value is not None and value.strip():
            frame.loc[instrument_id, field] = value
    for prefix in ("history", "quote"):
        fields = [f"{prefix}_provider", f"{prefix}_symbol"]
        supplied = [
            bool((metadata.get(field) or "").strip()) for field in fields
        ]
        if any(supplied) and not all(supplied):
            raise ValueError("Supply provider and symbol together.")
    path = Path(path)
    with NamedTemporaryFile(
        dir=path.parent, suffix=".xlsx", delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        frame.reset_index().to_excel(
            temporary,
            sheet_name="instruments",
            index=False,
            engine="openpyxl",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return instrument_id
