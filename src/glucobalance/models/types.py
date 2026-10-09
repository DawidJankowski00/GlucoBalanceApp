"""Column types shared by the models."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Dialect, Enum, TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """A timezone-aware datetime, always stored and returned in UTC.

    Naive datetimes are rejected, so nothing is ever saved in an unknown timezone.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"naive datetime {value!r}: attach a timezone before saving")
        value = value.astimezone(UTC)
        # SQLite has no timezone support, so it stores the UTC wall-clock time.
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def str_enum(enum_class: type[StrEnum]) -> Enum:
    """Store a StrEnum as its plain string value (VARCHAR), not as a database enum type."""

    def values(members: Any) -> list[str]:
        return [member.value for member in members]

    return Enum(
        enum_class,
        native_enum=False,
        length=32,
        values_callable=values,
        validate_strings=True,
    )
