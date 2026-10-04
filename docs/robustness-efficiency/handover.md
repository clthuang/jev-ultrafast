# Handover: robustness and efficiency work (2026-10-04)

Branch `claude/busy-edison-lx8bhh`, draft PR #2, checkpointed at `b868634` when the session's credit ran low. The
detailed ledger, with every command, count and review, is [status.md](status.md); this page is the summary.

## Done

| Stage | Commit | Evidence |
| --- | --- | --- |
| Consolidation of the earlier branches into main | #1, `a94014b` | 90 earlier plan nodes re-run in the cloud and passing |
| REVIEWS: review-pipeline defects, GATE-REVIEWS | `11ecf9f` | Two independent reviewers READY after 3 rounds; 34 findings each pinned by a test |
| SNAPSHOT: schema-2 snapshots, GATE-SNAPSHOT | `0e48727`, `acbef8d` | About 38 KB per read where schema 1 sent 1.58–30.89 MB; native parity on 17 mutations; reviewer READY |
| READINESS: the loading wait and busy-page rereads | `952ef93` | 45 named nodes / 48 variants; 48 mutants caught; native composition, 5/5 busy-page runs and 6 loading cases in headless Chromium |
| RELEASE-3 draft: storage migration tool and rehearsal | `f476832` | 15 tests, the rollback export read by the frozen baseline code; the rehearsal passes on two disposable stores with no paid launch |

At `f476832`: 801 offline tests, 40 native tests, 25 live guard checks, the wheel smoke check, Ruff, `node --check` and
`uv build` all pass.

## Remaining, in order

1. **GATE-READINESS.** Re-run its two independent reviews: execution semantics and concurrency, then the browser, lab
   and doc claims. Both were stopped unfinished to save credit. Fix their findings, then mark the gate done.
2. **RELEASE-1.** Reconcile README and the docs with the shipped API, statuses and limits. A docs audit was started and
   stopped too; re-run it.
3. **RELEASE-2.** All checks at one commit, every plan stage's nodes with `--native`, an independent review of the
   whole change, and a premortem with fault injection.
4. **RELEASE-3.** Independently review the drafted tooling, and re-run `scripts/rehearse_activation.py` at the release
   commit.
5. **GATE-RELEASE.** The change summary, the migration notes and the reviews; then PR #2 is ready to merge.

All of this can run in a cloud session. Activating your real review store cannot: it runs on your Mac, with
[activation-runbook.md](activation-runbook.md).

## Decisions I need from you

1. **The loading wait with your own Chrome.** Chrome 144+ asks "Allow remote debugging?" for each new DevTools
   connection, and the wait needs one of its own.
   - Built default: on with an explicit endpoint (`BU_CDP_URL`/`BU_CDP_WS`), and off with your own Chrome unless
     `JEV_LOADING_GATE=1`.
   - The alternative: on by default, at the cost of one extra approval per server start.
   - Recommendation: set `JEV_LOADING_GATE=1` once on your Mac and run one goal. If the single extra prompt is
     acceptable, make it the default; that is where false DONEs on late-loading results happen. The prompt cannot be
     tested in the cloud.
2. **Paid live-site checks.** The loading wait's live acceptance (Google Flights, DuckDuckGo, crates.io and YouTube,
   10 trials each) and H5 on arXiv need live sites and model calls, so they were not run.
   - Choose: authorize them with a budget cap, or ship with them recorded as unverified.
   - Recommendation: run the Google Flights arm before claiming the fix works on live sites.
3. **The review backlog after activation.** Old review digests are history, not acknowledgments. So after activation,
   reviews re-send runs the old code already reviewed: at most 25 runs a day, each review capped at $0.50, and only
   runs from 2026-09-27 on for automatic reviews.
   - This is the plan's accepted choice.
   - Choose: confirm it, or ask for the migration to mark those runs acknowledged. That is a design change, and needs
     its own review.
4. **When to activate the real store,** after GATE-RELEASE. It means stopping your running `jev-mcp` servers for a few
   minutes, backing up `artifacts/` and migrating it, as the runbook says.

## Not verifiable in the cloud

- Chrome's approval prompt.
- Writer detection on macOS (`ps`/`lsof`; the rehearsal used Linux `/proc`).
- The live-site trials.
- Your real store.
