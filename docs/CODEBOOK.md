# Annotation codebook

For the two annotators. Work independently. Do not discuss any item until both
of you have finished the whole set.

You will see a **scenario** (what the person was told) and their **reply**.
Label the reply, not the scenario. If the scenario says they cannot pay but the
reply says "will clear it Tuesday", the label comes from the reply.

## The one rule that matters most

**Label what was said, not what you think was meant.** If a reply is vague, the
correct label is the vague one. Do not reward the writer for an intention you
inferred. If you find yourself reasoning "well, they probably mean...", mark it
`ambiguous`.

## Intents — pick exactly one

**`promise_to_pay`** — commits to paying, with a time reference of any precision.
- Yes: "15 tarikh tak ho jayega", "month end tak", "next week clear kar denge"
- No: "will check and revert" (no commitment) → `acknowledgement`
- No: "payment cycle me hai, 10th ko run hoti hai" → `process_deflection`
- The distinction from deflection: a promise is *they* undertaking to act. A
  deflection describes a process that will or won't produce payment on its own.

**`payment_claim`** — asserts payment has already been made, fully or partly.
- Yes: "kal hi transfer kiya, UTR 12345", "half paid last week"
- Record the UTR/reference if present, and the amount if stated.

**`dispute`** — withholds against a commercial or documentation problem with the
goods, the rate, or the bill itself.
- Yes: "2 boxes damaged the, credit note bhejo", "rate PO se zyada hai"
- Yes: "GST number galat hai invoice pe" — a bill that cannot be processed as
  issued is a dispute, not a document request.
- No: "PO copy bhejiye" → `document_request` (nothing is wrong; something is
  missing)
- Record the disputed amount if stated.

**`document_request`** — asks for paperwork or an action from the supplier before
payment can proceed. Nothing is *wrong*; something is *absent*.
- Yes: "challan bhej dijiye", "portal pe upload karein", "GRN pending hai"

**`process_deflection`** — points at an internal process, cycle, or approval as
the reason, without personally committing.
- Yes: "payment cycle me hai", "approval management ke paas hai", "accounts dekh
  raha hai"
- This is the hardest class. It is the honest truth from a large buyer on a
  fixed cycle and a brush-off from someone avoiding you, and **the reply alone
  often cannot tell you which.** That is fine. Label the surface form. It is not
  your job to guess sincerity.

**`hardship`** — states inability to pay.
- Yes: "cash nahi hai", "business bahut slow hai", "ek saath nahi de paunga"
- **Distinguish carefully from `refusal`.** Hardship says *cannot*. Refusal says
  *will not*, or gives no reason. Getting this wrong is the error with the most
  human cost, so when it is genuinely unclear, mark `ambiguous` rather than
  guessing.
- A request to split into instalments is `hardship`.

**`refusal`** — declines to pay, with no commercial reason and no stated
inability.
- Yes: "abhi payment nahi hoga", "baad me dekhte hain"
- If a reason involving the goods is given → `dispute`. If inability is stated →
  `hardship`.

**`acknowledgement`** — received, no commitment, no information.
- Yes: "noted", "ok dekhta hoon", "will revert", "theek hai"
- The test: strip politeness. If nothing remains that changes what the supplier
  should do next, it is an acknowledgement.

**`unclear`** — you cannot assign one of the above. Use sparingly and only after
genuinely trying. Not a synonym for `ambiguous` — use `unclear` when the intent
cannot be determined, and the `ambiguous` flag when you chose a label but were
not confident.

## When two labels both fit

Priority order, highest first:

1. `dispute`
2. `payment_claim`
3. `hardship`
4. `promise_to_pay`
5. `document_request`
6. `process_deflection`
7. `refusal`
8. `acknowledgement`

A reply that disputes *and* promises ("credit note bhejo, phir 15 tak kar denge")
is `dispute` — because the dispute is what blocks the money, and acting on the
promise while ignoring the dispute is the failure mode we are trying to prevent.

Record the promised date in the extra fields even when the primary label is
`dispute`.

## Extra fields

- **promised_date_raw** — the date expression verbatim: "month end tak", "15
  tarikh". Copy it exactly; do not convert it.
- **promised_date_resolved** — your calendar reading of it, relative to the
  supplied "message date". Leave blank if you genuinely cannot pin it.
- **disputed_amount** — only if a figure is stated.
- **claimed_utr** — any transaction reference, verbatim.
- **requested_documents** — free text list.
- **confidence** — `clear` or `ambiguous`. Be honest. The `ambiguous` items are
  reported as their own subset and are among the most useful data we will have.

## What not to do

- Do not look up the other annotator's labels.
- Do not skip items that annoy you; label them and flag `ambiguous`.
- Do not correct spelling, expand short forms, or normalise the text in any way.
- Do not label based on the scenario when the reply contradicts it.
