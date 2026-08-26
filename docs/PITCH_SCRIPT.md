# Pitch script — long form

**This is deliberately over-length.** It walks every page and states every number
so you can cut rather than invent. Roughly 11 minutes as written; the target is
5. Cut marks are on each section:

- **KEEP** — the five minutes I would actually record
- **CUT FIRST** — drop these to hit time
- **ONLY IF ASKED** — panel-answer material, not video material

**Setup:** `unblocked ui` on :8000. Terminal in a second window. Test card
`5267 3181 8797 5449`, expiry `12/28`, CVV `123`, OTP `1111`. Do one dry run of
the payment first.

---

# 1 · The problem — **KEEP** (0:35)

*[Landing page, top. Do not scroll.]*

> An Indian small business waits about seventy-three days to be paid on invoices
> written with thirty-day terms.
>
> Every ERP she owns will tell her **who** owes her money — Tally, Zoho, all of
> them. None of them work out **why**. And that turns out to be the only thing
> that decides what to do about it.
>
> So she waits, because waiting is the safest move on any single invoice. The
> money stays out and she borrows to cover the gap.

### Optional extra — **CUT FIRST**

> She is also her own sales head and her own accounts department. The hardest
> five percent of the job — the follow-up — lands on the one person who has no
> time for it.

---

# 2 · What it is — **KEEP** (0:35)

*[Still on the first screen. Point at the one-liner, then the figure.]*

> This is Unblocked. **It works out why an invoice is stuck, fixes that, and
> stays quiet the rest of the time.**
>
> The number on the front page is deliberately not the biggest one I have. It's
> **forty-one and a half thousand rupees per buyer, after** charging what the
> chasing cost — lost accounts and the owner's time. The bigger number is on the
> next screen down.
>
> And it says right there that the book is simulated and the payment rail is
> real. I'd rather you know that before you see a number than after.

---

# 3 · The idea — **KEEP** (0:35)

*[Scroll to the two diagrams.]*

> Collections software escalates on **age** — day thirty, day forty-five, day
> sixty, day ninety. That only works if every buyer is late for the same reason.
>
> They aren't. Six causes, six different right answers.
>
> A buyer on a fixed monthly payment cycle doesn't need a reminder — their AP
> desk runs payments once a month and asking again doesn't move the date. A buyer
> with an unraised complaint doesn't need a reminder at all until the complaint is
> settled. And a buyer who was always going to pay needs nothing, so every message
> you send them is pure cost.

---

# 4 · One real buyer — **KEEP** (0:50)

*[Scroll to the story. Walk the four beats.]*

> This is a buyer from the run you can browse on this site — not an illustration.
>
> **Three hundred and seven days overdue.** A ladder escalates.
>
> Instead it works out the reason first: **short of cash, eighty-one percent
> confident**, from how they've paid before.
>
> Then it finds something that outranks that. One of their invoices **never
> reached the buyer's system** — never uploaded to their portal, no PO number.
> Nobody on their side can see it.
>
> **A buyer who cannot see an invoice cannot pay it, however willing they are.**
> No reminder, however well judged, could have worked on that invoice.
>
> So it fixes the paperwork first. Only then does the cause decide what happens
> next.

*[Point at the Hinglish reply.]*

> The buyer writes back — *"month end tak ko release kar denge, accounts ko bol
> diya hai"* — it reads that as a commitment with a date, resolves "month end" to
> the thirty-first, and goes silent until then.
>
> **One crore thirty-five lakh collected. Ninety-six percent of what was owed.**

---

# 5 · Does it work — **KEEP** (0:45)

*[Scroll to the net-value chart, then click through to Evaluation.]*

> Seven hundred and twenty-eight buyers, held out. Every policy faces **identical
> random draws**, so the differences are paired rather than two lucky runs.

*[Evaluation table.]*

> Doing nothing recovers fifty-nine percent of the book. Chasing everyone weekly
> gets sixty-one. A thirty-sixty-ninety ladder, fifty-nine. **This gets seventy
> point six.**
>
> That's **one lakh twenty-eight thousand rupees more per buyer** than doing
> nothing.
>
> But look at the cost columns, which sit on the same table on purpose. Blast-
> weekly sends **seventeen thousand messages** and loses **fifty accounts**. After
> charging that, it's *behind* doing nothing. **It recovers significantly more and
> then loses all of it to churn.**
>
> This sends five thousand, loses thirty-seven, and is **forty-one and a half
> thousand ahead per buyer on net.** No baseline manages that.

