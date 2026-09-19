"""Check metadata resolution and safe updates without network access."""

import json
from io import BytesIO
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data_io import instruments as module
from src.data_io.transactions import COLUMNS as TRANSACTION_COLUMNS
from src.data_io.transactions import add_transactions


@pytest.fixture
def workbook_path(tmp_path):
    path = tmp_path / "instruments.xlsx"
    pd.DataFrame(columns=module.COLUMNS).to_excel(
        path, sheet_name="instruments", index=False
    )
    return path


def test_missing_ids_keep_order_and_remove_duplicates(tmp_path, workbook_path):
    transactions = tmp_path / "transactions.xlsx"
    pd.DataFrame(columns=TRANSACTION_COLUMNS).to_excel(
        transactions, sheet_name="transactions", index=False
    )
    add_transactions(
        [
            {
                "instrument_id": instrument_id,
                "execution_date": "2026-01-01",
                "action": "OPEN_LONG",
                "quantity": 1,
                "unit_price": 1,
                "currency": "EUR",
                "fees": 0,
            }
            for instrument_id in ("BTC/EUR", "USD/EUR", "BTC/EUR", "ETH/EUR")
        ],
        transactions,
    )
    module.update_instrument({"instrument_id": "USD/EUR"}, workbook_path)
    assert module.find_missing_instruments(transactions, workbook_path) == [
        "BTC/EUR",
        "ETH/EUR",
    ]


def test_update_preserves_missing_fields_and_other_rows(workbook_path):
    module.update_instrument(
        {"instrument_id": "BTC/EUR", "name": "Bitcoin", "exchange": "CCC"},
        workbook_path,
    )
    module.update_instrument({"instrument_id": "USD/EUR"}, workbook_path)
    module.update_instrument(
        {"instrument_id": "BTC/EUR", "name": "BTC", "exchange": None},
        workbook_path,
    )
    frame = pd.read_excel(workbook_path)
    assert len(frame) == 2
    assert list(frame.columns) == module.COLUMNS
    assert frame.loc[0, "name"] == "BTC"
    assert frame.loc[0, "exchange"] == "CCC"
    assert frame.loc[1, "instrument_id"] == "USD/EUR"


@pytest.mark.parametrize(
    "metadata",
    [
        {"instrument_id": ""},
        {"instrument_id": "BTC/EUR", "unknown": "x"},
        {"instrument_id": "BTC/EUR", "name": 42},
        {"instrument_id": "BTC/EUR", "history_provider": "yahoo"},
    ],
)
def test_invalid_update_does_not_modify_file(workbook_path, metadata):
    original = workbook_path.read_bytes()
    with pytest.raises(ValueError):
        module.update_instrument(metadata, workbook_path)
    assert workbook_path.read_bytes() == original


def test_duplicate_master_ids_are_rejected(workbook_path):
    frame = pd.DataFrame(
        [{"instrument_id": "BTC/EUR"}] * 2, columns=module.COLUMNS
    )
    frame.to_excel(workbook_path, sheet_name="instruments", index=False)
    with pytest.raises(ValueError, match="unique"):
        module.update_instrument({"instrument_id": "BTC/EUR"}, workbook_path)


def test_failed_save_preserves_original(workbook_path, monkeypatch):
    original = workbook_path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("Disk full")

    monkeypatch.setattr(pd.DataFrame, "to_excel", fail)
    with pytest.raises(OSError):
        module.update_instrument({"instrument_id": "BTC/EUR"}, workbook_path)
    assert workbook_path.read_bytes() == original
    assert list(workbook_path.parent.iterdir()) == [workbook_path]


@pytest.mark.parametrize(
    "instrument_id,symbol,quote_type",
    [
        ("USD/EUR", "USDEUR=X", "CURRENCY"),
        ("BTC/EUR", "BTC-EUR", "CRYPTOCURRENCY"),
        ("ETH/EUR", "ETH-EUR", "CRYPTOCURRENCY"),
    ],
)
def test_pair_resolution(monkeypatch, instrument_id, symbol, quote_type):
    quotes = (
        [{"symbol": symbol, "quoteType": quote_type}]
        if quote_type == "CRYPTOCURRENCY"
        else []
    )
    monkeypatch.setattr(
        module.yf, "Search", lambda *a, **k: SimpleNamespace(quotes=quotes)
    )
    info = {"symbol": symbol, "quoteType": quote_type, "currency": "EUR"}
    monkeypatch.setattr(
        module.yf,
        "Ticker",
        lambda value: SimpleNamespace(get_info=lambda: info),
    )
    record = module.fetch_instrument_metadata(instrument_id)
    assert record["history_symbol"] == symbol
    assert record["quote_symbol"] == symbol
    assert record["instrument_type"] == (
        "fx" if quote_type == "CURRENCY" else "crypto"
    )
    assert record["quote_currency"] == "EUR"
    assert list(record) == module.COLUMNS


