"""Common random numbers.

Every stochastic decision in the simulation is a deterministic function of
(run_seed, a stable entity key, the day, a stream name) rather than a draw from
a sequential generator. It costs a hash per draw and buys the single most
useful property the evaluation has:

**Policies are compared on paired samples.** When the static ladder and the
cause-matched policy are both run on seed 20260824, buyer `buy_ab12` on day 47
faces the *same* underlying uniform draw under both. If one collects and the
other does not, that difference is attributable to the policy, not to one run
happening to roll better dice.

Without this, distinguishing a 6% recovery improvement from run-to-run noise on
728 buyers would need many more replications than twelve days allows. With it,
the paired difference is measured directly and its confidence interval is
computed on the differences.

The subtlety it protects against: a sequential RNG makes the *number* of draws
depend on the policy - a policy that contacts more buyers consumes more randomness
and desynchronises every subsequent draw. Keying by entity and day rather than by
call order makes the draw for a given cell independent of everything the policy
did elsewhere.
"""

from __future__ import annotations

import hashlib
import struct

_MASK53 = (1 << 53) - 1


def u01(seed: int, *key: object) -> float:
    """Uniform [0, 1) for this exact cell. Pure, stable across processes.

    Deliberately not `random.Random(hash(key))`: Python's `hash` is salted per
    process for str, which would make runs irreproducible across invocations in
    a way that is extremely easy to miss.
    """
    h = hashlib.blake2b(digest_size=8)
    h.update(struct.pack("<q", seed))
    for part in key:
        h.update(b"\x1f")
        h.update(str(part).encode("utf-8"))
    (raw,) = struct.unpack("<Q", h.digest())
    return (raw & _MASK53) / float(1 << 53)


def bernoulli(seed: int, p: float, *key: object) -> bool:
    return u01(seed, *key) < p


def uniform(seed: int, lo: float, hi: float, *key: object) -> float:
    return lo + (hi - lo) * u01(seed, *key)


def choice(seed: int, options: list, *key: object):
    if not options:
        raise ValueError("choice from empty sequence")
    return options[min(int(u01(seed, *key) * len(options)), len(options) - 1)]


def weighted(seed: int, options: list, weights: list[float], *key: object):
    total = sum(weights)
    if total <= 0:
        raise ValueError("weights must sum positive")
    x = u01(seed, *key) * total
    acc = 0.0
    for opt, w in zip(options, weights):
        acc += w
        if x < acc:
            return opt
    return options[-1]
