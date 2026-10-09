"""The logbook: filtered, paged entries and the CSV export."""

import csv
import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.logbook import (
    LogbookError,
    LogbookFilters,
    parse_filters,
    query_logbook,
    to_csv,
)
from glucobalance.models import (
    CarbEntry,
    DisplayUnit,
    DoseKind,
    GlucoseReading,
    GlucoseTag,
    InsulinDose,
    InsulinType,
    Note,
    ReadingSource,
    User,
)
from glucobalance.timeline import EntryKind

WARSAW = ZoneInfo("Europe/Warsaw")
TODAY = date(2026, 10, 9)
T0 = datetime(2026, 10, 9, 6, 0, tzinfo=UTC)  # 08:00 in Warsaw
ALL = frozenset(EntryKind)


@pytest.fixture
def user(session: Session) -> User:
    return register(session, "ann@example.com", "Ann", "correct horse battery")


def glucose(
    user: User,
    minutes: int,
    value: int = 110,
    tag: GlucoseTag | None = None,
    note: str | None = None,
) -> GlucoseReading:
    return GlucoseReading(
        user=user,
        measured_at=T0 + timedelta(minutes=minutes),
        value_mgdl=value,
        source=ReadingSource.MANUAL,
        tag=tag,
        note=note,
    )


def filters(**changes: object) -> LogbookFilters:
    base = {"start": TODAY, "end": TODAY, "kinds": ALL, "tag": None}
    return LogbookFilters(**{**base, **changes})  # type: ignore[arg-type]


# ---------- filters from the query string ----------


def test_defaults_are_the_last_two_weeks_and_everything() -> None:
    parsed = parse_filters({}, TODAY)
    assert (parsed.start, parsed.end) == (date(2026, 9, 26), TODAY)
    assert parsed.kinds == ALL
    assert parsed.tag is None


def test_filters_are_read_from_the_query() -> None:
    parsed = parse_filters(
        {"start": "2026-10-01", "end": "2026-10-05", "type": "glucose,carbs", "tag": "fasting"},
        TODAY,
    )
    assert (parsed.start, parsed.end) == (date(2026, 10, 1), date(2026, 10, 5))
    assert parsed.kinds == {EntryKind.GLUCOSE, EntryKind.CARBS}
    assert parsed.tag is GlucoseTag.FASTING


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ({"start": "yesterday"}, "YYYY-MM-DD"),
        ({"end": "2026-13-01"}, "YYYY-MM-DD"),
        ({"start": "2026-10-09", "end": "2026-10-01"}, "before the end"),
        ({"start": "2025-01-01", "end": "2026-10-09"}, "one year"),
        ({"type": "lunch"}, "entry type"),
        ({"tag": "brunch"}, "tag"),
    ],
)
def test_bad_filters_give_a_readable_error(query: dict[str, str], message: str) -> None:
    with pytest.raises(LogbookError, match=message):
        parse_filters(query, TODAY)


def test_blank_values_mean_no_filter() -> None:
    parsed = parse_filters({"start": "", "end": "", "type": "", "tag": ""}, TODAY)
    assert parsed.kinds == ALL
    assert parsed.tag is None


# ---------- querying ----------


def test_rows_are_newest_first(session: Session, user: User) -> None:
    session.add_all([glucose(user, 0, 100), glucose(user, 60, 120), glucose(user, 30, 110)])
    session.flush()
    page = query_logbook(session, user.id, WARSAW, filters())
    assert [row.entry.value_mgdl for row in page.rows] == [120, 110, 100]  # type: ignore[union-attr]
    assert page.total == 3


def test_the_end_date_is_inclusive_in_local_time(session: Session, user: User) -> None:
    session.add_all(
        [
            glucose(user, -8 * 60 - 1, 101),  # 23:59 the day before, local
            glucose(user, -8 * 60, 102),  # 00:00 local
            glucose(user, 15 * 60 + 59, 103),  # 23:59 local
            glucose(user, 16 * 60, 104),  # 00:00 the next day, local
        ]
    )
    session.flush()
    page = query_logbook(session, user.id, WARSAW, filters())
    assert sorted(row.entry.value_mgdl for row in page.rows) == [102, 103]  # type: ignore[union-attr]


def test_kinds_can_be_filtered(session: Session, user: User) -> None:
    session.add_all(
        [
            glucose(user, 0),
            InsulinDose(
                user=user,
                taken_at=T0,
                units=Decimal("4"),
                insulin_type=InsulinType.RAPID,
                kind=DoseKind.BOLUS,
            ),
            CarbEntry(user=user, eaten_at=T0, grams=Decimal("45")),
            Note(user=user, noted_at=T0, text="walk"),
        ]
    )
    session.flush()
    only = query_logbook(session, user.id, WARSAW, filters(kinds=frozenset({EntryKind.INSULIN})))
    assert [row.kind for row in only.rows] == [EntryKind.INSULIN]
    assert query_logbook(session, user.id, WARSAW, filters()).total == 4


def test_a_tag_filter_keeps_only_matching_readings(session: Session, user: User) -> None:
    session.add_all(
        [
            glucose(user, 0, 100, GlucoseTag.FASTING),
            glucose(user, 10, 110, GlucoseTag.BEDTIME),
            glucose(user, 20, 120),
            CarbEntry(user=user, eaten_at=T0, grams=Decimal("45")),
        ]
    )
    session.flush()
    page = query_logbook(session, user.id, WARSAW, filters(tag=GlucoseTag.FASTING))
    assert [row.entry.value_mgdl for row in page.rows] == [100]  # type: ignore[union-attr]


