"""Every page renders, on real data, with no network.

A dashboard that 500s on one route during a demo is worse than no dashboard, and
these routes touch nearly every part of the system - so this doubles as a
smoke test of the whole stack.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from unblocked.ui import app as ui_app


@pytest.fixture(scope="module")
def client():
    # A small world so the module's one build stays quick.
    ui_app.STATE = ui_app.app_state.build(merchants=2, buyers=25)
    return TestClient(ui_app.app)


@pytest.mark.parametrize(
    "path",
    ["/", "/book", "/buyers", "/restraint", "/evaluation", "/sensitivity",
     "/understanding", "/method"],
)
def test_page_renders(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text[:400]
    assert "<html" in r.text
    assert "Traceback" not in r.text


def test_buyer_detail_renders(client):
    bid = ui_app.STATE.cards[0].buyer_id
    r = client.get(f"/buyers/{bid}")
    assert r.status_code == 200
    assert ui_app.STATE.cards[0].name in r.text


def test_unknown_buyer_is_404_not_500(client):
    assert client.get("/buyers/buy_doesnotexist").status_code == 404


@pytest.mark.parametrize("q", ["?cause=prompt", "?filter=wrong", "?filter=blocked", "?filter=churned"])
def test_buyer_filters(client, q):
    assert client.get(f"/buyers{q}").status_code == 200


def test_extraction_demo_works_offline(client):
    """The rule extractor must answer even with no model reachable."""
    r = client.post("/understanding", data={"text": "month end tak ho jayega"})
    assert r.status_code == 200
    assert "promise_to_pay" in r.text


def test_extraction_demo_survives_empty_input(client):
    assert client.post("/understanding", data={"text": "   "}).status_code == 200


def test_extraction_demo_survives_hostile_input(client):
    """A page that renders untrusted text must escape it."""
    r = client.post("/understanding", data={"text": "<script>alert(1)</script> pay kar diya"})
    assert r.status_code == 200
    assert "<script>alert(1)</script>" not in r.text


def test_no_external_asset_references(client):
    """The dashboard must render with the network off - no CDN, no remote font."""
    for path in ("/", "/evaluation", "/method"):
        body = client.get(path).text
        for marker in ("http://", "https://", "//cdn", "googleapis"):
            assert marker not in body, f"{path} references an external asset: {marker}"


def test_landing_leads_with_the_problem_not_a_number(client):
    """The home page exists for someone who does not know what this is. If it
    opens with a metric it has failed at the only job it has."""
    body = client.get("/").text
    assert "Most overdue invoices" in body
    assert body.index("Most overdue invoices") < body.index("recovered per buyer")


def test_ground_truth_is_labelled_as_such(client):
    """The buyers table shows the simulator's truth beside the agent's guess.
    That is deliberate and must stay visibly labelled, not presented as something
    the agent knew."""
    body = client.get("/buyers").text
    assert "Truth" in body and "Inferred" in body


def test_landing_states_the_scale_of_its_headline_numbers(client):
    """A reduced-scale evaluation run once overwrote the full-scale artifact and
    the landing page kept quoting the smaller figures with no sign anything had
    changed. The buyer count is now on the page so that is visible, not silent."""
    body = client.get("/").text
    assert "buyers, held out" in body
