# Robustness and efficiency: status and continuation

This file is the ledger for [the implementation plan](../robustness-efficiency-implementation-plan.md). It replaces
the handover's machine-bound ledger (`artifacts/robustness-efficiency-implementation/<run_id>/progress.json` on the
original Mac, preserved in history at `1bb0449:docs/handover/2026-10-04/continuation/progress.json`). The plan's
contracts, task boundaries and acceptance criteria are unchanged; only where work runs and how evidence is kept
changed, as §2 and §3 record.

## 1. Task status

| Stage | Tasks | Status | Evidence |
| --- | --- | --- | --- |
| Baseline | SETUP-1…3, GATE-BASELINE | Done, 2026-10-03 | Original machine: 34 harness tests, native egress proof (zero forbidden connections), production files hash-identical |
| Policy | POLICY-1…3, GATE-POLICY | Done, 2026-10-03 | Original machine: 10 named nodes, 274 focused tests; reviewer `browser_review` READY |
| Select | SELECT-1…2, GATE-SELECT | Done, 2026-10-03 | Original machine: 333 offline + 30 native; 19 changed-state cases reject before input; reviewer `execution_review` READY |
| Limits | LIMITS-1…2, GATE-LIMITS | Done, 2026-10-04 | Original machine: 15 named nodes / 45 variants, 422 focused tests; reviewer `browser_review` READY |
| Prerequisites | PRIVACY-1, RUNS-1 | Done, 2026-10-04 | Original machine: 32 and 338 focused tests; reviewer `execution_review` READY |
| Reviews | REVIEWS-1…7, GATE-REVIEWS | In progress | See §4 |
| Snapshot | SNAPSHOT-1…2, GATE-SNAPSHOT | Not started | — |
| Readiness | READINESS-1…3, GATE-READINESS | Not started | — |
| Release | RELEASE-1…3, GATE-RELEASE | Not started | — |

Re-run in the cloud on 2026-10-04 at `a94014b` (main after consolidation): every plan-named node through REVIEWS-7
exists and passes — 90 nodes, 244 variants, none skipped or xfailed, the 3 native SELECT nodes included
(`scripts/plan_tests.py SETUP POLICY SELECT LIMITS PRIVACY RUNS REVIEWS --native`). The full offline suite passes
(597) and the full native suite passes (30). This re-run confirms the earlier gates still hold on the consolidated
tree; it is not a substitute for GATE-REVIEWS' independent review.

## 2. Building and testing in the cloud

**Can this be implemented and tested in a cloud container? Mostly yes, with three explicit limits.**

What works here (verified 2026-10-04, Linux container, Playwright Chromium 141 headless):

- **All offline work.** Every runtime change in the remaining stages is Python or in-page JavaScript, and the
  plan's correctness checks are offline tests with fakes, a fake clock and the node-based snapshot harness.
- **Native browser checks.** `scripts/validation_lab.py` starts an owned headless Chrome with a fresh profile, a local
  fixture server and a deny-by-default proxy; every other destination is refused and audited. It needed three
  portability fixes (no sandbox only as root, `/proc`-based process identity, an explicit browser path). All 30
  native tests pass; `validation_lab.py run` closes the lab even when tests fail.
- **Evidence and review.** Git commits identify every source state; independent reviewers are fresh agents given a
  fixed commit and scope.

What cannot be validated here, and stays an explicit limit in every gate report:

1. **Live sites and paid models.** No `TYPESAFE_API_KEY`/`TEXT_MODEL_API_KEY` exist here, the plan authorizes no paid
   call in these stages, and datacenter IPs see consent and bot pages that make Google Flights timings
   unrepresentative. Performance claims need the separate paid protocol in the plan's §8.
2. **Headful, user-profile behaviour.** Window placement and focus (`foreground_window`, `show_window`, the background
   window), extensions such as 1Password, and a signed-in profile behave differently in headless Chrome. The lab
   proves DOM, CDP, freshness, SELECT and network-readiness logic, not these.
3. **Production activation.** The live `jev-mcp` servers and the real `artifacts/` store are on the user's machine.
   RELEASE-3 rehearses detection, backup, migration and rollback on disposable state; the real activation is the
   user's step, with the runbook.

## 3. How evidence is kept now

- **Source identity is a commit SHA**, replacing the hash manifests that guarded a separate candidate directory.
  There is no live writer in the container, so SETUP-3's isolation concern does not arise here; it returns at
  activation (RELEASE-3).
- **Each gate records**, in §1 and its stage section: the commit, the exact commands, exit status and counts, the
  named-node result from `scripts/plan_tests.py`, the reviewer's scope and verdict, and every finding's resolution.
  Raw logs are not committed; each is reproducible by re-running the command at the recorded commit.
- **Named acceptance nodes** are checked by `uv run python scripts/plan_tests.py <stage> [--native]`: it extracts the
  plan's Verify nodes (plus the 45 inherited readiness nodes for GATE-READINESS), fails on a missing node, an empty
  collection, or any failed, skipped or xfailed variant, and runs native nodes in a fresh owned lab.
- **Independent review** is a fresh agent with no implementation context, a fixed commit and an explicit scope,
  matching the plan's reviewer roles (`execution_review`, `browser_review`, `review_pipeline`). Blockers and
  should-fix findings are resolved before a gate closes.
- **Never counted as a pass:** a missing or skipped required case, zero tests collected, a mocked substitute for a
  native requirement, or a test whose assertions are weaker than the plan's Pass line.

## 4. Remaining work

Stage designs for SNAPSHOT and READINESS, and the REVIEWS gap audit, are being prepared from the current code and
will replace this section's list. Until then, the order and the known items are:

1. **REVIEWS (in progress).** Code and every plan-named test exist and pass. Open before GATE-REVIEWS:
   - the CLI must report complete batch input membership separately from acknowledgments, with IDs and versions;
   - a paid attempt's short review-lock transitions are non-blocking, so a concurrent manual `apply` can fail the
     attempt before spawn or discard its paid reply after launch;
   - `scripts/migrate_review_storage.py` converts only the notes file; a legacy `running` value in the review state
     would block every later paid dispatch with no command to clear it;
   - the handover's remaining verification items (dispatcher ownership, pre-cap eligibility, digest crash cases,
     real-pipeline privacy through actual output sinks), then independent execution/storage and reporting/privacy
     reviews.
2. **SNAPSHOT-1/2**, then **READINESS-1…3**, as the plan specifies.
3. **RELEASE-1…3**: docs reconciliation, full checks including the native suite and `scripts/wheel_smoke.py`,
   independent review and premortem, and a disposable activation/rollback rehearsal.