def test_yahoo_isin_requires_selection_and_identity_match(monkeypatch):
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    monkeypatch.setattr(
        module.yf,
        "Search",
        lambda *a, **k: SimpleNamespace(
            quotes=[{"symbol": "ONE"}, {"symbol": "TWO"}]
        ),
    )
    isin = "IE00B03HD191"
    with pytest.raises(ValueError, match="candidates"):
        module.fetch_instrument_metadata(isin)
    info = {"symbol": "ONE", "quoteType": "MUTUALFUND", "currency": "EUR"}
    ticker = SimpleNamespace(get_info=lambda: info, get_isin=lambda: isin)
    monkeypatch.setattr(module.yf, "Ticker", lambda value: ticker)
    record = module.fetch_instrument_metadata(isin, symbol="ONE")
    assert record["isin"] == isin
    assert record["instrument_type"] == "mutual_fund"
    assert record["asset_class"] is None
    ticker.get_isin = lambda: "DIFFERENT"
    with pytest.raises(ValueError, match="verify"):
        module.fetch_instrument_metadata(isin, symbol="ONE")


def test_eodhd_filters_isin_and_keeps_unknown_metadata_empty(monkeypatch):
    monkeypatch.setenv("EODHD_API_TOKEN", "test-token")
    isin = "IE00B03HD191"
    results = [
        {
            "ISIN": isin,
            "Code": "FUND",
            "Exchange": "EUFUND",
            "Type": "Fund",
            "Currency": "EUR",
            "Name": "Example Fund",
        },
        {"ISIN": "OTHER", "Code": "WRONG", "Exchange": "US"},
    ]
    monkeypatch.setattr(
        module,
        "urlopen",
        lambda *a, **k: BytesIO(json.dumps(results).encode()),
    )
    record = module.fetch_instrument_metadata(isin)
    assert record["history_provider"] == "eodhd"
    assert record["history_symbol"] == "FUND.EUFUND"
    assert record["instrument_type"] == "mutual_fund"
    assert record["timezone"] is None
    assert record["asset_class"] is None


def test_network_error_is_not_treated_as_missing_instrument(monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError("Provider timed out")

    monkeypatch.setattr(module.yf, "Search", fail)
    with pytest.raises(TimeoutError):
        module.fetch_instrument_metadata("USD/EUR")


@pytest.mark.parametrize("isin_field", [None, ""])
def test_eufund_resolves_exact_code_when_isin_is_empty(
    monkeypatch, isin_field
):
    monkeypatch.setenv("EODHD_API_TOKEN", "test-token")
    isin = "LU0840158819"
    results = [
        {
            "Code": isin,
            "Exchange": "EUFUND",
            "ISIN": isin_field,
            "Name": "Storm Fund II - Storm Bond Fund RC EUR",
            "Type": "FUND",
            "Currency": "EUR",
        }
    ]
    monkeypatch.setattr(
        module,
        "urlopen",
        lambda *a, **k: BytesIO(json.dumps(results).encode()),
    )
    record = module.fetch_instrument_metadata(isin, provider="eodhd")
    assert record["isin"] == isin
    assert record["history_symbol"] == isin + ".EUFUND"
    assert record["quote_currency"] == "EUR"


@pytest.mark.parametrize(
    "code,exchange,isin_field",
    [
        ("LU0840158819", "EUFUND", "LU0840158900"),
        ("LU0840158819", "XETRA", None),
        ("LU0840158900", "EUFUND", None),
    ],
)
def test_eufund_code_fallback_rejects_other_classes_or_conflicts(
    monkeypatch,
    code,
    exchange,
    isin_field,
):
    monkeypatch.setenv("EODHD_API_TOKEN", "test-token")
    results = [{"Code": code, "Exchange": exchange, "ISIN": isin_field}]
    monkeypatch.setattr(
        module,
        "urlopen",
        lambda *a, **k: BytesIO(json.dumps(results).encode()),
    )
    with pytest.raises(ValueError, match="No matching instrument"):
        module.fetch_instrument_metadata("LU0840158819", provider="eodhd")


def test_explicit_listing_is_saved_and_reused(workbook_path, monkeypatch):
    monkeypatch.setenv("EODHD_API_TOKEN", "test-token")
    isin = "CH1199067674"
    results = [
        {
            "Code": "21BC",
            "Exchange": exchange,
            "ISIN": isin,
            "Type": "ETF",
            "Currency": "EUR",
        }
        for exchange in ("F", "XETRA")
    ]
    monkeypatch.setattr(
        module,
        "urlopen",
        lambda *a, **k: BytesIO(json.dumps(results).encode()),
    )
    with pytest.raises(ValueError, match="candidates"):
        module.fetch_instrument_metadata(isin)
    record = module.fetch_instrument_metadata(isin, symbol="21BC.XETRA")
    module.update_instrument(record, workbook_path)
    stored = module._read_instruments(workbook_path).iloc[0]
    refreshed = module.fetch_instrument_metadata(
        stored["instrument_id"],
        provider=stored["history_provider"],
        symbol=stored["history_symbol"],
    )
    assert refreshed["history_symbol"] == "21BC.XETRA"
    assert refreshed["exchange"] == "XETRA"
    assert refreshed["quote_currency"] == "EUR"
