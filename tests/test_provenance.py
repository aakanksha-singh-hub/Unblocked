"""The corpus provenance audit.

Exists because a first batch of replies came back with the same thirty-word
sentence appearing verbatim under three different contributors. The audit
encodes that judgement in the repository so it does not have to be remade, by
anyone, under deadline pressure.
"""

from __future__ import annotations

from unblocked.eval.provenance import audit

REAL = [
    ("c1", "i1", "ok sir dekhta hoon"),
    ("c1", "i2", "month end tak ho jayega, abhi thoda tight hai"),
    ("c1", "i3", "2 boxes damaged the, credit note bhejo pehle"),
    ("c2", "i4", "noted"),
    ("c2", "i5", "Payment is in our cycle, will be released on the 10th."),
    ("c2", "i6", "kal transfer kiya tha, UTR check karlo na"),
    ("c3", "i7", "PO copy bhejiye, system me nahi mil raha"),
    ("c3", "i8", "sir abhi cash nahi hai bilkul. thoda time dijiye please"),
    ("c3", "i9", "will check with accounts and revert"),
]

SYNTHETIC = [
    ("c1", "i1", "Hi, we have made a partial payment of roughly half the outstanding "
                 "amount last week and will clear the balance shortly."),
    ("c1", "i2", "Hi, we are currently unable to release this payment as the invoice "
                 "has not been uploaded to our vendor portal."),
    ("c2", "i3", "Hi, we have made a partial payment of roughly half the outstanding "
                 "amount last week and will clear the balance shortly."),
    ("c2", "i4", "Hi, our production team has raised concerns regarding the quality "
                 "of this batch and payment is currently on hold."),
    ("c3", "i5", "Hi, we require the e-way bill and delivery challan copies before "
                 "our accounts team can process this payment."),
    ("c3", "i6", "Hi, this payment is pending approval from our owner who is "
                 "currently travelling and will return next week."),
]


def test_flags_verbatim_text_under_multiple_contributors():
    """The one check that settles it. Two people do not independently produce
    identical thirty-word sentences."""
    rep = audit(SYNTHETIC)
    dupes = next(f for f in rep.findings if f.check == "cross-contributor dupes")
    assert not dupes.passed
    assert dupes.severity == "fail"
    assert rep.failures


def test_synthetic_corpus_is_pilot_only():
    assert audit(SYNTHETIC).verdict.startswith("PILOT ONLY")


def test_natural_corpus_passes():
    rep = audit(REAL)
    assert not rep.failures, [f.detail for f in rep.failures]
    assert not rep.verdict.startswith("PILOT ONLY"), rep.summary()


def test_detects_absent_code_switching():
    english_only = [(f"c{i}", f"i{i}", "We will process this payment shortly.") for i in range(4)]
    rep = audit(english_only)
    assert not next(f for f in rep.findings if f.check == "code-switching").passed


def test_detects_uniform_voice_length():
    """Different people write at different lengths. Near-identical per-contributor
    means across a whole panel is the strongest single tell that one hand wrote
    all of it."""
    uniform = [
        (f"c{c}", f"i{c}{k}", "We will be releasing this payment after the internal approval completes.")
        for c in range(4)
        for k in range(4)
    ]
    rep = audit(uniform)
    assert not next(f for f in rep.findings if f.check == "distinct voices").passed


def test_detects_missing_short_replies():
    rep = audit([(f"c{i}", f"i{i}", "We will process this payment after review completes soon.") for i in range(4)])
    assert not next(f for f in rep.findings if f.check == "has short replies").passed


def test_empty_corpus_does_not_crash():
    assert audit([]).n == 0


def test_summary_is_human_readable():
    text = audit(SYNTHETIC).summary()
    assert "CORPUS PROVENANCE" in text and "verdict" in text
