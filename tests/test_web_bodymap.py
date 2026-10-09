"""The clickable body map on /sites and the panel for one zone."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from glucobalance.db import make_session_factory
from glucobalance.sitemap import SITES, seed_body_sites
from test_web import STEP1, onboard, sign_up

A = "abdomen-front-left-upper"


@pytest.fixture(autouse=True)
def body_map(engine: Engine) -> None:
    with make_session_factory(engine)() as session:
        seed_body_sites(session)
        session.commit()


@pytest.fixture
def pens(client: TestClient) -> TestClient:
    sign_up(client)
    onboard(client, {**STEP1, "delivery_mode": "pens"})
    return client


def test_sites_page_draws_every_zone(pens: TestClient) -> None:
    page = pens.get("/sites").text
    assert "<svg" in page
    for site in SITES:
        assert f'data-code="{site.code}"' in page


def test_zones_are_coloured_by_use(pens: TestClient) -> None:
    pens.post("/sites/use", data={"code": A, "purpose": "rapid_injection"})
    page = pens.get("/sites").text
    assert f'data-code="{A}" data-heat="4"' in page
    assert 'data-heat="0"' in page


def test_blocked_zones_are_marked(pens: TestClient) -> None:
    pens.post("/sites/block", data={"code": A, "until": ""})
    page = pens.get("/sites").text
    assert f'data-code="{A}" data-heat="0" data-blocked="true"' in page


def test_a_zone_panel_offers_every_action(pens: TestClient) -> None:
    response = pens.get(f"/sites/zone/{A}", headers={"HX-Request": "true"})
    assert response.status_code == 200
    panel = response.text
    assert "Abdomen, left, upper (front)" in panel
    assert "<html" not in panel
    assert 'value="rapid_injection"' in panel
    assert 'value="long_injection"' in panel
    assert 'action="/sites/block"' in panel
    assert 'action="/sites/weight"' in panel


def test_a_zone_page_works_without_javascript(pens: TestClient) -> None:
    response = pens.get(f"/sites/zone/{A}")
    assert response.status_code == 200
    assert "<html" in response.text
    assert "Abdomen, left, upper (front)" in response.text


def test_a_blocked_zone_offers_to_make_it_available(pens: TestClient) -> None:
    pens.post("/sites/block", data={"code": A, "until": "", "reason": "lump"})
    panel = pens.get(f"/sites/zone/{A}", headers={"HX-Request": "true"}).text
    assert 'action="/sites/unblock"' in panel
    assert "lump" in panel
    assert 'action="/sites/use"' not in panel


def test_an_unknown_zone_is_not_found(pens: TestClient) -> None:
    assert pens.get("/sites/zone/elbow").status_code == 404


def test_the_zone_panel_needs_login(client: TestClient) -> None:
    response = client.get(f"/sites/zone/{A}", follow_redirects=False)
    assert response.status_code == 303