### Segment table — **CUT FIRST**

> The advantage isn't uniform. Process-bound buyers go from fifty-seven to
> seventy-nine percent, almost entirely from finding invoices stuck at intake.
> Buyers who can't pay in one go go from twenty-four to thirty-eight, from
> instalment offers no baseline ever makes. Cash-stressed, seventy-seven to
> eighty-eight.

---

# 6 · Restraint — **KEEP** (0:50)

*[Restraint page.]*

> Anyone can build something that chases. The interesting output is the silence.
>
> Twenty-five thousand chances to send something. It held back on ninety-four
> percent of them.
>
> And I want to be precise about that, because it's easy to inflate: **only nine
> thousand eight hundred of those are a rule stopping it.** Nine thousand are an
> expected-value calculation deciding nothing is worth its cost, and five thousand
> are the calendar. **Forty-one percent is the honest number.**

*[Scroll to the rules table.]*

> Every rule names itself. Sunday or a public holiday, five thousand times. An
> unresolved complaint, two and a half thousand. Already contacted enough this
> month, sixteen hundred. **They said they can't pay — don't apply pressure**, two
> hundred and seventy-four.

*[Promise-freeze table.]*

> These are the ones I'd point at. The buyer said *"dekhiye pandrah taarikh tak
> clear kar dunga"* — and the agent quotes that back as its own reason for staying
> silent until the fifteenth.
>
> **No model runs in that layer.** Every rule is plain code, because an LLM that
> can be talked out of a stopping rule is not a stopping rule.

### Human sign-off — **CUT FIRST**

> Thirty-three actions needed a person. Anything irreversible — an owner-to-owner
> call, a statutory notice — is gated. A Samadhaan filing is never executed at all;
> it can only be recommended. That's a legal act against a counterparty and it
> belongs to a human.

---

# 7 · A real payment — **KEEP** (0:40)

*[Terminal.]*

> Everything so far runs on a book I generated. So here's the part that doesn't.

```
unblocked prove --amount 2500
```

*[Open the link. Pay it. Return.]*

```
unblocked prove --check <link_id>
```

> Two and a half thousand rupees, collected through Razorpay, reconciled against
> the invoice on a **reference we set when the link was issued** — never on
> anything the payer controls. The agent marks it settled and stops chasing.
>
> That's attested by Razorpay's API, not by my bookkeeping.

### The failure — **CUT FIRST, but keep if the live one fails**

> The first time I ran this it was declined — the card routed as international.
> Nothing was double-issued, the link stayed live, and resuming was one command. A
> collections tool whose answer to a failed payment is a second demand at the same
> buyer is exactly what this exists to avoid.

---

# 8 · The honest part — **KEEP, do not cut** (0:50)

> Now the part I'd want to hear if I were on your side of this.
>
> **I wrote the simulator.** Beating baselines inside a world I built measures
> policy quality *given my assumptions*. It is not evidence the assumptions hold,
> and the repo says so on its own front page.
>
> The obvious defence is that I froze the environment before building the agent,
> and you can check the commits. **That defence doesn't work** — commit ordering
> proves sequence, not independence. Same author, same afternoon.

*[Sensitivity page.]*

> So I went looking for where it breaks. I built a sweep expecting to report a
> contact-fatigue threshold — the point where spamming starts to win.
>
> **There isn't one.** From fatigue switched off entirely to severe, the margin
> moves about ten percent and never crosses zero.
>
> And that failure told me something worse: the two parameters most likely to be
> carrying the result were **hardcoded literals my own sweep couldn't reach.** A
> limitations section that lists every parameter is worthless if the important
> ones live somewhere else.
>
> With those exposed: at zero, **eighty-eight percent of the advantage
> disappears.** So the honest claim is narrower than "cause-matching works" — it's
> **most of the advantage is the intake-repair mechanism**, and if chasing
> paperwork rarely unblocks an invoice in reality, most of this evaporates.

---

# 9 · The measurement that isn't mine — **KEEP** (0:40)

*[Understanding page.]*

