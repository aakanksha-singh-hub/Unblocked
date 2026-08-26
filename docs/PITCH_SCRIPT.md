# Pitch script — 5 minutes

Read it once, then talk it rather than reading it aloud. The bracketed lines are
what to have on screen, not things to say.

**Before you start:** `unblocked ui` running on :8000, terminal in a second
window, a Razorpay test card ready (`5267 3181 8797 5449`, any future expiry, CVV
`123`, OTP `1111`). Do a dry run of the payment once so you know the flow.

---

## 0:00 — 0:35 · The problem

> An Indian small business waits about seventy-three days to be paid on invoices
> written with thirty-day terms.
>
> Every ERP she owns will tell her **who** owes her money. Tally, Zoho, all of
> them. None of them work out **why** — and that turns out to be the only thing
> that decides what to do about it.
>
> So she waits, because waiting is the safest move on any single invoice. The
> money stays out, and she borrows to cover the gap.

*[Landing page, top of screen. Do not scroll yet.]*

---

## 0:35 — 1:10 · What it does

> This is Unblocked.
>
> **It works out why an invoice is stuck, fixes that, and stays quiet the rest of
> the time.**
>
> That last part is most of it. Ninety-four percent of the decisions it makes are
> decisions to do nothing.

*[Point at the one-liner and the +Rs 41.5K figure. Then scroll to the two
diagrams.]*

> Collections software escalates on **age** — thirty days, sixty days, ninety
> days. That only works if every buyer is late for the same reason. They aren't.
>
> Six causes, six different right answers. A buyer on a fixed monthly payment
> cycle doesn't need a reminder, they need their invoice to reach the AP desk
> before the cut-off. A buyer with an unraised complaint doesn't need a reminder
> at all until the complaint is settled.

---

## 1:10 — 2:00 · One real buyer

*[Scroll to the story. Walk down the four beats.]*

> Here's one buyer from the run. Three hundred and seven days overdue — a ladder
> would escalate.
>
> Instead it works out the reason: short of cash, eighty-one percent confident,
> from how they've paid before.
>
> But then it finds something that outranks that. One of their invoices never
> reached the buyer's system — never uploaded, no PO number. Nobody on their side
> can see it. **A buyer who cannot see an invoice cannot pay it, however willing
> they are.** No reminder, however well judged, could have worked.
>
> So it fixes the paperwork first. Then the buyer writes back — in Hinglish —
> naming a date, and it goes quiet until that date.

---

## 2:00 — 2:40 · Restraint

*[Click "See it decide not to send". Restraint page.]*

> Anyone can build something that chases. The interesting output is the silence.
>
> Of twenty-five thousand chances to send something, it held back on ninety-four
> percent. And I want to be precise about that number, because it's the kind of
> thing that's easy to inflate: **only forty-one percent of those holds are a rule
> stopping it.** The rest are an expected-value calculation deciding nothing is
> worth its cost, or the calendar.

*[Scroll to the promise-freeze table.]*

> These are the ones I'd point at. The buyer said *"dekhiye pandrah taarikh tak
> clear kar dunga"* — and the agent quotes that back as its reason for staying
> silent until the fifteenth.
>
> No model runs in that layer. Every one of those rules is plain code, because an
> LLM that can be talked out of a stopping rule is not a stopping rule.

---

## 2:40 — 3:15 · A real payment

*[Switch to terminal.]*

> Everything I've shown you so far runs on a simulated book. So here's the part
> that isn't.

```
unblocked prove --amount 2500
```

*[Open the link, pay it, come back.]*

```
unblocked prove --check <link_id>
```

> Two and a half thousand rupees, collected through Razorpay, matched back to the
> invoice on a reference we set when the link was issued — never on anything the
> payer controls. The agent marks it settled and stops chasing.
>
> That's attested by Razorpay's API, not by my own bookkeeping.

---

## 3:15 — 4:00 · Does it work

*[Evaluation page.]*

> Seven hundred and twenty-eight buyers, held out. Every policy faces identical
> random draws, so the differences are paired rather than two lucky runs.
>
> Against doing nothing it recovers about **one lakh twenty-eight thousand rupees
> more per buyer.** And after charging what it cost — lost accounts, the owner's
> time — it's still **forty-one and a half thousand ahead.**
>
> **No baseline manages that.** Chasing everyone weekly recovers significantly
> more than doing nothing, and then loses all of it to churn. That's why the cost
> columns sit on the same table as the money instead of in an appendix.

---

## 4:00 — 4:40 · The honest part

> Now the part I'd want to hear if I were you.
>
> **I wrote the simulator.** Beating baselines inside a world I built measures
> policy quality given my assumptions — it is not evidence the assumptions hold,
> and this repo says so on its own front page.

*[Sensitivity page.]*

> I built a sweep expecting to report a contact-fatigue threshold. There isn't
> one. And that failure showed me the two parameters most likely to be carrying
> the result were hardcoded literals my own sweep couldn't even reach.
>
> So the honest claim is narrower than "cause-matching works": **most of the
> advantage is the intake-repair mechanism**, and if chasing paperwork rarely
> unblocks an invoice in reality, most of this evaporates.

*[Understanding page.]*

> One measurement here isn't downstream of my simulator. A hundred and twelve
> Hinglish replies from fourteen people who were never shown my taxonomy,
> labelled independently by two annotators. **Kappa: point eight five five.**
>
> The model reads them better than the rule baseline. But the paired test comes
> out at **p equals point one** — so on this sample, the model is **not shown** to
> beat the patterns, and I say that rather than quoting the point estimate.

---

## 4:40 — 5:00 · What broke

> The thing I'd tell you about is a bug in my own simulator. It made contacting a
> buyer **cause** the dispute that blocked payment — so "never chase" won that
> segment for an entirely spurious reason. Under that model, the best response to
> a damaged delivery is to never mention it.
>
> I found it by asking why a baseline was beating my agent on one segment,
> instead of accepting the aggregate number that looked fine.
>
> The same causality error turned up twice more. The third one is still unfixed,
> and it's documented as unfixed.

---

## Notes

- **Say the numbers slowly.** ₹1.28L and ₹41.5K are the two that matter.
- **Do not skip 4:00–4:40.** Everyone will show recovery numbers. Almost nobody
  will show the experiment that embarrassed them, and that section is why a panel
  believes the rest.
- If the live payment fails, say so and use the artifact in `artifacts/proof/`.
  A failure handled calmly is better television than a clean run.
- Total spoken words ~780, which lands near five minutes at a normal pace.