def test_other_users_entries_are_never_shown(session: Session, user: User) -> None:
    other = register(session, "bob@example.com", "Bob", "correct horse battery")
    session.add_all([glucose(user, 0, 100), glucose(other, 0, 999)])
    session.flush()
    page = query_logbook(session, user.id, WARSAW, filters())
    assert [row.entry.value_mgdl for row in page.rows] == [100]  # type: ignore[union-attr]


def test_paging(session: Session, user: User) -> None:
    session.add_all([glucose(user, minute, 100 + minute) for minute in range(5)])
    session.flush()
    first = query_logbook(session, user.id, WARSAW, filters(), page=1, page_size=2)
    last = query_logbook(session, user.id, WARSAW, filters(), page=3, page_size=2)
    assert [row.entry.value_mgdl for row in first.rows] == [104, 103]  # type: ignore[union-attr]
    assert [row.entry.value_mgdl for row in last.rows] == [100]  # type: ignore[union-attr]
    assert (first.page, first.pages, first.total) == (1, 3, 5)


def test_a_page_past_the_end_is_the_last_page(session: Session, user: User) -> None:
    session.add_all([glucose(user, 0), glucose(user, 1), glucose(user, 2)])
    session.flush()
    page = query_logbook(session, user.id, WARSAW, filters(), page=99, page_size=2)
    assert (page.page, len(page.rows)) == (2, 1)
    assert query_logbook(session, user.id, WARSAW, filters(), page=0, page_size=2).page == 1


def test_an_empty_logbook_has_one_empty_page(session: Session, user: User) -> None:
    page = query_logbook(session, user.id, WARSAW, filters())
    assert (page.rows, page.page, page.pages, page.total) == ([], 1, 1, 0)


# ---------- CSV ----------


def parse(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_has_one_row_per_entry_with_local_and_utc_times(session: Session, user: User) -> None:
    session.add_all(
        [
            glucose(user, 0, 126, GlucoseTag.FASTING, "before run"),
            InsulinDose(
                user=user,
                taken_at=T0 + timedelta(minutes=5),
                units=Decimal("4.5"),
                insulin_type=InsulinType.RAPID,
                kind=DoseKind.BOLUS,
            ),
            CarbEntry(
                user=user,
                eaten_at=T0 + timedelta(minutes=6),
                grams=Decimal("45"),
                description="toast",
            ),
        ]
    )
    session.flush()
    rows = query_logbook(session, user.id, WARSAW, filters(), page_size=None).rows
    text = to_csv(rows, DisplayUnit.MGDL, WARSAW)
    assert text.splitlines()[0] == (
        "utc_time,local_time,type,glucose_mgdl,glucose_display,display_unit,"
        "insulin_units,insulin_kind,insulin_type,carbs_g,tag,note"
    )
    by_type = {row["type"]: row for row in parse(text)}
    glucose_row = by_type["glucose"]
    assert glucose_row["utc_time"] == "2026-10-09T06:00:00Z"
    assert glucose_row["local_time"] == "2026-10-09 08:00"
    assert (glucose_row["glucose_mgdl"], glucose_row["glucose_display"]) == ("126", "126")
    assert (glucose_row["display_unit"], glucose_row["tag"]) == ("mg/dL", "fasting")
    assert glucose_row["note"] == "before run"
    insulin_row = by_type["insulin"]
    assert (insulin_row["insulin_units"], insulin_row["insulin_kind"]) == ("4.5", "bolus")
    assert insulin_row["insulin_type"] == "rapid"
    carbs_row = by_type["carbs"]
    assert (carbs_row["carbs_g"], carbs_row["note"]) == ("45", "toast")


def test_csv_is_oldest_first_so_it_reads_like_a_diary(session: Session, user: User) -> None:
    session.add_all([glucose(user, 0, 100), glucose(user, 60, 120)])
    session.flush()
    rows = query_logbook(session, user.id, WARSAW, filters(), page_size=None).rows
    assert [r["glucose_mgdl"] for r in parse(to_csv(rows, DisplayUnit.MGDL, WARSAW))] == [
        "100",
        "120",
    ]


def test_csv_shows_mmol_next_to_the_stored_mg_dl(session: Session, user: User) -> None:
    session.add(glucose(user, 0, 126))
    session.flush()
    rows = query_logbook(session, user.id, WARSAW, filters(), page_size=None).rows
    (row,) = parse(to_csv(rows, DisplayUnit.MMOLL, WARSAW))
    assert (row["glucose_mgdl"], row["glucose_display"], row["display_unit"]) == (
        "126",
        "7.0",
        "mmol/L",
    )


@pytest.mark.parametrize("text", ["=1+1", "+cmd", "-2", "@SUM(A1)", "\tx"])
def test_csv_neutralises_spreadsheet_formulas(session: Session, user: User, text: str) -> None:
    session.add(glucose(user, 0, note=text))
    session.flush()
    rows = query_logbook(session, user.id, WARSAW, filters(), page_size=None).rows
    (row,) = parse(to_csv(rows, DisplayUnit.MGDL, WARSAW))
    assert row["note"] == "'" + text


def test_csv_quotes_commas_and_new_lines(session: Session, user: User) -> None:
    session.add(glucose(user, 0, note='pizza, "large"\nand cola'))
    session.flush()
    rows = query_logbook(session, user.id, WARSAW, filters(), page_size=None).rows
    (row,) = parse(to_csv(rows, DisplayUnit.MGDL, WARSAW))
    assert row["note"] == 'pizza, "large"\nand cola'
