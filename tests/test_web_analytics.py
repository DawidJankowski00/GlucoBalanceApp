"""The analytics page and the PDF report, end to end through the test client."""

import json
import re
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from glucobalance.analytics_service import parse_days
from glucobalance.models import GlucoseReading, ReadingSource
from test_web import STEP1, onboard, saved_user, sign_up


def set_up(client: TestClient, monitoring_mode: str = "cgm") -> None:
    sign_up(client)
    onboard(client, {**STEP1, "monitoring_mode": monitoring_mode, "timezone": "Europe/Warsaw"})


def add_days_of_readings(engine: Engine, days: int = 14, value: int = 120) -> None:
    """A reading every 15 minutes for the last ``days`` days, for the only user."""
    session, user = saved_user(engine)
    with session:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        for i in range(days * 96):
            session.add(
                GlucoseReading(
                    user=user,
                    measured_at=now - timedelta(minutes=15 * i),
                    value_mgdl=value + (i % 7) * 10,
                    source=ReadingSource.CGM,
                )
            )
        session.commit()


def test_pages_need_login(client: TestClient) -> None:
    for path in ("/analytics", "/report.pdf"):
        assert client.get(path, follow_redirects=False).status_code == 303


def test_analytics_without_readings_says_so(client: TestClient) -> None:
    set_up(client)
    page = client.get("/analytics").text
    assert "No glucose readings in this period" in page


def test_analytics_shows_statistics_and_the_agp(client: TestClient, engine: Engine) -> None:
    set_up(client)
    add_days_of_readings(engine)
    page = client.get("/analytics").text
    assert "Time in range" in page
    assert "GMI" in page
    assert "Ambulatory glucose profile" in page
    match = re.search(r'<script id="agp-data" type="application/json">(.*?)</script>', page, re.S)
    assert match
    figure = json.loads(match.group(1))
    assert figure["data"][-1]["name"] == "Median"


def test_a_glucometer_user_gets_time_of_day_averages(client: TestClient, engine: Engine) -> None:
    set_up(client, "glucometer")
    add_days_of_readings(engine, days=3)
    page = client.get("/analytics").text
    assert "Average by time of day" in page
    assert "agp-data" not in page


def test_a_short_period_of_data_warns_cgm_users(client: TestClient, engine: Engine) -> None:
    set_up(client)
    add_days_of_readings(engine, days=3)
    page = client.get("/analytics").text
    assert "of the period" in page  # the coverage warning


def test_the_period_can_be_30_days(client: TestClient, engine: Engine) -> None:
    set_up(client)
    add_days_of_readings(engine, days=3)
    assert "30 days" in client.get("/analytics?days=30").text
    assert "glucobalance-report" not in client.get("/analytics?days=nonsense").text


def test_glucose_is_shown_in_the_users_unit(client: TestClient, engine: Engine) -> None:
    sign_up(client)
    client.post(
        "/onboarding/1", data={**STEP1, "display_unit": "mmol/L", "timezone": "Europe/Warsaw"}
    )
    client.post(
        "/onboarding/2",
        data={
            "target_low": "3.9",
            "target_high": "10.0",
            "insulin_action_hours": "4",
            "max_bolus_units": "10",
            "dose_step_units": "0.5",
        },
    )
    client.post(
        "/onboarding/3", data={"block_start_0": "00:00", "block_icr_0": "10", "block_isf_0": "2.2"}
    )
    add_days_of_readings(engine, days=2, value=180)
    page = client.get("/analytics").text
    assert "mmol/L" in page
    assert "Very high (&gt; 13.9)" in page


def test_the_pdf_report_downloads(client: TestClient, engine: Engine) -> None:
    set_up(client)
    add_days_of_readings(engine)
    response = client.get("/report.pdf?days=14")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "glucobalance-report" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


def test_the_pdf_report_works_without_readings(client: TestClient) -> None:
    set_up(client)
    response = client.get("/report.pdf")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_the_navigation_links_to_reports(client: TestClient) -> None:
    set_up(client)
    assert 'href="/analytics"' in client.get("/").text


def test_parse_days_accepts_only_the_offered_periods() -> None:
    assert parse_days("30") == 30
    assert parse_days("14") == 14
    assert [parse_days(raw) for raw in (None, "", "7", "abc", "-30")] == [14] * 5
