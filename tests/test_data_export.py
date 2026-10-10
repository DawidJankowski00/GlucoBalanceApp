"""Data export (JSON and CSV zip) and account deletion."""

import io
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select

from glucobalance.db import make_session_factory
from glucobalance.models import (
    CarbEntry,
    CGMConnection,
    CGMSourceKind,
    DoseKind,
    GlucoseReading,
    InsulinDose,
    InsulinType,
    PushSubscription,
    ReadingSource,
    User,
)
from test_web import PASSWORD, onboard, saved_user, sign_up

FORMULA_NOTE = '=HYPERLINK("http://evil.example")'


def set_up_with_data(client: TestClient, engine: Engine) -> None:
    sign_up(client)
    onboard(client)
    session, user = saved_user(engine)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    with session:
        session.add_all(
            [
                GlucoseReading(
                    user=user,
                    measured_at=now,
                    value_mgdl=110,
                    source=ReadingSource.MANUAL,
                    note=FORMULA_NOTE,
                ),
                CarbEntry(user=user, eaten_at=now, grams=Decimal("45.5"), description="rice"),
                InsulinDose(
                    user=user,
                    taken_at=now,
                    units=Decimal("4.50"),
                    insulin_type=InsulinType.RAPID,
                    kind=DoseKind.BOLUS,
                ),
                CGMConnection(
                    user=user,
                    source=CGMSourceKind.LIBRELINKUP,
                    email="f@example.com",
                    password_encrypted="SECRET-CIPHERTEXT",
                    token_encrypted="SECRET-TOKEN",
                ),
                PushSubscription(
                    user=user,
                    endpoint="https://push.example/abc",
                    p256dh="KEYKEY",
                    auth="AUTHAUTH",
                    created_at=now,
                ),
            ]
        )
        session.commit()


def test_json_export_contains_the_users_data(client: TestClient, engine: Engine) -> None:
    set_up_with_data(client, engine)
    response = client.get("/account/export.json")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    data = response.json()
    assert data["user"]["email"] == "ann@example.com"
    tables = data["tables"]
    assert tables["glucose_readings"][0]["value_mgdl"] == 110
    assert tables["glucose_readings"][0]["measured_at"].startswith("2026-09-01T12:00:00")
    assert tables["carb_entries"][0]["grams"] == "45.5"
    assert tables["insulin_doses"][0]["units"] == "4.5"
    assert tables["insulin_doses"][0]["insulin_type"] == "rapid"
    assert len(tables["settings_time_blocks"]) == 2
    assert tables["user_settings"][0]["delivery_mode"] == "pump"


def test_export_leaves_out_secrets(client: TestClient, engine: Engine) -> None:
    set_up_with_data(client, engine)
    text = client.get("/account/export.json").text
    with zipfile.ZipFile(io.BytesIO(client.get("/account/export.zip").content)) as archive:
        text += "".join(archive.read(name).decode() for name in archive.namelist())
    for secret in ("SECRET-CIPHERTEXT", "SECRET-TOKEN", "KEYKEY", "AUTHAUTH", "password_hash"):
        assert secret not in text
    assert "argon2" not in text
    assert "push_subscriptions" not in text


def test_csv_zip_has_one_file_per_table_and_neutralises_formulas(
    client: TestClient, engine: Engine
) -> None:
    set_up_with_data(client, engine)
    response = client.get("/account/export.zip")
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert {"user.csv", "glucose_readings.csv", "carb_entries.csv"} <= set(archive.namelist())
        readings = archive.read("glucose_readings.csv").decode()
    assert "'=HYPERLINK" in readings
    assert ',"=HYPERLINK' not in readings
    assert "manual" in readings


def test_export_needs_login(client: TestClient) -> None:
    assert client.get("/account/export.json", follow_redirects=False).status_code == 303
    assert client.get("/account/export.zip", follow_redirects=False).status_code == 303


def test_exports_only_contain_own_data(client: TestClient, engine: Engine) -> None:
    set_up_with_data(client, engine)
    client.post("/logout")
    sign_up(client, "bob@example.com")
    data = client.get("/account/export.json").json()
    assert data["user"]["email"] == "bob@example.com"
    assert data["tables"]["glucose_readings"] == []


def test_old_rows_are_exported_too(client: TestClient, engine: Engine) -> None:
    set_up_with_data(client, engine)
    session, user = saved_user(engine)
    with session:
        session.add(
            GlucoseReading(
                user=user,
                measured_at=datetime.now(UTC) - timedelta(days=900),
                value_mgdl=95,
                source=ReadingSource.MANUAL,
            )
        )
        session.commit()
    assert len(client.get("/account/export.json").json()["tables"]["glucose_readings"]) == 2


def count(engine: Engine, model: type) -> int:
    with make_session_factory(engine)() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def test_delete_needs_the_email_and_password(client: TestClient, engine: Engine) -> None:
    set_up_with_data(client, engine)
    wrong_email = client.post(
        "/account/delete", data={"confirm_email": "x@y.z", "password": PASSWORD}
    )
    assert wrong_email.status_code == 422
    wrong_password = client.post(
        "/account/delete", data={"confirm_email": "ann@example.com", "password": "nope"}
    )
    assert wrong_password.status_code == 422
    assert count(engine, User) == 1
    assert count(engine, GlucoseReading) == 1


def test_delete_removes_the_account_and_everything_it_owns(
    client: TestClient, engine: Engine
) -> None:
    set_up_with_data(client, engine)
    client.post("/logout")
    sign_up(client, "bob@example.com")
    client.post("/logout")
    client.post("/login", data={"email": "ann@example.com", "password": PASSWORD})
    response = client.post(
        "/account/delete",
        data={"confirm_email": " ANN@example.com ", "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    with make_session_factory(engine)() as session:
        assert [u.email for u in session.scalars(select(User))] == ["bob@example.com"]
    for model in (GlucoseReading, CarbEntry, InsulinDose, CGMConnection, PushSubscription):
        assert count(engine, model) == 0
    # logged out, and the old login no longer works
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    again = client.post("/login", data={"email": "ann@example.com", "password": PASSWORD})
    assert again.status_code == 401


def test_account_page_renders(client: TestClient) -> None:
    sign_up(client)
    onboard(client)
    page = client.get("/account")
    assert page.status_code == 200
    assert "Delete everything" in page.text
    assert "Download JSON" in page.text
