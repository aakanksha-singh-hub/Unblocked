# What this evaluation establishes, and what it does not

Read this before any number in this repository.

## The problem with our own headline result

This project ships a simulator and an agent. The simulator's effect matrix
encodes a thesis: that a soft nudge is worth 1.6x on a cash-stressed buyer and
1.0x on a process-bound one. The agent's central mechanism is inferring which
buyer is which. The agent then beats baselines that do not make that
distinction.

That result was determined the moment the effect matrix was written.

It is tempting to defend this by pointing at the commit history: the environment
was built, frozen and tagged before the agent existed. That defence does not
work, and we are not going to make it. Commit ordering proves *sequence*, not
*independence*. Same author, same afternoon, and the thesis predates both
commits. Freezing a hypothesis before testing it against a world you also wrote
is not pre-registration; it is bookkeeping.

So we are not claiming the simulation is evidence that the thesis is true.

## What the simulation actually measures

**Policy quality conditional on stated assumptions.**

Given the world described in `sim/calibration.py` - and only given that world -
does our policy extract more money, at lower relationship and human cost, than
the alternatives? That is a real question with a real answer, and it is worth
asking, because a policy can easily lose *even inside a world built to favour
it*. Timing, sequencing, budget allocation across a portfolio, and knowing when
to stop are all genuinely hard under our own assumptions, and a naive agent that
merely knows the archetypes still underperforms.

The right analogy is a chess engine's Elo against other engines. It is a
meaningful, reproducible measurement. It is not a claim about human chess.

What we may say:
> Under the assumptions in calibration.py, this policy recovers X% more than a
> static ladder while sending 4x fewer messages.

What we may not say, and do not:
> This proves cause-matched collections beat dunning ladders.
> This agent will recover X% more for a real merchant.

## The classifier number, labelled correctly

Inside the simulator, archetypes are ground truth *by construction*: we drew
them, then generated behaviour from them. Recovering them from that behaviour
measures how invertible our own generator is. It is a sanity check on whether
the latent variable leaves a legible trace, and a legitimate one - a generator
whose latent state is unrecoverable would tell us the world is degenerate.

It is not a claim that we can classify real buyers.

Every chart carries the full label:

> Macro-F1 on recovering a latent generator variable in simulation. Not a
> real-world classification result.

The confusion matrix is reported in full, with DISTRESSED -> AVOIDER broken out
separately, because mistaking someone who cannot pay for someone who will not is
the error that does human damage.

## Leading with the condition under which we are wrong

Our headline finding - that high-frequency chasing loses money - rests almost
entirely on one invented number: the per-message contact-fatigue multiplier,
currently 0.88 applied past three contacts in a rolling thirty days.

We did not measure that. We chose it.

Burying that in a threats-to-validity section at the bottom would be a way of
technically disclosing it while practically hiding it. Instead the breakeven is
the **first** result in the report, above our own headline:

> Blast-weekly loses to cause-matched only while per-message fatigue is below
> f*. Above f*, blast-weekly wins and our thesis is wrong on this book.

`eval/breakeven.py` finds f* by bisection rather than asserting it. We report the
value, and we report how far our chosen 0.88 sits from it. If the honest answer
turns out to be "our thesis holds only in a narrow band," that is the finding,
and it goes on the slide in that form.

We deliberately do not choose the perturbation ranges for the sensitivity sweep
and then report only that we survived them. The breakeven is a threshold someone
else can evaluate against their own beliefs about how buyers behave.

Scope, given twelve days: three parameters swept - contact fatigue, archetype
mix, and promise reliability. Chosen because each one, if wrong, breaks a
different load-bearing claim.

## The one number here that is about the world

Exactly one layer of this system produces evidence that is not downstream of our
own generator: **inbound reply understanding**.

The protocol, in `docs/EXTRACTION_PROTOCOL.md`:

