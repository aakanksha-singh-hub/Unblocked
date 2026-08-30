# Application form answers

Plain language, copy-paste ready.

---

## Project Objectives — what does it solve?

Small businesses in India wait around 73 days to get paid on invoices that say
30 days. Every accounting tool they own can tell them **who** owes them money.
None of them work out **why** that money hasn't arrived — and that turns out to
be the only thing that decides what to do about it.

So the owner waits, because sending a reminder is never free. Too gentle and it's
ignored. Too firm and she loses a customer worth a fifth of her business. Waiting
is the safest move on any single invoice, and the money stays out.

Unblocked works out why each invoice is stuck, does the one thing that fixes
that, and stays quiet the rest of the time.

The important part is that "unpaid" usually isn't one problem. A buyer on a fixed
monthly payment run isn't ignoring you — their accounts team pays once a month
and asking again won't move the date. A buyer with an unresolved complaint about
damaged goods won't pay until the complaint is settled, no matter how you ask.
And very often the invoice simply never reached the buyer's system — never
uploaded to their portal, or missing a purchase order number — so nobody on their
side can even see it. On an ageing report all three look identical: "90 days
overdue."

Once it knows which of those it is, it picks the matching action — chase the
paperwork, settle the complaint, offer instalments, send a payment link, or do
nothing at all. **94% of the time it decides to do nothing**, which is the
point: it only spends the owner's goodwill where that will actually get her paid.

Against doing nothing it collects **₹1.28 lakh more per buyer**, and it is the
only approach tested that is still ahead once you charge it for the customers it
annoys and the owner's time it uses.

---

## Build challenges & technical obstacles

**The hardest bugs weren't crashes. They were results that looked fine.**

**1. My own test environment was lying to me.**
To measure whether the agent works, I built a simulated set of buyers who behave
in different ways. In an early version, a buyer only ever raised a complaint
*after* being contacted. That sounds harmless, but it meant the simulation
concluded that the best response to a damaged delivery was to never mention it —
because if you never ask, you never hear about the problem.

The overall numbers looked good, so nothing flagged it. I only found it by asking
a question the aggregate hid: *"why is 'do nothing' beating my agent on this one
group of buyers?"* Complaints are now facts that exist from the start, and
contact simply reveals them. That group went from losing to winning.

The same mistake turned up twice more elsewhere. I now check any result where a
simple baseline beats the agent, rather than trusting the total.

**2. I tested the wrong assumption, and finding that out was more useful than the
test.**
I assumed the result depended on how quickly buyers get annoyed by messages, and
built a test to find the tipping point. There isn't one — the answer barely moves.
Worse, that test showed me the two assumptions that *do* carry the result were
buried in the code in a way my own test couldn't reach. I pulled them out and
tested them properly. One of them turns out to carry almost the whole result, and
the project now says so plainly rather than claiming more than it can support.

**3. Checking whether my own data was real.**
The one part of this that isn't simulated is understanding what buyers write
back, in Hinglish. I collected replies from real people and had two others label
them independently. The first batch I got back looked wrong, so I wrote a tool to
check it — and it found the same sentence appearing word-for-word under three
different contributors. I threw that batch out, kept it in the repo with a note
explaining why, and collected again properly. The second batch passed, and the
two people labelling it agreed 86% of the time.

**4. It was being killed on the hosting platform.**
The site kept restarting for using too much memory. It wasn't traffic — it was
recording so much detail about every decision that it ran out of memory before
anyone visited. I cut the part nothing displays and halved it.
