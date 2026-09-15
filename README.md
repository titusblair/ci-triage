# ci-triage

Work out why CI failed — and whether it has failed that way before.

```
$ ci-triage watch pallets/flask --runs 12

  pallets/flask: 12 failed jobs -> 6 distinct failures (2 recurring)

  RECURRING  x4   test_failure    026ad8562329
             jobs: Development Versions
             seen: 2026-09-08 to 2026-09-13   owner: the author
             E   DeprecationWarning: The 'ImmutableDict' class is deprecated...

  RECURRING  x4   test_failure    fbc0079e96fa
             jobs: Development Versions
             seen: 2026-08-09 to 2026-08-11   owner: the author
             E   DeprecationWarning: The 'parse_cache_control_header' function is...
```

Twelve red builds. Six real problems. One of them has been failing since the 8th
and everybody has been hitting re-run.

No dependencies. Works on any public repo.

---

## The question this answers

Reading one failed log tells you what broke. It does not tell you the thing that
decides priority: **is this new, or has it been quietly failing for a month?**

Most CI tooling shows you a list of red X's. Every one looks equally urgent and
equally novel. So a flaky test that fires twice a week and a real regression that
appeared this morning get the same amount of attention, which is to say someone
clicks re-run on both.

Answering it means clustering failures by *what went wrong*, which means two runs
that failed the same way have to produce the same fingerprint even though their
logs share almost no literal text.

---

## How the fingerprint works

A failure signature is built by throwing away everything that varies between runs
and hashing what is left:

- **Teardown is cut first.** Everything after `Post job cleanup` is git config and
  orphan-process cleanup. It is the literal tail of every log and says nothing.
- **Generic trailers are excluded.** `Process completed with exit code 1` is true
  of every failure. Including it would collapse unrelated failures into one
  cluster.
- **Then everything variable goes**: timestamps, SHAs, UUIDs, temp paths, home
  paths, line and column numbers, memory addresses, ANSI colour codes, and every
  number.

That last one was not in the first version, and it broke the whole tool. A tox
summary reads:

```
tests-dev: FAIL code 4 (4.68=setup[0.61]+cmd[3.21,0.86] seconds)
```

Those durations differ on every single run. Four identical Flask failures were
producing four different signatures, so nothing ever clustered and the tool
silently reported "12 distinct failures" for 6 problems. It looked like it was
working. Scrubbing all numbers fixed it — and the clustering eval below exists
so it cannot break that way again without saying so.

---

## Categories, and why they are rules rather than a model

Category decides *who owns it*. A dependency resolution failure is not the same
work as a failing assertion, and routing it to the wrong person is most of what
makes triage slow.

| Category | Owner |
|---|---|
| `test_failure` | the author |
| `lint` | the author |
| `typecheck` | the author |
| `compile` | the author |
| `dependency` | whoever bumped the lockfile |
| `config` | whoever owns the workflow |
| `permissions` | repo admin |
| `timeout` / `oom` / `network` | infrastructure |
| `flaky_candidate` | nobody yet |
| `no_diagnostic` | whoever owns the workflow |

The rules are auditable, free, instant, and — measured below — accurate enough
that the model's job is *explaining* a failure rather than identifying one.

`no_diagnostic` is a real verdict, not a fallback. "This job failed and printed
nothing useful" is actionable: the fix is to make the workflow say why.

---

## Usage

```bash
pip install -e .

ci-triage run   psf/requests 34145371878    # triage one failed run
ci-triage run   pallets/flask               # most recent failure, if no id given
ci-triage watch pallets/flask --runs 25     # cluster recent failures
ci-triage watch myorg/myrepo --fail-on-recurring   # exit 1 if anything recurred
ci-triage run   psf/requests --explain      # add a Claude narrative
```

Uses the `gh` CLI if present, otherwise `GITHUB_TOKEN`. Job logs need a token even
for public repos — that is a GitHub rule, not a choice here.

`--fail-on-recurring` is the interesting one: put it on a schedule and the
pipeline itself complains when a failure stops being a one-off.

### The optional LLM layer

`--explain` sends the already-selected evidence to Claude for a narrative. It is
deliberately the thin layer. Identifying the category, isolating the evidence and
clustering the history are deterministic, auditable and free; the model is asked
only for the why and the what-next, on evidence it did not choose.

Needs `pip install 'ci-triage[llm]'` and credentials. Everything else works
without.

---

## Evals

```bash
python3 evals/run_eval.py
```

```
  failure classification
    accuracy                 100.0%
    correct                  22/22
    per label:
      compile          2/2      lint             3/3
      config           1/1      network          1/1
      dependency       2/2      test_failure     9/9
      typecheck        2/2      unknown          2/2

  signature clustering
    fixtures                 22
    distinct_signatures      22
    deterministic            100.0%
    over_clustered            0
```

22 real failed jobs from 9 public repositories — Flask, requests, pytest, numpy,
urllib3, SQLAlchemy, Starlette, FastAPI, Black — hand-labelled and saved as
fixtures. Fixtures rather than live run IDs, because GitHub expires logs after 90
days and an eval that rots is not an eval.

**The first run scored 59.1%.** The eval is what found the other 41%:

| What it caught | Why the rule was wrong |
|---|---|
| A pytest test asserting about `pexpect.exceptions.TIMEOUT` read as an infra timeout | matched the bare word `timeout` |
| Two mypy failures read as `unknown` | no pattern for `file.py:123: error:` |
| A formatter's unified diff read as a test failure | matched `assert ...` *inside* the diff content |
| A Dependabot job read as `typecheck` | the job was *bumping mypy*, so the word appeared as data |
| Two Docker build failures read as `unknown` | no pattern for buildkit step output |

That last one is the general lesson, and it applies well beyond CI: **a tool name
appearing in a log is a mention, not a diagnostic.** Four of the five misses were
some version of matching a word in the wrong context.

The clustering eval scores both directions on purpose. Over-clustering — merging
failures that are genuinely different — is worse than not clustering at all,
because it hides a real regression inside a known-flaky bucket.

**Caveat worth stating:** 22 cases is a small set, drawn from Python projects. The
number is real but it is not a claim about Java, Go, or monorepo CI.

## Tests

```bash
python3 tests/test_core.py     # 13 checks, no network
```

Covers the invariants that must hold whatever a log contains: same failure plus
different durations gives the same signature, different failures do not collide,
ANSI codes do not change anything, and all 22 real fixtures parse without
crashing.

---

## Limitations

- **GitHub Actions only.** The signature and classifier ideas port to any CI; the
  fetching layer does not.
- **Logs expire after 90 days**, so `watch` over a long window will report jobs it
  could not read rather than pretending they did not exist.
- **Rules are tuned on Python-ecosystem CI.** Expect to add patterns for other
  stacks. They live in one list in `classify.py` and each is one line.
- **`flaky_candidate` is a hint, not a verdict.** Real flake detection needs
  pass/fail history per test, not log text.

## License

MIT