- The reply texts are **not written by us**. They are elicited from people who
  work in or around small businesses, given only a situation ("your supplier has
  chased you for a 40-day-old invoice; you intend to pay after your GST filing")
  and never shown our intent taxonomy.
- Labels are applied by **two annotators who are not the author**, independently,
  from a written codebook.
- We report **inter-annotator agreement (Cohen's kappa)** before we report model
  accuracy. If humans cannot agree on what a message means, model accuracy on
  those items is not measuring comprehension.
- Disagreements are adjudicated and kept as a separate hard subset, reported
  separately rather than dropped.
- The model never sees any item during prompt development. A development split is
  drawn first and the test split is opened once.

This set is small - target 150-200 items - and we will say it is small. But it is
the only place in the stack where the numbers are about Indian B2B payment
language rather than about our own code, and that makes it worth more than
another thousand simulated buyers.

## The one thing here that is not a simulation at all

Money recovered inside a simulator we wrote is a number our code printed.

`adapters/razorpay_live.py` executes one path against Razorpay test-mode APIs
end to end: a parsed reply triggers a payment link, the buyer pays, the webhook
fires, the ledger reconciles and the agent stops chasing. The capture is
attested by Razorpay's dashboard, not by our bookkeeping.

One real captured payment is a categorically different kind of claim from ten
thousand simulated ones, and it is prioritised accordingly - built third, ahead
of extra baselines.

## Baselines

Three, plus a ceiling:

- **never-chase** - the floor, and a genuinely competitive one on a book that is
  30% prompt payers. Any agent that cannot beat "do nothing" on net value has
  learned nothing.
- **blast-weekly** - contact everyone open, every week. The strategy fatigue is
  designed to punish, which is exactly why its breakeven is reported first.
- **static ladder** - 30/60/90-day escalation, what most collections software
  actually does.
- **oracle** - handed the true archetype for free. Not a baseline but a ceiling;
  the gap between our agent and the oracle is the part of the problem inference
  has not solved, and reporting it stops "we beat the baselines" from being a
  brag.

The hand-tuned human heuristic is cut for time. The three above bracket the
space.

## Cost metrics, reported whether or not they flatter us

Recovered rupees alone would let us win by harassing people. Reported alongside,
always, on the same table:

- **Wasted contacts** - messages sent to buyers whose pay date is, by
  construction, contact-insensitive. This is our false-positive cost.
- **Relationship capital spent**, and accounts pushed past their churn threshold.
- **Human-minutes consumed.** An agent that recommends forty phone calls a day
  has not helped a fourteen-person unit where the owner is also the collections
  department. This metric can only make our agent look worse, and it stays.

## What the sweeps actually found

We built the breakeven expecting to report the fatigue threshold. The result was
a negative one, and more useful than the answer we went looking for.

**Contact fatigue does not carry the result.** Swept from disabled entirely
(retention 1.00) to severe (0.70), the margin moves about 10% and never crosses
zero. Our conclusion does not depend on the constant we assumed was load-bearing,
which means the paragraph we were about to write defending our choice of 0.88
would have been defending something that did not matter.

That failure exposed a defect worth stating plainly. The two probabilities most
likely to be carrying the result - how often a document chase unblocks an
invoice, how often a dispute-resolution contact settles one - were **hardcoded
literals in dynamics.py rather than parameters**. The sensitivity analysis could
not have reached them. A limitations section listing every parameter is worthless
if the important ones live somewhere else.

With those exposed and swept:

| parameter | worst case in range | verdict |
|---|---:|---|
| `PORTAL_REPAIR_SUCCESS` | **11%** of margin | **carries the result** |
| `ARCHETYPE_MIX.process_bound` | 55% | matters, does not carry |
| `DISPUTE_RESOLUTION_SUCCESS` | 83% | matters, does not carry |
| contact fatigue | ~90% | largely insensitive |

So the honest claim is narrower than "cause-matching works". It is: **most of the
advantage is the intake-repair mechanism.** If chasing paperwork rarely unblocks
an invoice in reality, most of this evaporates. That is the assumption to attack.

We also report worst-case collapse rather than only whether a crossing exists,
because "no crossing" cannot distinguish a parameter that wipes out 88% of the
margin from one that costs 17%.

## Testing the stopping rule directly

The promise freeze is the project's headline behaviour, so it should not rest on
an intuition that restraint is worth it. We ran the identical agent with the
promise freeze switched off and nothing else changed:

| | cash-stressed recovery | promise respect |
|---|---:|---:|
| agent, respects promises | 80.2% | 67% |
| agent, ignores promises | 75.0% | 27% |

Respecting promises **earns** 5.2pp on the segment that makes the least reliable
promises. Our prior going in was that restraint would cost recovery and buy
relationship capital. That prior was wrong, and the measurement is what said so.

## A causality error we fixed twice, and one we did not

Twice now the generator has made *contact* the cause of something that should
have existed independently:

1. **Disputes were created by replying.** Under that model the optimal response
   to a damaged consignment is to never mention it, and never-chase won the
   disputer segment for an entirely spurious reason. Fixed: disputes are latent
   from day one and contact reveals them.
2. **Promises suppressed the payment hazard.** A buyer who intends to pay at
   month end intends that whether or not anyone asked; saying it aloud does not
   push the date back. Letting contact produce a promise which then suppressed
   payment made chasing a cash-stressed buyer harmful, contradicting our own
   effect matrix. Weakened to a small commitment-anchoring effect.

**The one we did not fix.** The fully correct treatment is a latent intended
pay-date per buyer, with the hazard concentrated there whether or not anyone
asked, and the promise merely reporting it. That is a larger change to the
generator than the remaining time allows. It is recorded here rather than
quietly ignored, and it is the first thing we would do with another week.

A third incoherence of the same family: the effect matrix said instalment offers
help cash-stressed buyers while the plan mechanic capped their payments and
suppressed the hazard between monthly dates - two parts of one model
contradicting each other, which is worse than either being wrong alone.

## Threats to validity

1. **Generator circularity.** The dominant limitation, addressed above.
2. **Parameter invention.** Twenty of the ~25 parameters are designer priors.
   `calibration.provenance_report()` prints that count at the head of every run.
3. **No real payment behaviour.** Nothing here is fitted to observed data.
4. **Population plausibility.** The archetype mix is asserted, not sampled.
5. **Single-book variance.** Reported across 14 merchants, appendix table only.
6. **Reply-set size.** 150-200 items is enough for a confidence interval that
   will be wide, and we report the interval rather than the point estimate.
7. **Promises still carry a small causal effect** they should not have. See
   above; the latent pay-date refactor is unfinished.
8. **The archetype model is trained on data from our own baseline policies.**
   Reply features only exist where contact happened, so pooling across
   never-chase, blast-weekly and static-ladder gives coverage of both regimes.
   It reduces the distribution shift against the agent's own behaviour; it does
   not eliminate it.

## The falsification test

If the extraction study came back at kappa 0.4 and model accuracy near the
majority-class baseline, the reply-understanding layer would be unsupported and
we would say so in the video rather than quietly dropping the slide.

That is the standard this document exists to hold us to.
