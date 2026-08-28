# Deploying the dashboard

The dashboard is a **long-lived process**, not a request-scoped function. It
simulates a world once and holds it in memory for the life of the process —
deliberately, so that two pages of the same dashboard cannot disagree with each
other about what happened (`src/unblocked/ui/state.py`).

That single fact decides where it can be hosted, and how.

## Why not serverless

Measured on this repo, not estimated:

| | |
|---|---:|
| `state.build()`, 180 buyers | **6.1s**, 507MB peak |
| scipy + scikit-learn + numpy, unzipped | **143MB** |
| Vercel serverless limit | 250MB, 10s default timeout |

A serverless function is a fresh container on every cold start, so it would
re-run that 6-second simulation before it could answer, on a slower CPU than
the one above, against a 10-second clock — and carry 143MB of scientific
Python to do it. The app is not badly written for serverless; it is a
different shape from serverless.

Static prerendering *is* a good fit and would be worth doing if the site ever
needs to be free and instant. It costs the live extractor demo on
`/understanding` and the `?cause=` filter links, both of which would have to be
rebuilt client-side.

## Render, as a Web Service

**New → Web Service**, point it at this repository. No `render.yaml` and no
code change is required; everything below goes in the form.

| Field | Value |
|---|---|
| Root Directory | *blank* — the app is at the repo root |
| Language | `Python 3` |
| Build Command | `pip install -e .` |
| Instance Type | Free is enough |

Start Command:

    python -c "import os,uvicorn,unblocked.ui.app as a; _o=a.app_state.build; a.app_state.build=lambda **k: _o(merchants=3,buyers=30); uvicorn.run(a.app,host='0.0.0.0',port=int(os.environ['PORT']))"

Set `PYTHON_VERSION` to `3.11.9`.

### Why the start command is not just `uvicorn`

**The 180-buyer default peaks at 507MB while building, over the 512MB a free
instance gets, and is killed part-way through.** `STATE` is a module-level
global that `get_state()` returns if it is already set, so seeding it with a
smaller world before serving avoids that entirely. Measured:

| world | peak RSS | build |
|---|---:|---:|
| 180 buyers (`unblocked ui` default) | 507MB | 6.1s |
| **90 buyers (hosted)** | **350MB** | 4.0s |
| 50 buyers | 278MB | 3.6s |

It reads `PORT` from the environment rather than from the shell, so there is no
quoting to get wrong.

It replaces the builder rather than pre-seeding `STATE`, so the port binds
within two seconds and the world is built lazily on the first request, as it is
locally. That ordering is deliberate: **Render fails a deploy it cannot detect
an open port for**, and the free instance is 0.1 CPU — a tenth of a core — on
which a build measured at 5.3s here can take the better part of a minute.
Binding first puts that time inside a request, where it costs one visitor a
slow page, instead of in front of the port scan, where it can cost the deploy.

This changes only **the run you can browse**. Every measured number on
`/evaluation` and `/sensitivity` is read from the committed artifacts, which
were computed on 728 buyers and do not move with this setting. The dashboard
has always said which of the two each page is reading.

### Cold starts

A free instance sleeps after ~15 minutes idle. The first visitor after that
waits for the container to wake **and** for the world to build — plan for
roughly 40-60 seconds. Anyone demoing this should open it once beforehand. A
paid instance does not sleep.

## Railway, Fly.io, or any container host

Nothing above is Render-specific. The same build and start commands work
anywhere that runs a process and gives you a `$PORT`. Give it **512MB or
more**, and note the table above if you give it less.

## The model path on /understanding

The rule extractor runs with no configuration. Setting `ANTHROPIC_API_KEY` in
the host's own secret store — never in the repo — enables the model extractor
beside it. Without it the page degrades to rules alone rather than failing,
which is the intended behaviour and is what `tests/test_ui.py` asserts.
