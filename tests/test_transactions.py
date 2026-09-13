"""Check pandas ledger operations using temporary synthetic data."""

import pandas as pd
import pytest

from src.data_io.transactions import (
    COLUMNS,
    add_transactions,
    delete_transactions,
    edit_transactions,
)


@pytest.fixture
def workbook_path(tmp_path):
    path = tmp_path / "transactions.xlsx"
    pd.DataFrame(columns=COLUMNS).to_excel(
        path, sheet_name="transactions", index=False
    )
    return path


@pytest.fixture
def transaction():
    return {
        "execution_date": "2026-09-10",
        "instrument_id": "IE00B03HD191",
        "action": "OPEN_LONG",
        "quantity": 12.65,
        "unit_price": 63.1993,
        "currency": "EUR",
        "fees": 0,
    }


def test_add_transactions(workbook_path, transaction):
    assert add_transactions(transaction, workbook_path) == ["TX000001"]
    assert add_transactions([transaction, transaction], workbook_path) == [
        "TX000002",
        "TX000003",
    ]
    frame = pd.read_excel(workbook_path)
    assert list(frame.columns) == COLUMNS
    assert frame["transaction_id"].tolist() == [
        "TX000001",
        "TX000002",
        "TX000003",
    ]
    assert frame.loc[0, "quantity"] == 12.65
    original = workbook_path.read_bytes()
    with pytest.raises(ValueError):
        add_transactions(transaction | {"quantity": -1}, workbook_path)
    assert workbook_path.read_bytes() == original


def test_edit_transactions(workbook_path, transaction):
    add_transactions(transaction, workbook_path)
    assert edit_transactions(
        "TX000001", {"quantity": 15, "fees": 1}, workbook_path
    ) == ["TX000001"]
    row = pd.read_excel(workbook_path).iloc[0]
    assert row["transaction_id"] == "TX000001"
    assert row["quantity"] == 15
    assert row["fees"] == 1
    assert row["unit_price"] == transaction["unit_price"]


def test_delete_transactions(workbook_path, transaction):
    ids = add_transactions([transaction] * 3, workbook_path)
    assert delete_transactions(ids[:2], workbook_path) == ids[:2]
    assert pd.read_excel(workbook_path)["transaction_id"].tolist() == [ids[2]]
    assert delete_transactions(ids[2], workbook_path) == [ids[2]]
    frame = pd.read_excel(workbook_path)
    assert frame.empty
    assert list(frame.columns) == COLUMNS
