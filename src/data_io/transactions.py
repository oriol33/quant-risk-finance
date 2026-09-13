"""Manage the transaction ledger with pandas and a single Excel sheet."""

from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd

Transaction = dict[str, str | int | float | None]
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data/transactions.xlsx"
COLUMN_TYPES = {
    "transaction_id": "string",
    "execution_date": "datetime64[ns]",
    "instrument_id": "string",
    "action": "string",
    "quantity": "float64",
    "unit_price": "float64",
    "currency": "string",
    "fees": "float64",
    "transfer_id": "string",
}
COLUMNS = list(COLUMN_TYPES)
ACTIONS = {
    "OPEN_LONG",
    "CLOSE_LONG",
    "OPEN_SHORT",
    "CLOSE_SHORT",
    "TRANSFER_OUT",
    "TRANSFER_IN",
}


def _validate(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply column types and check ledger values before reading or saving."""
    if list(frame.columns) != COLUMNS:
        raise ValueError("Columns do not match the transaction schema.")
    frame = frame.copy()
    for column, dtype in COLUMN_TYPES.items():
        values = frame[column].dropna()
        if dtype == "string" and not values.map(type).eq(str).all():
            raise ValueError(f"{column} must contain text.")
        if dtype == "float64" and values.map(type).eq(bool).any():
            raise ValueError(f"{column} must contain numbers, not booleans.")
    frame["execution_date"] = pd.to_datetime(
        frame["execution_date"].astype("string"), format="ISO8601"
    )
    frame = frame.astype(COLUMN_TYPES)
    if frame[COLUMNS[:-1]].isna().any().any():
        raise ValueError("Required fields cannot be empty.")
    ids = frame["transaction_id"]
    if not ids.str.fullmatch(r"TX\d{6,}").all() or ids.duplicated().any():
        raise ValueError("Transaction IDs must be valid and unique.")
    if not ids.str[2:].astype(int).gt(0).all():
        raise ValueError("Transaction numbers must be positive.")
    if not frame["instrument_id"].str.strip().ne("").all():
        raise ValueError("instrument_id cannot be blank.")
    if not frame["action"].isin(ACTIONS).all():
        raise ValueError("Unknown transaction action.")
    if not frame["currency"].str.fullmatch(r"[A-Z]{3}").all():
        raise ValueError("currency must be a three-letter uppercase code.")
    numbers = frame[["quantity", "unit_price", "fees"]]
    if not np.isfinite(numbers).all().all() or (numbers < 0).any().any():
        raise ValueError("Numeric values must be finite and nonnegative.")
    if not frame[["quantity", "unit_price"]].gt(0).all().all():
        raise ValueError("quantity and unit_price must be positive.")
    frame["transfer_id"] = frame["transfer_id"].replace(
        r"^\s*$", pd.NA, regex=True
    )
    if (
        not frame["action"]
        .str.startswith("TRANSFER_")
        .eq(frame["transfer_id"].notna())
        .all()
    ):
        raise ValueError("transfer_id is required only for transfers.")
    return frame


def _read_transactions(path: str | Path) -> pd.DataFrame:
    """Read the single sheet, preserving text identifiers and blank cells."""
    with pd.ExcelFile(path, engine="openpyxl") as workbook:
        if workbook.sheet_names != ["transactions"]:
            raise ValueError("Expected one sheet named transactions.")
        frame = pd.read_excel(
            workbook,
            sheet_name="transactions",
            dtype=object,
            keep_default_na=False,
            na_values=[""],
        )
    return _validate(frame)


def _save_transactions(frame: pd.DataFrame, path: str | Path) -> None:
    """Validate and replace the workbook only after a successful save."""
    frame = _validate(frame)
    path = Path(path)
    with NamedTemporaryFile(
        dir=path.parent, suffix=".xlsx", delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        frame.to_excel(
            temporary,
            sheet_name="transactions",
            index=False,
            engine="openpyxl",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _check_fields(values: Transaction) -> None:
    """Allow only editable input fields; IDs are managed internally."""
    invalid = values.keys() - set(COLUMNS[1:])
    if invalid:
        fields = ", ".join(sorted(invalid))
        raise ValueError(f"Unknown or invalid fields supplied: {fields}")


def add_transactions(
    transactions: Transaction | list[Transaction],
    path: str | Path = DEFAULT_PATH,
) -> list[str]:
    """Add one or several records and return IDs generated from the maximum."""
    records = (
        transactions if isinstance(transactions, list) else [transactions]
    )
    if not records:
        return []
    for record in records:
        _check_fields(record)
    frame = _read_transactions(path)
    maximum = (
        int(frame["transaction_id"].str[2:].astype(int).max())
        if len(frame)
        else 0
    )
    ids = [f"TX{maximum + i:06d}" for i in range(1, len(records) + 1)]
    added = pd.DataFrame(records).reindex(columns=COLUMNS)
    added["transaction_id"] = ids
    added = _validate(added)
    _save_transactions(pd.concat([frame, added], ignore_index=True), path)
    return ids


def edit_transactions(
    transaction_id: str,
    changes: Transaction,
    path: str | Path = DEFAULT_PATH,
) -> list[str]:
    """Edit selected fields of one record and return its unchanged ID."""
    _check_fields(changes)
    frame = _read_transactions(path).astype(object)
    selected = frame["transaction_id"].eq(transaction_id)
    if not selected.any():
        raise KeyError(transaction_id)
    for column, value in changes.items():
        frame.loc[selected, column] = value
    _save_transactions(frame, path)
    return [transaction_id]


def delete_transactions(
    transaction_ids: str | list[str],
    path: str | Path = DEFAULT_PATH,
) -> list[str]:
    """Delete rows and return their IDs, keeping surviving IDs unchanged."""
    ids = (
        [transaction_ids]
        if isinstance(transaction_ids, str)
        else transaction_ids
    )
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    frame = _read_transactions(path)
    missing = set(ids) - set(frame["transaction_id"])
    if missing:
        raise KeyError(sorted(missing))
    _save_transactions(frame.loc[~frame["transaction_id"].isin(ids)], path)
    return ids
