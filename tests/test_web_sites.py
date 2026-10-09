"""The /sites page: suggestions, logging a use, skipping, blocking and weights."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from glucobalance.db import make_session_factory
from glucobalance.models import SiteBlock, SitePurpose, SiteUse
from glucobalance.site_service import suggestions
from glucobalance.sitemap import seed_body_sites, site_label
from test_web import STEP1, onboard, saved_user, sign_up

A = "abdomen-front-left-upper"


@pytest.fixture(autouse=True)
def body_map(engine: Engine) -> None:
    """The migration loads the body map; the test database is built without it."""
    with make_session_factory(engine)() as session:
        seed_body_sites(session)
        session.commit()


def pens(client: TestClient) -> None:
    sign_up(client)
    onboard(client, {**STEP1, "delivery_mode": "pens"})


def pump(client: TestClient) -> None:
    sign_up(client)
    onboard(client)


def test_sites_needs_login(client: TestClient) -> None:
    response = client.get("/sites", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_pump_page_shows_one_rotation_and_the_set_change(client: TestClient) -> None:
    pump(client)
    page = client.get("/sites").text
    assert "Infusion set" in page
    assert "Rapid-acting" not in page
    assert "No set change logged yet" in page


def test_pen_page_shows_two_rotations(client: TestClient) -> None:
    pens(client)
    page = client.get("/sites").text
    assert "Rapid-acting" in page
    assert "Long-acting" in page
    assert "Infusion set" not in page


def test_using_the_suggested_site_logs_it(client: TestClient, engine: Engine) -> None:
    pump(client)
    response = client.post("/sites/use", data={"code": A, "purpose": "infusion_set"})
    assert response.status_code == 200
    assert "Logged" in response.text
    assert "3 days until the next set change" in response.text

    session, user = saved_user(engine)
    uses = session.query(SiteUse).all()
    assert [(u.user_id, u.site.code, u.purpose) for u in uses] == [
        (user.id, A, SitePurpose.INFUSION_SET)
    ]
    session.close()


def test_skip_shows_the_next_best_site(client: TestClient, engine: Engine) -> None:
    pens(client)
    session, user = saved_user(engine)
    ranked = suggestions(session, user, SitePurpose.RAPID_INJECTION, now=datetime.now(UTC))
    session.close()

    page = client.get("/sites", params={"skip_rapid_injection": "1"}).text
    assert f'Next: <span class="font-semibold">{site_label(ranked[1])}</span>' in page


def test_a_bad_use_is_explained(client: TestClient) -> None:
    pump(client)
    response = client.post("/sites/use", data={"code": "elbow", "purpose": "infusion_set"})
    assert response.status_code == 422
    assert "Unknown site" in response.text


def test_a_bad_purpose_is_explained(client: TestClient) -> None:
    pump(client)
    response = client.post("/sites/use", data={"code": A, "purpose": "nonsense"})
    assert response.status_code == 422


def test_blocking_with_an_end_date_and_unblocking(client: TestClient, engine: Engine) -> None:
    pens(client)
    response = client.post(
        "/sites/block", data={"code": A, "until": "2099-01-01", "reason": "bruise"}
    )
    assert response.status_code == 200
    assert "bruise" in response.text

    session, _ = saved_user(engine)
    block = session.query(SiteBlock).one()
    assert block.until is not None
    session.close()

    response = client.post("/sites/unblock", data={"code": A})
    assert response.status_code == 200
    assert "bruise" not in response.text


def test_blocking_without_an_end_date_is_permanent(client: TestClient, engine: Engine) -> None:
    pens(client)
    client.post("/sites/block", data={"code": A, "until": "", "reason": ""})

    session, _ = saved_user(engine)
    assert session.query(SiteBlock).one().until is None
    session.close()


def test_a_past_end_date_is_explained(client: TestClient) -> None:
    pens(client)
    response = client.post("/sites/block", data={"code": A, "until": "2001-01-01"})
    assert response.status_code == 422
    assert "future" in response.text


def test_a_bad_date_is_explained(client: TestClient) -> None:
    pens(client)
    response = client.post("/sites/block", data={"code": A, "until": "soon"})
    assert response.status_code == 422


def test_setting_a_weight(client: TestClient, engine: Engine) -> None:
    pump(client)
    response = client.post("/sites/weight", data={"code": A, "weight": "0"})
    assert response.status_code == 200

    session, user = saved_user(engine)
    assert A not in suggestions(session, user, SitePurpose.INFUSION_SET, now=datetime.now(UTC))
    session.close()


def test_a_bad_weight_is_explained(client: TestClient) -> None:
    pump(client)
    response = client.post("/sites/weight", data={"code": A, "weight": "9"})
    assert response.status_code == 422
    assert "0 and 2" in response.text


def test_the_nav_links_to_sites(client: TestClient) -> None:
    pump(client)
    assert 'href="/sites"' in client.get("/today").text
