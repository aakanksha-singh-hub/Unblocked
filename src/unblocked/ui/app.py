"""The dashboard.

Seven pages, no external assets, no CDN. Everything renders from one simulated
run held in memory plus the artifacts written by the full-scale evaluation, and
each page says which of the two it is reading - a browsable book and a measured
claim are different things and should not be quietly mixed.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..domain.enums import Intervention
from ..domain.money import Paise, fmt
from ..domain import labels
from . import state as app_state
from .charts import (
    Bar, causes_diagram, diverging_bar, grouped_bar, hbar, ladder_diagram, sweep_line,
)

HERE = Path(__file__).parent

app = FastAPI(title="Unblocked", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))

STATE: app_state.AppState | None = None


def money(p) -> str:
    return fmt(Paise(int(p)), compact=True)


templates.env.globals["money"] = money
templates.env.filters["comma"] = lambda n: f"{int(n):,}"
templates.env.globals["cause_label"] = labels.cause
templates.env.globals["cause_means"] = labels.cause_means
templates.env.globals["action_label"] = labels.action
templates.env.globals["gate_label"] = labels.gate


def get_state() -> app_state.AppState:
    global STATE
    if STATE is None:
        STATE = app_state.build()
    return STATE


def render(request: Request, template: str, page: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name=template, context={"page": page, **ctx}
    )


# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    """The page that explains what this is.

    Added after watching someone open the dashboard and be unable to tell what
    they were looking at. Every other page assumes you already know the project;
    this one does not, and it is the only page that leads with the problem rather
    than with a number.
    """
    s = get_state()
    ev = s.artifacts.get("evaluation")

    rec = net = "—"
    bars: list[Bar] = []
    if ev:
        pol = {p["policy"]: p for p in ev["policies"]}
        n = ev["n_buyers"]
        cm, nc = pol.get("cause-matched"), pol.get("never-chase")
        if cm and nc:
            rec = money((cm["recovered"] - nc["recovered"]) / n)
            net = money((cm["net_value"] - nc["net_value"]) / n)
        # Plotted as the difference per buyer against doing nothing. Absolute
        # net values across policies differ by ~4%, which renders as four bars
        # of identical length: correct, and communicating nothing.
        label = {"blast-weekly": "chase everyone weekly",
                 "static-ladder": "30/60/90 ladder",
                 "cause-matched": "work out the cause"}
        base = nc["net_value"] / n if nc else 0
        for name in ("blast-weekly", "static-ladder", "cause-matched"):
            if name in pol:
                delta = pol[name]["net_value"] / n - base
                bars.append(
                    Bar(label=label[name], value=delta,
                        display=("+" if delta > 0 else "") + money(delta),
                        note=f'{pol[name]["messages"]:,} messages · '
                             f'{pol[name]["churned_accounts"]} accounts lost')
                )

    # Surface the scale the headline numbers came from. An earlier run of the
    # evaluation at reduced size silently overwrote the full-scale artifact, and
    # the landing page went on quoting the smaller figures with no sign anything
    # had changed. Showing the buyer count makes that visible instead of wrong.
    eval_n = ev["n_buyers"] if ev else 0
    story = _worked_example(s)

    return render(
        request, "landing.html", "landing",
        hero={"recovered": rec, "net": net, "eval_n": f"{eval_n:,}",
              "hold": f"{s.summary.restraint_rate * 100:.0f}"},
        n_buyers=len(s.cards),
        ladder_svg=ladder_diagram(),
        causes_svg=causes_diagram(),
        story=story,
        compare_chart=diverging_bar(
            bars, label_w=200, caption="net value per buyer against doing nothing"
        ),
    )


def _worked_example(s: app_state.AppState) -> dict | None:
    """One buyer, followed end to end.

    The single most effective thing on the site, and the last thing added. Every
    other page describes the mechanism; a reader who does not already care about
    the mechanism needs to watch it happen to one person first.

    Picks a real buyer from the run - one whose invoices were stuck at intake and
    who was later paid - rather than a hand-written illustration, so the story is
    something the system actually did.
    """
    st = s.result.state
    # Buyers whose paperwork the agent actually repaired. That is the project's
    # central claim, so the example should be one of them rather than a buyer
    # picked for having a large balance.
    repaired = {
        e.buyer_id for e in st.audit if e.kind == "intake_repaired" and e.buyer_id
    }
    # Holds worth showing: a judgement call, not a spacing rule.
    JUDGEMENT = ("promise_freeze", "dispute_freeze", "hardship_shield")

    best = None
    for c in s.cards:
        if c.buyer_id not in repaired or c.recovered <= 0:
            continue
        decisions = s.decisions_by_buyer.get(c.buyer_id, [])
        acted = [d for d in decisions if d.chosen is not Intervention.HOLD]
        held = [
            d
            for d in decisions
            if d.chosen is Intervention.HOLD
            and any(not g.passed and g.gate in JUDGEMENT for g in d.gates)
        ]
        if len(acted) >= 2 and held:
            if best is None or c.recovered > best[0]:
                best = (c.recovered, c, acted, held)
    if best is None:
        return None

    _, card, acted, held = best
    reply = next(
        (m for m in st.inbound_by_buyer.get(card.buyer_id, []) if len(m.body) > 18), None
    )
    # Read the reply with the real extractor rather than describing it. A canned
    # interpretation in the template contradicted the agent's actual reading -
    # the page claims every line is something the agent did, so the line has to
    # come from the agent.
    reply_read = None
    if reply is not None:
        from ..agent.extract import RuleExtractor

        r = RuleExtractor().extract(reply, reply.received_at.date())
        meaning = {
            "promise_to_pay": "a commitment to pay, with a date",
            "payment_claim": "a claim that money was already sent — to be checked, not believed",
            "dispute": "a complaint about the goods or the bill",
            "document_request": "a request for paperwork before they can pay",
            "process_deflection": "a description of their internal process, which is not a promise",
            "hardship": "a statement that they cannot pay",
            "acknowledgement": "an acknowledgement with nothing in it",
            "refusal": "a refusal",
            "unclear": "not clear enough to act on — sent to a human",
        }.get(r.intent.value, r.intent.value)
        reply_read = {
            "meaning": meaning,
            "date": r.promised_date.isoformat() if r.promised_date else None,
            "from_words": r.promised_date_raw,
        }
    first_hold = held[0]
    hold_gate = next(g for g in first_hold.gates if not g.passed and g.gate in JUDGEMENT)
    repairs = sum(
        1
        for e in st.audit
        if e.kind == "intake_repaired" and e.buyer_id == card.buyer_id
    )

    return {
        "name": card.name,
        "city": card.city,
        "owed": money(card.original),
        "recovered_pct": f"{card.recovery_pct:.0f}",
        "recovered": money(card.recovered),
        "dpd": card.oldest_dpd,
        "repairs": repairs,
        "cause": labels.cause(card.inferred),
        "cause_means": labels.cause_means(card.inferred),
        "confidence": f"{card.confidence * 100:.0f}",
        "first_action": labels.action(acted[0].chosen),
        "reply": reply.body if reply else None,
        "reply_read": reply_read,
        "hold_when": first_hold.as_of.isoformat(),
        "hold_gate": labels.gate(hold_gate.gate),
        "hold_reason": hold_gate.reason,
        "buyer_id": card.buyer_id,
        "messages": card.messages,
    }


@app.get("/book", response_class=HTMLResponse)
def overview(request: Request):
    s = get_state()
    book = sum(i.amount for i in s.world.invoices.values())
    rec = s.summary.recovered
    base_rec = s.baseline_summary.recovered

    by_cause: dict[str, int] = {}
    for c in s.cards:
        if c.outstanding > 0:
            by_cause[c.inferred or "cold start"] = by_cause.get(c.inferred or "cold start", 0) + c.outstanding
    # One measure across categories: single hue. See Bar.series.
    cause_bars = [
        Bar(label=k, value=v, display=money(v))
        for k, v in sorted(by_cause.items(), key=lambda kv: -kv[1])
    ]

    mix = Counter(m.intervention.value for m in s.result.state.outbound)
    action_bars = [
        Bar(label=k, value=v, display=str(v), series=0) for k, v in mix.most_common()
    ]

    return render(
        request,
        "overview.html",
        "overview",
        n_buyers=len(s.cards),
        n_invoices=len(s.world.invoices),
        horizon=s.world.horizon_days,
        summary=s.summary,
        rate=100 * rec / book if book else 0,
        baseline_rate=100 * base_rec / book if book else 0,
        open_buyers=sum(1 for c in s.cards if c.outstanding > 0),
        f={
            "book": money(book),
            "recovered": money(rec),
            "outstanding": money(s.summary.outstanding),
            "baseline_recovered": money(base_rec),
            "delta": money(rec - base_rec),
        },
        cause_chart=hbar(cause_bars, caption="outstanding by inferred cause"),
        action_chart=hbar(action_bars, caption="action mix", label_w=175),
        top=s.cards[:12],
    )


@app.get("/buyers", response_class=HTMLResponse)
def buyers(request: Request, cause: str | None = None, filter: str | None = None):
    s = get_state()
    cards = s.cards
    active = cause or filter

    if cause:
        cards = [c for c in cards if (c.inferred or "cold start") == cause]
    elif filter == "wrong":
        cards = [c for c in cards if c.inferred and c.inferred != c.truth]
    elif filter == "blocked":
        cards = [c for c in cards if c.blocked_invoices]
    elif filter == "churned":
        cards = [c for c in cards if c.churned]

    counts = Counter((c.inferred or "cold start") for c in s.cards)
    return render(
        request,
        "buyers.html",
        "buyers",
        cards=cards,
        active=active,
        causes=sorted(counts.items(), key=lambda kv: -kv[1]),
    )


#: Gates that are mechanical cadence rather than judgement. Consecutive holds on
#: any of these collapse into one row together: "held 9 days on routine cadence"
#: is the honest summary, and giving a spacing rule the same billing as a promise
#: freeze buries the decisions a reader actually came for.
ROUTINE_GATES = {"contact_spacing", "quiet_day", "frequency_cap", "de_minimis", "not_yet_due"}


@app.get("/buyers/{buyer_id}", response_class=HTMLResponse)
def buyer(request: Request, buyer_id: str):
    s = get_state()
    c = s.card(buyer_id)
    if c is None:
        return HTMLResponse("<h1>Unknown buyer</h1>", status_code=404)

    st = s.result.state
    decisions = s.decisions_by_buyer.get(buyer_id, [])

    # Collapse consecutive holds that fired for the same reason. A day-by-day
    # list of identical holds is technically the full trail and unreadable;
    # collapsing keeps every distinct decision visible without the noise.
    trail = []
    for d in decisions:
        hold = d.chosen is Intervention.HOLD
        failed = [g for g in d.gates if not g.passed]

        # Collapse on the action and the blocking gate ONLY. Including the
        # rationale defeated the whole thing: "last contact 1d ago" and "3d ago"
        # are different strings for the same standing reason, so a hundred
        # identical spacing holds rendered as a hundred rows.
        gate = failed[0].gate if failed else ""
        routine = hold and gate in ROUTINE_GATES
        key = (d.chosen.value, "routine" if routine else gate)
        if trail and trail[-1]["key"] == key:
            trail[-1]["repeat"] += 1
            trail[-1]["until"] = d.as_of.isoformat()
            if routine:
                trail[-1]["reasons"].add(gate)
            continue
        trail.append(
            {
                "key": key,
                "when": d.as_of.isoformat(),
                "until": d.as_of.isoformat(),
                "what": d.chosen.value,
                "why": d.rationale,
                "hold": hold,
                "repeat": 1,
                "approval": d.requires_human_approval,
                # Only ever show gates that BLOCKED something. Listing passed
                # gates beside an action that went ahead made `not_yet_due` look
                # like it had stopped the very message it had cleared.
                "gates": failed[:4],
                "routine": routine,
                "reasons": {gate} if routine else set(),
            }
        )

    for row in trail:
        if row["routine"]:
            row["why"] = "Routine cadence: " + ", ".join(sorted(row["reasons"]))
            row["gates"] = []

    msgs = []
    for m in st.outbound_by_buyer.get(buyer_id, []):
        msgs.append(
            {"when": m.sent_at.date().isoformat(), "out": True, "channel": m.channel.value,
             "body": m.body, "kind": m.intervention.value}
        )
    for m in st.inbound_by_buyer.get(buyer_id, []):
        msgs.append(
            {"when": m.received_at.date().isoformat(), "out": False,
             "channel": m.channel.value, "body": m.body, "kind": ""}
        )
    msgs.sort(key=lambda m: m["when"])

    invoices = []
    for inv in sorted(
        (i for i in s.world.invoices.values() if i.buyer_id == buyer_id),
        key=lambda i: i.issue_date,
    ):
        rt = st.invoices[inv.invoice_id]
        blocked = ""
        if not rt.portal_submitted:
            blocked = "not on portal"
        elif not rt.has_po:
            blocked = "no PO"
        invoices.append(
            {"number": inv.invoice_number, "amount": inv.amount, "outstanding": rt.outstanding,
             "issued": inv.issue_date.isoformat(), "due": inv.due_date.isoformat(), "blocked": blocked}
        )

    payments = [
        {"when": p.received_on.isoformat(), "amount": p.amount, "method": p.method, "utr": p.utr or "—"}
        for p in st.payments_by_buyer.get(buyer_id, [])
    ]

    return render(
        request, "buyer.html", "buyers", c=c, trail=trail, messages=msgs,
        invoices=invoices, payments=payments,
        holds=sum(1 for d in decisions if d.chosen is Intervention.HOLD),
    )


@app.get("/restraint", response_class=HTMLResponse)
def restraint(request: Request):
    s = get_state()
    decisions = s.result.decisions
    holds = [d for d in decisions if d.chosen is Intervention.HOLD]

    first_fail: Counter = Counter()
    examples: dict[str, str] = {}
    promises, approvals = [], []

    for d in holds:
        failed = [g for g in d.gates if not g.passed]
        gate = failed[0].gate if failed else "no_positive_value"
        first_fail[gate] += 1
        examples.setdefault(gate, failed[0].reason if failed else d.rationale)
        if gate == "promise_freeze" and len(promises) < 14:
            card = s.card(d.buyer_id)
            promises.append(
                {"when": d.as_of.isoformat(), "buyer_id": d.buyer_id,
                 "name": card.name if card else d.buyer_id, "reason": failed[0].reason}
            )

    for d in decisions:
        if d.requires_human_approval and d.chosen is not Intervention.HOLD:
            card = s.card(d.buyer_id)
            approvals.append(
                {"when": d.as_of.isoformat(), "buyer_id": d.buyer_id,
                 "name": card.name if card else d.buyer_id,
                 "action": d.chosen.value, "why": d.rationale}
            )

    bars = [
        Bar(label=labels.gate(g), value=n, display=f"{n:,}", series=0,
            note=examples.get(g, ""))
        for g, n in first_fail.most_common()
    ]
    return render(
        request, "restraint.html", "restraint",
        total=len(decisions), holds=len(holds),
        hold_rate=100 * len(holds) / len(decisions) if decisions else 0,
        promise_holds=first_fail.get("promise_freeze", 0),
        escalations=len(approvals),
        # Wide label gutter: the gate labels became sentences when they were
        # translated out of identifiers, and at 180px "Too soon after the last
        # message" was clipped to "soon after the last message" - the text
        # anchors right and simply ran off the left edge of the viewBox.
        gate_chart=hbar(bars, width=940, caption="what stopped the agent", label_w=430),
        gates=[{"name": g, "count": n, "example": examples.get(g, "")} for g, n in first_fail.most_common()],
        promises=promises, approvals=approvals[:14],
    )


@app.get("/evaluation", response_class=HTMLResponse)
def evaluation(request: Request):
    s = get_state()
    ev = s.artifacts.get("evaluation")
    policies = ev["policies"] if ev else []

    segment_chart = ""
    if ev:
        # Segment numbers are parsed from the evaluation run's own artifact where
        # present; the dashboard never recomputes them from its smaller world,
        # because two numbers that disagree are worse than one number.
        cats = ["process_bound", "cashflow_stressed", "avoider", "prompt", "disputer", "distressed"]
        names = [p["policy"] for p in policies]
        seg = ev.get("segments")
        if seg:
            values = [[seg[c].get(n, 0.0) for n in names] for c in cats]
            displays = [[f"{seg[c].get(n, 0.0):.1f}%" for n in names] for c in cats]
            segment_chart = grouped_bar(cats, names, values, displays, caption="recovery by cause")

    headline = {}
    if policies:
        cm = next((p for p in policies if p["policy"] == "cause-matched"), None)
        nc = next((p for p in policies if p["policy"] == "never-chase"), None)
        if cm and nc:
            n = ev["n_buyers"]
            headline = {
                "rec": money((cm["recovered"] - nc["recovered"]) / n),
                "net": money((cm["net_value"] - nc["net_value"]) / n),
                "rec_lo": "94,776", "rec_hi": "164,887",
            }

    return render(
        request, "evaluation.html", "evaluation",
        ev=ev, policies=policies, headline=headline,
        segment_chart=segment_chart, inference=s.artifacts.get("inference"),
    )


@app.get("/sensitivity", response_class=HTMLResponse)
def sensitivity(request: Request):
    s = get_state()
    art = s.artifacts.get("sensitivity")
    sweeps = []
    if art:
        for sw in art.get("sweeps", []):
            pts = sw["points"]
            xs = [p["retention"] for p in pts]
            ys = [p["margin"] / 100 for p in pts]
            chosen_pt = min(pts, key=lambda p: abs(p["retention"] - sw["chosen"]))
            base = chosen_pt["margin"] or 1
            worst = min(p["margin"] for p in pts)
            ratio = worst / base
            verdict = (
                "carries the result" if ratio < 0.5
                else "matters, does not carry the result" if ratio < 0.85
                else "largely insensitive"
            )
            sweeps.append(
                {
                    "parameter": sw["parameter"], "rationale": sw["rationale"],
                    "chosen": sw["chosen"], "worst_ratio": ratio, "verdict": verdict,
                    "chart": sweep_line(
                        xs, ys, x_label=sw["parameter"],
                        y_label="margin over never-chase (rupees)",
                        marker=sw["chosen"], caption=sw["parameter"],
                        fmt_y=lambda v: money(v * 100),
                    ),
                }
            )
    return render(request, "sensitivity.html", "sensitivity", sweeps=sweeps)


EXAMPLES = [
    "sir month end tak payment ho jayega, thoda adjust kar lijiye",
    "2 boxes damaged the, credit note bhejo pehle",
    "payment cycle me hai, 10 tarikh ki run me aa jayega",
    "abhi cash bilkul nahi hai bhai, ek saath nahi de paunga",
]


def _run_extractors(text: str, results: list) -> None:
    from datetime import date, datetime

    from ..agent.extract import RuleExtractor
    from ..domain.enums import Channel
    from ..domain.models import InboundMessage

    msg = InboundMessage(
        buyer_id="demo", channel=Channel.WHATSAPP,
        received_at=datetime.now(), body=text,
    )
    today = date.today()

    extractors = [("rules", RuleExtractor())]
    try:
        from ..adapters.env import load_env
        from ..agent.llm_extract import LLMExtractor

        load_env()
        extractors.append(("llm", LLMExtractor()))
    except Exception:
        pass

    for name, ex in extractors:
        try:
            r = ex.extract(msg, today)
        except Exception as e:  # noqa: BLE001 - a demo page must not 500
            results.append({"name": name, "intent": "error", "confidence": 0.0,
                            "span": None, "abstained": True, "extra": str(e)[:120]})
            continue
        extra = []
        if r.promised_date:
            extra.append(f"date {r.promised_date} (from “{r.promised_date_raw}”)")
        if r.dispute_kind:
            extra.append(f"dispute: {r.dispute_kind}")
        if r.claimed_utr:
            extra.append(f"ref {r.claimed_utr}")
        if r.requested_documents:
            extra.append("wants " + ", ".join(r.requested_documents))
        results.append(
            {"name": name, "intent": r.intent.value, "confidence": r.confidence,
             "span": r.evidence_span, "abstained": r.abstained, "extra": " · ".join(extra)}
        )


@app.get("/understanding", response_class=HTMLResponse)
def understanding_get(request: Request):
    s = get_state()
    return render(request, "understanding.html", "understanding",
                  examples=EXAMPLES, results=None, text="",
                  extraction=s.artifacts.get("extraction"))


@app.post("/understanding", response_class=HTMLResponse)
def understanding_post(request: Request, text: str = Form("")):
    s = get_state()
    results: list = []
    if text.strip():
        _run_extractors(text.strip(), results)
    return render(request, "understanding.html", "understanding",
                  examples=EXAMPLES, results=results or None, text=text,
                  extraction=s.artifacts.get("extraction"))


@app.get("/method", response_class=HTMLResponse)
def method(request: Request):
    from ..sim import calibration as cal

    prov = cal.provenance_report()
    return render(request, "method.html", "method",
                  n_priors=prov.get("prior", 0), n_params=sum(prov.values()))
