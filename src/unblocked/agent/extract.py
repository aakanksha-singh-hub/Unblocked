"""Turning a buyer's reply into structured state.

Two implementations behind one protocol:

- `RuleExtractor` - keyword and regex. Fast, deterministic, and used for every
  simulation run so that the 180-day loop over 728 buyers does not require
  hundreds of thousands of model calls. It is a *baseline*, and it is evaluated
  as one: the extraction study reports it alongside the model so the reader can
  see what the model is actually buying.
- `LLMExtractor` - the model path, used on the externally elicited corpus and in
  the live demo.

Both are scored on the same held-out corpus in `docs/EXTRACTION_PROTOCOL.md`.
Scoring either of them on simulator-generated text would measure template
inversion, and `tests/test_no_template_leak.py` prevents it.

The reason this layer earns a model at all: the rule extractor below is roughly
120 lines of patterns and it will fail on the first reply that says something
its author did not anticipate. That is not a fixable deficiency - it is what
rules are.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Protocol, runtime_checkable

from ..domain.enums import ReplyIntent
from ..domain.models import ExtractedReply, InboundMessage
from ..domain.money import Paise
from .dates import resolve


@runtime_checkable
class ReplyExtractor(Protocol):
    name: str

    def extract(self, message: InboundMessage, as_of: date) -> ExtractedReply: ...


# ---------------------------------------------------------------------------

_UTR = re.compile(r"\b((?:UTR|RRN|REF|TXN)[\s:#-]*)?([A-Z]{0,4}\d{9,22})\b", re.I)
_AMOUNT = re.compile(
    r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d{1,2})?)|([\d,]{4,})\s*(?:rs|rupees|/-)", re.I
)

_DISPUTE = [
    (r"damag|toota|tuta|broken|kharab", "damage"),
    (r"short\s*(delivery|supply)|kam\s*(aaya|mila|material)|less\s*(quantity|material)", "short_delivery"),
    (r"rate\s*(mismatch|galat|zyada|different)|price\s*(wrong|mismatch)|po\s*me.*kam", "rate_mismatch"),
    (r"quality|defect|ghatiya|sub\s*standard", "quality"),
    (r"gst\s*(number|no|galat|wrong|mismatch)|gstin", "gst_mismatch"),
]
_DOCS = [
    (r"\bpo\b|purchase\s*order", "purchase_order"),
    (r"challan|delivery\s*note|\bdc\b", "delivery_challan"),
    (r"e-?way", "eway_bill"),
    (r"\bgrn\b|goods\s*receipt", "grn"),
    (r"portal|upload", "portal_upload"),
    (r"invoice\s*copy|bill\s*copy|soft\s*copy", "invoice_copy"),
]

_HARDSHIP = r"cash\s*nahi|paisa\s*nahi|no\s*cash|cannot\s*pay|nahi\s*de\s*paunga|nahi\s*de\s*payenge|majboori|business\s*(slow|down)|market\s*down|tight\s*hai|part\s*payment|instal?ment|thoda\s*time"
_PROMISE = r"ho\s*jayega|kar\s*denge|kar\s*dunga|release\s*kar|transfer\s*kar|clear\s*kar|process\s*hoga|pay\s*kar|will\s*(pay|clear|release|process)|de\s*denge|bhej\s*denge"
_CLAIM = r"kar\s*diya|ho\s*chuka|already\s*paid|paid\s*(hai|tha|kar)|transfer\s*(ho\s*chuka|kiya|kar\s*diya)|released?\s*(on|the)|bhej\s*diya|utr|rrn"
_DEFLECT = r"payment\s*cycle|cycle\s*me|approval|management|accounts\s*(dept|department|dekh)|process\s*me|run\s*me|under\s*process|pending\s*(hai|with)"
_REFUSE = r"nahi\s*(hoga|ho\s*payega|karenge)|not\s*possible|baad\s*me\s*(dekh|baat)|abhi\s*nahi"
_ACK = r"^\s*(ok|okay|noted|theek|thik|received|sure|ji|haan|yes|k)\b|will\s*(check|revert|see|look)|dekh(ta|te)\s*(hoon|hain)|check\s*kar"


def _find_amount(text: str) -> Paise | None:
    m = _AMOUNT.search(text)
    if not m:
        return None
    raw = (m.group(1) or m.group(2) or "").replace(",", "")
    try:
        return Paise(int(round(float(raw) * 100)))
    except ValueError:
        return None


def _find_utr(text: str) -> str | None:
    m = _UTR.search(text)
    if not m:
        return None
    ref = m.group(2)
    # A bare 4-6 digit number is an amount or a date, not a bank reference.
    return ref if len(ref) >= 9 else None


class RuleExtractor:
    """Pattern-based baseline. Deterministic, fast, and brittle by nature."""

    name = "rules"

    def extract(self, message: InboundMessage, as_of: date) -> ExtractedReply:
        text = message.body
        low = text.lower()

        dispute_kind = next((k for pat, k in _DISPUTE if re.search(pat, low)), None)
        docs = [k for pat, k in _DOCS if re.search(pat, low)]
        utr = _find_utr(text)
        amount = _find_amount(text)

        # Priority order matches the annotation codebook, so the rule baseline
        # and the human labels are resolving ties the same way. Comparing them
        # under different tie-breaks would make the gap between them
        # uninterpretable.
        if dispute_kind:
            intent = ReplyIntent.DISPUTE
        elif re.search(_CLAIM, low) and (utr or re.search(r"paid|kar\s*diya|transfer", low)):
            intent = ReplyIntent.PAYMENT_CLAIM
        elif re.search(_HARDSHIP, low):
            intent = ReplyIntent.HARDSHIP
        elif re.search(_PROMISE, low):
            intent = ReplyIntent.PROMISE_TO_PAY
        elif docs:
            intent = ReplyIntent.DOCUMENT_REQUEST
        elif re.search(_DEFLECT, low):
            intent = ReplyIntent.PROCESS_DEFLECTION
        elif re.search(_REFUSE, low):
            intent = ReplyIntent.REFUSAL
        elif re.search(_ACK, low):
            intent = ReplyIntent.ACKNOWLEDGEMENT
        else:
            intent = ReplyIntent.UNCLEAR

        promised_raw = None
        promised = None
        was_relative = False
        if intent in (ReplyIntent.PROMISE_TO_PAY, ReplyIntent.PROCESS_DEFLECTION, ReplyIntent.HARDSHIP):
            promised_raw = self._date_phrase(text)
            if promised_raw:
                promised, was_relative = resolve(promised_raw, as_of)

        # Confidence is a crude proxy - how many independent cues fired - and is
        # presented as such. It is not calibrated, and the report says so.
        cues = sum(
            bool(x) for x in (dispute_kind, utr, amount, docs, promised, intent != ReplyIntent.UNCLEAR)
        )
        confidence = 0.0 if intent is ReplyIntent.UNCLEAR else min(0.95, 0.45 + 0.12 * cues)

        return ExtractedReply(
            message_id=message.message_id,
            intent=intent,
            confidence=confidence,
            promised_date_raw=promised_raw,
            promised_date=promised,
            promised_amount=amount if intent is ReplyIntent.PROMISE_TO_PAY else None,
            dispute_kind=dispute_kind,
            disputed_amount=amount if intent is ReplyIntent.DISPUTE else None,
            claimed_utr=utr,
            claimed_amount=amount if intent is ReplyIntent.PAYMENT_CLAIM else None,
            requested_documents=docs,
            evidence_span=text[:160],
            abstained=intent is ReplyIntent.UNCLEAR,
        )

    @staticmethod
    def _date_phrase(text: str) -> str | None:
        """Pull the span most likely to carry the date, so the resolver is not
        handed the whole message and made to guess which number is a date."""
        patterns = [
            r"\b\d{1,2}\s*(?:taarikh|tarikh|tarik)\b[^,.]*",
            r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
            r"month\s*end[^,.]*|mahine?\s*ke?\s*(?:end|akhir)[^,.]*",
            r"\b\d{1,3}\s*[-–]?\s*\d{0,3}\s*(?:din|days?|hafte|weeks?)[^,.]*",
            r"(?:next|agle?)\s*(?:week|hafte|month|mahine)[^,.]*",
            r"(?:is|iss|this)\s*(?:week|hafte)[^,.]*",
            r"(?:gst|diwali|salary|payroll)[^,.]*(?:baad|after)?[^,.]*",
            r"\bkal\b|\baaj\b|tomorrow|today",
        ]
        for p in patterns:
            m = re.search(p, text, re.I)
            if m:
                return m.group(0).strip()
        return None