> One number here isn't downstream of my simulator.
>
> **A hundred and twelve Hinglish replies** from fourteen people who were never
> shown my taxonomy. Labelled independently by **two annotators who aren't me**.
> Split by contributor and hashed before any model output was looked at.
>
> **Inter-annotator kappa: point eight five five.** I report that before any model
> number, because if two people can't agree what a message means, model accuracy
> on those items isn't measuring comprehension.
>
> The model reads them better than the rule baseline. But the paired test comes
> out around **p equals point one** — so on this sample the model is **not shown**
> to beat the patterns, and I'd rather say that than quote the point estimate.

### The one thing worth pointing at — **CUT FIRST**

> There is one result I'd lean on. The rule extractor reads **hardship as refusal
> two times in nine.** The model, zero. Reading someone who *cannot* pay as
> someone who *will not* is the error that does human damage — and it's exactly
> why the hardship shield is hard-coded rather than trusted to a classifier.

### What the annotators found — **ONLY IF ASKED**

> They also found a hole in my instrument. Every one of their first-round
> disagreements was the same construction — *"half payment kar diya tha, baki
> thoda time lagega"* — a payment claim and a promise in one sentence, which my
> codebook never addressed.
>
> And in round two: a buyer who **has** the money and has chosen not to pay you
> yet is neither hardship nor a process nor a bare refusal. My taxonomy has no
> home for it. That's documented as an open gap rather than patched, because
> adding a class mid-study would invalidate a hundred and twelve existing labels.

---

# 10 · What broke — **KEEP** (0:35)

> The one I'd tell you about is a bug in my own simulator.
>
> It made contacting a buyer **cause** the dispute that blocked payment. So "never
> chase" won that segment — for an entirely spurious reason. Under that model, the
> best response to a damaged delivery is to never mention it.
>
> I found it by asking why a baseline was beating my agent on **one segment**,
> instead of accepting the aggregate number, which looked fine.
>
> The same causality error turned up twice more. **The third one is still unfixed,
> and it's documented as unfixed** — the correct treatment is a latent intended
> pay-date that the promise merely reports, and that's a bigger change than the
> time allowed.

### Other bugs — **ONLY IF ASKED**

> - A failed API call was being recorded as "the model was unsure", which turned
>   an honesty metric into a measurement of my network.
> - The policy degenerated once and sent three thousand messages that were
>   entirely document chases, including to buyers whose paperwork it had already
>   fixed.
> - `open_invoice_ids` scanned the whole book per buyer per day — four hundred and
>   seventy-two million comparisons. A full run went from thirty seconds to one
>   point four.
> - Both chasing baselines were strawmen at first. The ladder re-fired owner
>   escalation every fortnight forever and churned eighty-five percent of the
>   book. Beating that would have proved nothing.

---

# 11 · Pages I would not show — **CUT ALL**

Material if a panel opens them.

**Ledger.** The browsable book: ₹23.17Cr invoiced, ₹16.89Cr recovered, ₹5.27Cr
outstanding, 1,491 messages, 46 hours of owner time, 11 accounts lost.

**Buyers.** 180 buyers with the agent's inferred cause **beside the real one**,
which it never sees — 51 fixed-cycle, 43 unhappy with the goods, 40 prompt, 30
short of cash, 10 ignoring you. Filter by "it got wrong" to see the misses.

**Buyer detail.** Every decision for one buyer including the holds, with the gate
that blocked each, and the belief evolving from cold start to 91% confident.

**Method.** What the evaluation establishes and what it doesn't. Twenty-four of
twenty-nine parameters are designer priors, and the header of every run says so.

**Cause inference.** Macro-F1 **0.803** on held-out — labelled in the report as
*recovering a latent generator variable in simulation*, not a real-world
classification result. Distressed misread as avoider: **5 of 252**, tracked
separately because mistaking someone who can't pay for someone who won't is the
error that hurts people.

---

# Delivery notes

- **Say numbers slowly.** ₹1.28L and ₹41.5K are the two that matter.
- **Never cut section 8.** Everyone will show recovery numbers. Almost nobody
  will show the experiment that embarrassed them, and that section is why a panel
  believes the other four minutes.
- **Volunteer the 41%.** If you say 94% and let someone find the split, you look
  like you were hiding it. If you say it yourself, you look like you check things.
- If the live payment fails, say so and show `artifacts/proof/`. A failure handled
  calmly is better television than a clean run.
- KEEP sections alone are ~5:15. Trimming the segment table and the sign-off
  paragraph lands you at 5:00.
