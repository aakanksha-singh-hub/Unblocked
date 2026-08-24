"""Generate elicitation scenario sheets for the reply corpus.

The whole design problem here is describing a *circumstance* without naming the
*intent*. "You intend to pay after your GST filing clears" is a circumstance -
the contributor decides whether that comes out as a promise with a date, a vague
deflection, or a request for time. "Make a promise to pay" would hand them the
label and the resulting corpus would measure nothing.

Scenarios also deliberately do not describe the tone to use, and never suggest
Hinglish explicitly beyond the general instruction, so register variation comes
from the contributor rather than from us.

Usage:
    python scripts/elicit.py --contributors 12 --per-contributor 14 --out data/corpus/sheets
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

CONSENT = """\
Thanks for helping with this.

This is a student project about how businesses reply to payment reminders. Your
replies will be published as part of an open dataset used to test whether AI can
correctly understand messages like these.

Please do NOT include: real company names, real people's names, real amounts from
actual invoices, real UTR or transaction numbers, or text copied from a real
conversation. Make it up. Made-up is what we need.

Write the way you would actually write - WhatsApp style, short forms, Hinglish,
typos, no punctuation, whatever is natural for you. Please don't clean it up or
make it formal on our account; a corpus of tidy English would be useless.

You can skip any scenario you don't want to answer.
"""

# Circumstances only. No scenario names an intent, a tone, or a message type.
SCENARIOS: list[str] = [
    # --- money exists, timing is the issue ---
    "Your company pays all suppliers in one batch on the 10th of each month. This bill missed the last batch. The supplier has messaged asking where the payment is.",
    "You will have money after a large customer of yours pays you, which you expect sometime near the end of the month. The supplier is asking for an update.",
    "You are waiting for your GST filing to be done before releasing payments this month. The supplier has followed up for the second time.",
    "Your owner signs off on all payments above a certain amount and he is travelling until next week. The supplier wants to know when it will be released.",
    "You genuinely forgot about this bill. It is a small amount and you can pay it quickly. The supplier has just messaged.",
    "Diwali is coming and your office will be shut for a week. You plan to clear pending bills after reopening. The supplier is asking.",
    # --- something is wrong with the goods or paperwork ---
    "Two of the cartons in the last delivery arrived crushed and you had to reject them. Nobody has sent you a corrected bill. The supplier is asking for full payment.",
    "The rate on the bill is higher than what was agreed in the purchase order. The supplier is chasing payment.",
    "You received less material than what the bill says. The supplier is following up on the full amount.",
    "The GST number printed on the bill is wrong, so your accounts team cannot process it. The supplier is asking why payment is delayed.",
    "The quality of this batch was not up to standard and your production team has complained. You have not paid. The supplier has messaged.",
    # --- the invoice never properly arrived ---
    "Your company requires all supplier bills to be uploaded to a vendor portal. This one is not showing up there. The supplier says they sent it by email.",
    "Your accounts team cannot find the purchase order number for this bill, so it is stuck. The supplier is asking about payment.",
    "The goods receipt note has not been entered by your stores team yet, so the bill cannot move forward. The supplier is following up.",
    "You need the e-way bill and delivery challan copies to process this. You don't have them. The supplier is asking for payment.",
    # --- payment already made or partly made ---
    "You paid this bill a few days ago by bank transfer. The supplier seems not to have noticed and is asking again.",
    "You paid roughly half of what is owed last week and plan to pay the rest later. The supplier is asking for the full amount.",
    "Your bank shows the transfer went out but the supplier says it has not arrived. They are chasing you.",
    # --- genuine inability ---
    "Business has been very slow for several months and you honestly do not have the cash right now. The supplier is asking for payment.",
    "Your own customers owe you a lot of money and have not paid, so you cannot pay your suppliers either. The supplier is following up.",
    "You could manage the payment if you were allowed to split it over a few months, but not in one go. The supplier is asking for the whole amount.",
    # --- deprioritising ---
    "This is a small supplier and you have bigger payments to worry about this month. You are not planning to pay them yet. They have messaged you again.",
    "You have been putting off this supplier for a while. They have now sent a firmer message mentioning the agreed payment terms.",
    "You have received a formal-sounding notice from this supplier mentioning legal provisions about delayed payment to small enterprises.",
    # --- ambiguous by design; these become the `hard` subset ---
    "You are not sure whether this bill has been paid or not and you need to check with your accounts person. The supplier is asking.",
    "You have no particular reason for not paying and no clear plan for when you will. The supplier has messaged asking for an update.",
    "Someone else in your office handles this supplier and you are just replying because they messaged your number.",
    "You have been told by your manager not to release this payment but you have not been told why. The supplier is asking.",
]

CONTEXT_VARIANTS = [
    "The supplier has messaged you once before about this.",
    "This is the first time they have contacted you about it.",
    "They have been following up regularly for over a month now.",
    "You have a long-standing relationship with this supplier.",
    "You have only recently started buying from them.",
    "The bill is about three weeks overdue.",
    "The bill is more than three months overdue.",
    "",
]


def build_sheets(n_contributors: int, per_contributor: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    sheets = []
    for c in range(n_contributors):
        pool = SCENARIOS[:]
        rng.shuffle(pool)
        items = []
        for k in range(per_contributor):
            base = pool[k % len(pool)]
            ctx = rng.choice(CONTEXT_VARIANTS)
            items.append(
                {
                    "item_id": f"c{c + 1:02d}_i{k + 1:02d}",
                    "scenario": (base + " " + ctx).strip(),
                    "reply": "",
                }
            )
        sheets.append({"contributor": f"c{c + 1:02d}", "consent": CONSENT, "items": items})
    return sheets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contributors", type=int, default=12)
    ap.add_argument("--per-contributor", type=int, default=14)
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument("--out", type=Path, default=Path("data/corpus/sheets"))
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    sheets = build_sheets(args.contributors, args.per_contributor, args.seed)

    for sheet in sheets:
        (args.out / f"{sheet['contributor']}.json").write_text(
            json.dumps(sheet, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        lines = [CONSENT, "", "=" * 70, ""]
        for it in sheet["items"]:
            lines += [f"[{it['item_id']}]", it["scenario"], "", "Your reply:", "", "-" * 70, ""]
        (args.out / f"{sheet['contributor']}.txt").write_text("\n".join(lines), encoding="utf-8")

    total = args.contributors * args.per_contributor
    print(f"{len(sheets)} sheets -> {args.out}  ({total} items if all returned)")
    print("Send the .txt files. Collect replies back into the matching .json.")


if __name__ == "__main__":
    main()
