"""Export everything the app stores about one user, and delete the account.

The export is generic on purpose: it walks every table that has a ``user_id`` column, so a
table added in a later stage is exported without touching this file. Secrets are left out
(the password hash, the encrypted CGM password and token, push subscription keys), because an
export is meant to be opened, shared with a clinic or moved elsewhere.
"""

import csv
import io
import json
import zipfile
from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Session

from glucobalance.db import Base
from glucobalance.models import SettingsTimeBlock, User, UserSettings

EXPORT_VERSION = 1
# Columns that hold secrets, and tables that are only secrets.
SECRET_COLUMNS = frozenset({"password_hash", "password_encrypted", "token_encrypted"})
SECRET_TABLES = frozenset({"push_subscriptions"})
# A spreadsheet runs a cell that starts with one of these as a formula.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _json_value(value: object) -> Any:
    """Turn a database value into something JSON (and a CSV cell) can hold."""
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, Enum):
        return value.value
    return value


def _row(item: DeclarativeBase) -> dict[str, Any]:
    mapper = type(item).__mapper__
    return {
        column.key: _json_value(getattr(item, column.key))
        for column in mapper.columns
        if column.key not in SECRET_COLUMNS
    }


def _user_models() -> list[Any]:
    """Every model with a ``user_id`` column, in table-name order."""
    models: list[Any] = [
        mapper.class_
        for mapper in Base.registry.mappers
        if "user_id" in mapper.columns and mapper.class_.__tablename__ not in SECRET_TABLES
    ]
    return sorted(models, key=lambda model: str(model.__tablename__))


def collect(session: Session, user: User, *, now: datetime) -> dict[str, Any]:
    """All of ``user``'s data as plain dictionaries, one list per table."""
    tables: dict[str, list[dict[str, Any]]] = {}
    for model in _user_models():
        rows = session.scalars(select(model).where(model.user_id == user.id).order_by(model.id))
        tables[model.__tablename__] = [_row(item) for item in rows]
    settings = session.scalars(select(UserSettings).where(UserSettings.user_id == user.id)).first()
    blocks: Iterable[SettingsTimeBlock] = (
        session.scalars(
            select(SettingsTimeBlock)
            .where(SettingsTimeBlock.settings_id == settings.id)
            .order_by(SettingsTimeBlock.start_time)
        )
        if settings is not None
        else []
    )
    tables["settings_time_blocks"] = [_row(block) for block in blocks]
    return {
        "app": "GlucoBalanceApp",
        "export_version": EXPORT_VERSION,
        "exported_at": now.astimezone(UTC).isoformat(),
        "note": "Glucose values are in mg/dL. All times are UTC. Not medical advice.",
        "user": _row(user),
        "tables": tables,
    }


def to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _cell(value: object) -> object:
    if isinstance(value, str) and value.startswith(_FORMULA_STARTS):
        return "'" + value
    return "" if value is None else value


def to_csv_zip(data: dict[str, Any]) -> bytes:
    """A ZIP with one CSV file per table that has rows (plus ``user.csv``)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        sheets = {"user": [data["user"]], **data["tables"]}
        for name, rows in sheets.items():
            if not rows:
                continue
            text = io.StringIO()
            writer = csv.DictWriter(text, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _cell(value) for key, value in row.items()})
            archive.writestr(f"{name}.csv", text.getvalue())
    return buffer.getvalue()


def delete_account(session: Session, user: User) -> None:
    """Delete the user and, through the database's ON DELETE CASCADE, everything they own.

    Rows that other people's rows point at with SET NULL (a settings change made *by* this
    user) lose only that pointer. Does not commit.
    """
    session.delete(user)
    session.flush()
