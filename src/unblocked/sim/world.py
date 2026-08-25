"""Population generation: merchants, buyers, their hidden truth, and the book.

Scale decision worth explaining. A real Priya has perhaps 40-60 active buyers,
so generating one merchant with 400 buyers would be a statistically comfortable
lie. Instead the world is a *portfolio*: several independent merchants at
realistic individual scale. Per-merchant results stay honest about how noisy a
single small book is, and the pooled result has the power needed to report
per-archetype precision and recall with real support.

The split is stratified by archetype and assigned at *buyer* level, so no buyer
appears in both train and holdout - a leak that would be trivially easy to
introduce by splitting on invoices instead.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..domain.enums import BuyerArchetype, Channel
from ..domain.models import Buyer, BuyerTruth, Invoice
from ..domain.money import Paise, rupees
from . import calibration as cal
from . import names


#: Fraction of a merchant's annual revenue attributable to the buyers modelled
#: in this world. The remainder stands for cash sales, one-off customers and
#: accounts too small to chase.
ACTIVE_BOOK_SHARE = 0.75


def _mkid(rng: random.Random, prefix: str) -> str:
    """Deterministic entity id drawn from the world rng.

    The domain models default to uuid4, which is right for runtime records
    but fatal here: an unseeded id makes every generated world unique and
    quietly voids World.fingerprint(). Generation therefore always passes
    ids explicitly.
    """
    return f"{prefix}_{rng.getrandbits(48):012x}"


@dataclass(frozen=True)
class Merchant:
    merchant_id: str
    legal_name: str
    city: str
    state: str
    #: Whether the merchant holds a Udyam registration. Gates the MSMED ladder
    #: for every buyer under them.
    udyam_registered: bool
    #: Annualised revenue, used to size individual invoices sensibly.
    annual_revenue: Paise


@dataclass
class World:
    seed: int
    start_date: date
    horizon_days: int
    merchants: list[Merchant]
    buyers: dict[str, Buyer]
    truth: dict[str, BuyerTruth]
    invoices: dict[str, Invoice]
    buyer_merchant: dict[str, str]
    split: dict[str, str]
    """buyer_id -> 'train' | 'holdout'."""

    #: Invoices issued during the run rather than pre-existing, keyed by the day
    #: they appear. The book is not static; new work keeps being delivered while
    #: old work goes unpaid, which is exactly the bind Priya is in.
    scheduled_invoices: dict[date, list[str]] = field(default_factory=dict)

    def buyers_in(self, split: str) -> list[Buyer]:
        return [b for bid, b in self.buyers.items() if self.split[bid] == split]

    def invoices_for(self, buyer_id: str) -> list[Invoice]:
        return [i for i in self.invoices.values() if i.buyer_id == buyer_id]

    def fingerprint(self) -> str:
        """Content hash of the generated world.

        Printed in every evaluation report. Two runs quoting the same
        fingerprint were scored on the identical book; two runs quoting
        different ones are not comparable, and the report will not pretend
        otherwise.
        """
        payload = {
            "seed": self.seed,
            "start": self.start_date.isoformat(),
            "horizon": self.horizon_days,
            "buyers": sorted(self.buyers),
            "truth": {k: self.truth[k].model_dump(mode="json") for k in sorted(self.truth)},
            "invoices": {
                k: self.invoices[k].model_dump(mode="json") for k in sorted(self.invoices)
            },
            "split": self.split,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Archetype-conditioned truth
# ---------------------------------------------------------------------------


def _draw_truth(rng: random.Random, buyer_id: str, arch: BuyerArchetype, agreed: int) -> BuyerTruth:
    """Hidden parameters for one buyer, conditioned on its archetype.

    The gap between `agreed` terms and `effective_terms_days` is where the
    project's whole problem lives: the aging report measures against the former
    and the buyer pays on the latter, so 'overdue' and 'late' are not the same
    word.
    """
    match arch:
        case BuyerArchetype.PROMPT:
            return BuyerTruth(
                buyer_id=buyer_id,
                archetype=arch,
                effective_terms_days=agreed + rng.randint(-3, 4),
                promise_reliability=rng.uniform(0.88, 0.98),
                contact_responsiveness=rng.uniform(0.98, 1.05),
                relationship_budget=rng.randint(70, 110),
            )
        case BuyerArchetype.PROCESS_BOUND:
            # Terms are whatever the buyer's AP policy says, not what was agreed.
            return BuyerTruth(
                buyer_id=buyer_id,
                archetype=arch,
                ap_cycle_day=rng.choice([5, 7, 10, 10, 15, 20, 25]),
                effective_terms_days=rng.choice([45, 60, 60, 75, 90]),
                promise_reliability=rng.uniform(0.80, 0.95),
                # ~1.0: this is the archetype that makes chasing measurably futile.
                contact_responsiveness=rng.uniform(0.97, 1.06),
                relationship_budget=rng.randint(60, 100),
            )
        case BuyerArchetype.CASHFLOW_STRESSED:
            return BuyerTruth(
                buyer_id=buyer_id,
                archetype=arch,
                effective_terms_days=agreed + rng.randint(15, 55),
                promise_reliability=rng.uniform(0.35, 0.70),
                contact_responsiveness=rng.uniform(1.25, 1.70),
                lump_sum_capacity=rng.uniform(0.75, 1.0),
                relationship_budget=rng.randint(45, 85),
            )
        case BuyerArchetype.DISPUTER:
            return BuyerTruth(
                buyer_id=buyer_id,
                archetype=arch,
                effective_terms_days=agreed + rng.randint(5, 25),
                promise_reliability=rng.uniform(0.70, 0.92),
                contact_responsiveness=rng.uniform(1.0, 1.25),
                relationship_budget=rng.randint(40, 80),
            )
        case BuyerArchetype.AVOIDER:
            return BuyerTruth(
                buyer_id=buyer_id,
                archetype=arch,
                effective_terms_days=agreed + rng.randint(60, 150),
                promise_reliability=rng.uniform(0.10, 0.35),
                contact_responsiveness=rng.uniform(0.95, 1.15),
                # High tolerance: an avoider is not the one who ends the
                # relationship, which is precisely why they can behave this way.
                relationship_budget=rng.randint(90, 140),
            )
        case BuyerArchetype.DISTRESSED:
            return BuyerTruth(
                buyer_id=buyer_id,
                archetype=arch,
                effective_terms_days=agreed + rng.randint(45, 120),
                promise_reliability=rng.uniform(0.30, 0.60),
                contact_responsiveness=rng.uniform(1.0, 1.30),
                # Cannot clear the balance in one go however hard they are asked.
                lump_sum_capacity=rng.uniform(0.15, 0.45),
                relationship_budget=rng.randint(35, 70),
            )
    raise AssertionError(f"unhandled archetype {arch}")


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _make_buyer(rng: random.Random, arch: BuyerArchetype) -> tuple[Buyer, BuyerTruth]:
    city, state = names.city(rng)
    coname = names.company(rng)
    contact = names.person(rng)

    # Large, process-bound buyers are the ones that run supplier portals and
    # dictate terms; small ones do not.
    is_large = arch is BuyerArchetype.PROCESS_BOUND and rng.random() < 0.75
    agreed = rng.choice([30, 30, 30, 45, 45, 60]) if is_large else rng.choice([15, 30, 30, 45])

    channels = [Channel.EMAIL]
    if rng.random() < 0.70:
        channels.append(Channel.WHATSAPP)
    if rng.random() < 0.55:
        channels.append(Channel.PHONE)

    # Concentration risk: a few buyers are a frightening share of revenue. This
    # is what makes escalation genuinely expensive rather than theoretically so.
    share = rng.choice(
        [rng.uniform(0.005, 0.02)] * 6 + [rng.uniform(0.02, 0.08)] * 3 + [rng.uniform(0.12, 0.35)]
    )

    buyer = Buyer(
        buyer_id=_mkid(rng, "buy"),
        legal_name=coname,
        trade_name=coname.split()[0],
        city=city,
        state=state,
        gstin=names.gstin(rng, state),
        revenue_share=round(share, 4),
        agreed_terms_days=agreed,
        tenure_months=rng.randint(2, 120),
        ap_contact_name=contact,
        ap_contact_email=names.email(rng, contact, coname),
        ap_contact_phone=names.phone(rng),
        owner_contact_name=names.person(rng) if rng.random() < 0.6 else None,
        reachable_channels=channels,
        uses_ap_portal=is_large and rng.random() < 0.8,
        msmed_eligible=True,  # overwritten per-merchant below
    )
    return buyer, _draw_truth(rng, buyer.buyer_id, arch, agreed)


def _make_invoices(
    rng: random.Random,
    buyer: Buyer,
    truth: BuyerTruth,
    merchant: Merchant,
    start: date,
    horizon: int,
    counter: list[int],
) -> tuple[list[Invoice], dict[date, list[str]]]:
    """Invoices for one buyer: an aged opening book plus new work during the run."""
    n_open = rng.randint(1, 5)
    n_future = rng.randint(0, 4)

    # Annual business done with this buyer, spread over roughly a dozen
    # invoices a year. Everything here is in rupees; conversion to paise happens
    # once, at construction.
    annual_with_buyer = (merchant.annual_revenue / 100) * buyer.revenue_share
    typical_rupees = max(12_000.0, annual_with_buyer / 12)

    out: list[Invoice] = []
    scheduled: dict[date, list[str]] = {}

    def one(issue: date) -> Invoice:
        counter[0] += 1
        amount = rupees(round(rng.uniform(0.45, 1.9) * typical_rupees, -2))
        terms = buyer.agreed_terms_days
        # Acceptance usually follows delivery within a few days; sometimes it is
        # never formally recorded, which weakens the MSMED position later.
        acc = issue + timedelta(days=rng.randint(0, 6)) if rng.random() < 0.82 else None
        portal_ok = True
        if buyer.uses_ap_portal:
            # The silent killer: a fifth of portal invoices never get uploaded.
            portal_ok = rng.random() > 0.20
        return Invoice(
            invoice_id=_mkid(rng, "inv"),
            invoice_number=f"{merchant.merchant_id.upper()}/26-27/{counter[0]:04d}",
            buyer_id=buyer.buyer_id,
            amount=amount,
            issue_date=issue,
            due_date=issue + timedelta(days=terms),
            po_number=f"PO{rng.randint(100000, 999999)}" if rng.random() < 0.85 else None,
            delivery_challan_no=f"DC{rng.randint(10000, 99999)}" if rng.random() < 0.9 else None,
            eway_bill_no=f"{rng.randint(100000000000, 999999999999)}"
            if rng.random() < 0.7
            else None,
            acceptance_date=acc,
            portal_submitted=portal_ok,
        )

    # Opening book: aged backwards from t0, skewed old for slow archetypes.
    max_age = int(truth.effective_terms_days * rng.uniform(1.2, 3.0)) + 20
    for _ in range(n_open):
        issue = start - timedelta(days=rng.randint(5, max(25, max_age)))
        out.append(one(issue))

    # New work delivered during the run.
    for _ in range(n_future):
        d = start + timedelta(days=rng.randint(1, max(1, horizon - 40)))
        inv = one(d)
        out.append(inv)
        scheduled.setdefault(d, []).append(inv.invoice_id)

    return out, scheduled


def generate(
    *,
    seed: int = 20260824,
    n_merchants: int = 14,
    buyers_per_merchant: int = 52,
    start_date: date | None = None,
    horizon_days: int | None = None,
    holdout_frac: float = 0.40,
) -> World:
    """Build a reproducible world. Same seed, same book, byte for byte."""
    rng = random.Random(seed)
    start = start_date or date(2026, 3, 2)
    horizon = horizon_days or int(cal.SIM_HORIZON_DAYS.value)

    mix = cal.archetype_mix()
    arch_list = list(mix)
    arch_w = [mix[a] for a in arch_list]

    merchants: list[Merchant] = []
    buyers: dict[str, Buyer] = {}
    truth: dict[str, BuyerTruth] = {}
    invoices: dict[str, Invoice] = {}
    buyer_merchant: dict[str, str] = {}
    scheduled: dict[date, list[str]] = {}
    by_arch: dict[BuyerArchetype, list[str]] = {a: [] for a in BuyerArchetype}

    for m in range(n_merchants):
        city, state = names.city(rng)
        # Most small suppliers are registered; some are not, and for those the
        # legal ladder simply does not exist. The agent must notice.
        udyam = rng.random() < 0.80
        merchant = Merchant(
            merchant_id=f"m{m + 1}",
            legal_name=names.company(rng),
            city=city,
            state=state,
            udyam_registered=udyam,
            annual_revenue=rupees(rng.uniform(3.5e7, 2.2e8)),
        )
        merchants.append(merchant)
        counter = [0]

        # Build the full buyer set for this merchant first. Revenue shares are
        # drawn independently and therefore do not sum to anything meaningful,
        # so they are normalised across the merchant's book *before* a single
        # invoice is sized from them. Skipping this step inflates the generated
        # book by roughly the number of buyers, which is the kind of error that
        # survives right up until someone checks whether a merchant's
        # receivables exceed its revenue.
        cohort: list[tuple[Buyer, BuyerTruth, BuyerArchetype]] = []
        for _ in range(buyers_per_merchant):
            arch = rng.choices(arch_list, weights=arch_w, k=1)[0]
            buyer, btruth = _make_buyer(rng, arch)
            buyer.msmed_eligible = udyam
            cohort.append((buyer, btruth, arch))

        # Normalise to ACTIVE_BOOK_SHARE rather than 1.0: not all of a
        # merchant's revenue sits with the buyers modelled here, and leaving
        # headroom keeps concentration realistic rather than forcing the shares
        # to tile the whole business.
        raw_total = sum(b.revenue_share for b, _, _ in cohort) or 1.0
        scale = ACTIVE_BOOK_SHARE / raw_total
        for buyer, _, _ in cohort:
            buyer.revenue_share = round(buyer.revenue_share * scale, 6)

        for buyer, btruth, arch in cohort:
            buyers[buyer.buyer_id] = buyer
            truth[buyer.buyer_id] = btruth
            buyer_merchant[buyer.buyer_id] = merchant.merchant_id
            by_arch[arch].append(buyer.buyer_id)

            invs, sched = _make_invoices(rng, buyer, btruth, merchant, start, horizon, counter)
            for inv in invs:
                invoices[inv.invoice_id] = inv
            for d, ids in sched.items():
                scheduled.setdefault(d, []).extend(ids)

    # Stratified split at buyer level. Stratifying matters most for the rare
    # archetypes: an unstratified 40% draw can easily leave four DISTRESSED
    # buyers in holdout, and a recall figure computed on four buyers is theatre.
    split: dict[str, str] = {}
    split_rng = random.Random(seed ^ 0x5F5F)
    for arch, ids in by_arch.items():
        ids = sorted(ids)
        split_rng.shuffle(ids)
        n_hold = round(len(ids) * holdout_frac)
        for i, bid in enumerate(ids):
            split[bid] = "holdout" if i < n_hold else "train"

    return World(
        seed=seed,
        start_date=start,
        horizon_days=horizon,
        merchants=merchants,
        buyers=buyers,
        truth=truth,
        invoices=invoices,
        buyer_merchant=buyer_merchant,
        split=split,
        scheduled_invoices=scheduled,
    )
