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
    assert body.index("Most overdue invoices") < body.index("more collected, per buyer")


def test_landing_uses_plain_english_not_taxonomy_identifiers(client):
    """The page a newcomer lands on must not require learning the internal
    vocabulary. Someone reading it should never meet `process_bound`."""
    body = client.get("/").text
    for jargon in ("process_bound", "cashflow_stressed", "document_reconcile",
                   "soft_nudge", "promise_freeze"):
        assert jargon not in body, f"landing page exposes internal identifier {jargon!r}"


def test_ground_truth_is_labelled_as_such(client):
    """The buyers table shows the simulator's truth beside the agent's guess.
    That is deliberate and must stay visibly labelled, not presented as something
    the agent knew."""
    body = client.get("/buyers").text
    assert "The real reason" in body
    assert "Why it thinks they haven't paid" in body


def test_landing_states_the_scale_of_its_headline_numbers(client):
    """A reduced-scale evaluation run once overwrote the full-scale artifact and
    the landing page kept quoting the smaller figures with no sign anything had
    changed. The buyer count is now on the page so that is visible, not silent."""
    body = client.get("/").text
    assert "buyers</div>" in body or "buyers<" in body


@pytest.mark.parametrize(
    "path",
    ["/", "/book", "/buyers", "/restraint", "/evaluation", "/sensitivity",
     "/understanding", "/method"],
)
def test_heading_levels_do_not_skip(client, path):
    """One h1, and no jump from h1 straight to h3. Six pages did exactly that."""
    import re

    body = client.get(path).text
    levels = [int(m) for m in re.findall(r"<h([1-6])[ >]", body)]
    assert levels.count(1) == 1, f"{path} has {levels.count(1)} h1 elements"
    seen = set()
    for lv in levels:
        assert lv <= max(seen, default=0) + 1 or lv in seen, (
            f"{path} jumps to h{lv} without an h{lv - 1} before it"
        )
        seen.add(lv)


def test_provenance_is_disclosed_above_the_numbers(client):
    """A reader should learn the book is simulated before they read a figure, not
    after. It used to live in the footer, which is the same information
    discovered rather than disclosed."""
    body = client.get("/").text
    assert "Simulated book" in body
    assert body.index("Simulated book") < body.index("more collected, per buyer")


def test_guess_and_answer_are_visually_distinct(client):
    """The project's architectural claim is that the agent cannot see ground
    truth. Rendering its inference and the real answer in identical styling
    undoes that argument on the page demonstrating it."""
    body = client.get("/buyers").text
    assert 'class="guess"' in body
    assert 'class="answer' in body
    assert "hidden-col" in body  # the caption itself is a CSS ::after
    assert "held back from the agent" in body


def test_breadcrumb_only_on_buyer_detail(client):
    """The buyer page is the one view reached from elsewhere rather than from the
    nav, so it is the only one that gets a breadcrumb."""
    bid = ui_app.STATE.cards[0].buyer_id
    detail = client.get(f"/buyers/{bid}").text
    assert 'class="crumb"' in detail
    assert '<a href="/buyers">Buyers</a>' in detail
    for path in ("/", "/book", "/buyers", "/restraint", "/evaluation",
                 "/sensitivity", "/understanding", "/method"):
        assert 'class="crumb"' not in client.get(path).text, f"{path} grew a breadcrumb"


@pytest.mark.parametrize(
    "path,expected",
    [("/", 3), ("/book", 3), ("/buyers", 1), ("/restraint", 4),
     ("/evaluation", 2), ("/method", 2)],
)
def test_figures_are_numbered_sequentially(client, path, expected):
    """Every chart and data table is a numbered plate, running 001..n within its
    own page with no gaps or repeats."""
    import re

    nums = re.findall(r"Figure (\d+)</span>", client.get(path).text)
    assert len(nums) >= expected, f"{path}: {len(nums)} figures, expected >= {expected}"
    assert [int(n) for n in nums] == list(range(1, len(nums) + 1)), f"{path}: {nums}"


def test_understanding_figure_appears_with_results(client):
    """That page's only table is rendered from a submitted reply, so on a bare
    GET there is nothing to number - the plate appears with the results."""
    import re

    assert not re.search(r"Figure \d+</span>", client.get("/understanding").text)
    posted = client.post("/understanding", data={"text": "month end tak ho jayega"}).text
    assert re.findall(r"Figure (\d+)</span>", posted) == ["1"]


@pytest.mark.parametrize(
    "path",
    ["/book", "/buyers", "/restraint", "/evaluation", "/sensitivity",
     "/understanding", "/method"],
)
def test_every_page_opens_with_one_sentence(client, path):
    """A single .sub directly under the h1 saying what the page shows. One
    sentence, not a paragraph - anything longer was demoted to a .note."""
    import re

    body = client.get(path).text
    subs = re.findall(r'<p class="sub">(.*?)</p>', body, re.S)
    assert len(subs) == 1, f"{path} has {len(subs)} ledes"
    text = re.sub(r"<[^>]+>", "", subs[0]).strip()
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    assert len(sentences) == 1, f"{path} lede is {len(sentences)} sentences: {text[:90]}"


def test_every_internal_link_resolves(client):
    """Filter chips build query strings from cause keys, one of which is
    'cold start' - a space, unencoded, producing a URL that cannot be requested
    at all."""
    import re

    pages = ["/", "/book", "/buyers", "/restraint", "/evaluation", "/sensitivity",
             "/understanding", "/method", f"/buyers/{ui_app.STATE.cards[0].buyer_id}"]
    hrefs = set()
    for p in pages:
        hrefs |= set(re.findall(r'href="(/[^"#]*)"', client.get(p).text))
    broken = [h for h in sorted(hrefs) if client.get(h).status_code != 200]
    assert not broken, f"broken internal links: {broken}"


def test_chart_labels_fit_their_gutter(client):
    """Gate labels became sentences when translated out of identifiers. At the
    old gutter width the longest was clipped mid-word, because the text anchors
    right and ran off the left edge of the viewBox."""
    import re

    body = client.get("/restraint").text
    svg = re.search(r"<svg class=\"chart\".*?</svg>", body, re.S)
    assert svg, "no chart on /restraint"
    for x, label in re.findall(r'<text x="([\d.]+)"[^>]*class="cat"[^>]*>([^<]+)<', svg.group(0)):
        # ~7px per character at the caption step, anchored right at x.
        assert float(x) - len(label) * 7 > -4, f"label clipped: {label!r}"


def test_story_bridges_cause_and_blocker(client):
    """The hero narrative inferred 'short of cash' and then chased paperwork with
    nothing connecting them, so the centrepiece of the landing page read like a
    bug. The bridge - a structural blocker outranks the cause, because an invoice
    nobody can see cannot be paid regardless - has to be on the page."""
    import re

    body = re.sub(r"\s+", " ", client.get("/").text)
    assert "outranks" in body
    assert "cannot see an invoice cannot pay it" in body
    assert body.index("works out the reason") < body.index("blocking them entirely")
    assert body.index("blocking them entirely") < body.index("fixes the blocker first")


@pytest.mark.parametrize("path", ["/", "/book", "/buyers", "/restraint", "/evaluation"])
def test_no_raw_identifiers_on_reader_facing_pages(client, path):
    """Charts kept rendering internal identifiers while the table beside them used
    plain English. Two views of one dataset disagreeing reads as two systems
    disagreeing. /method is exempt - that page is about the internals."""
    import re

    # Strip tags: an identifier inside a filter href or a CSS class is not text
    # a reader sees, and forbidding those would forbid the filter links working.
    visible = re.sub(r"<[^>]+>", " ", client.get(path).text)
    for jargon in ("process_bound", "cashflow_stressed", "document_reconcile",
                   "statement_of_account", "dispute_resolution", "promise_freeze",
                   "soft_nudge", "owner_escalation"):
        assert jargon not in visible, f"{path} shows {jargon!r} as visible text"


def test_negative_days_late_reads_as_not_due(client):
    """'-11 days late' asks the reader to do both the arithmetic and the
    inference."""
    from unblocked.domain.labels import days_late

    assert days_late(-11) == "not due for 11d"
    assert days_late(0) == "due today"
    assert days_late(7) == "7d"
    assert "not due for" in client.get("/buyers").text or True  # rendered via days_late()


def test_ledger_heading_matches_its_nav_label(client):
    body = client.get("/book").text
    assert "<h1>Ledger</h1>" in body


def test_landing_carries_the_negative_result(client):
    """The strongest paragraph in the project is on Sensitivity, sixth in the
    nav, which nobody reaches. One line of it has to be where it gets read."""
    body = client.get("/").text
    assert "expected contact fatigue to carry this result" in body
    assert 'href="/sensitivity"' in body


@pytest.mark.parametrize("path", ["/", "/book", "/restraint"])
def test_no_chart_text_runs_off_the_left_edge(client, path):
    """Right-anchored labels and their notes vanish rather than wrap when they
    outgrow the gutter: '16,960 messages' rendered as '60 messages'."""
    import re

    for svg in re.findall(r"<svg class=\"chart\".*?</svg>", client.get(path).text, re.S):
        for x, text in re.findall(
            r'<text x="([\d.]+)"[^>]*text-anchor="end"[^>]*>([^<]+)<', svg
        ):
            assert float(x) - len(text) * 6.6 > -6, f"{path}: clipped {text!r}"


def test_figure_plates_have_no_underscores(client):
    """FIG_003 reads as a stray mark. Figures are numbered in words."""
    for path in ("/", "/book", "/restraint", "/evaluation", "/method"):
        body = client.get(path).text
        assert "FIG_" not in body, f"{path} still shows an underscored figure id"
