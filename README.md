<img src="docs/banner.svg" alt="Jev Ultrafast · Browser Use × TypeSafe" width="100%" />

# Jev Ultrafast ⚡

> [!IMPORTANT]
> **The Browser Use Cloud waitlist is open.** Get early access to ultrafast browser agents in the cloud.
> **[Join the waitlist →](https://browser-use.com/ultrafast?utm_source=github&utm_medium=readme&utm_campaign=jev-ultrafast)**

**A browser agent with a dynamic, indexed action space.**

Give it one goal. [TypeSafe's Jev](https://docs.typesafe.ai/introduction) picks an operation and an element. A small LLM writes text only when the operation is `TYPE_TEXT`.

**Zürich → London on Google Flights in 7.1 seconds** in the recorded run (commit `452c1ad`). One natural-language goal, actual text generation, and loading waits included.

<a href="docs/demo.mp4"><img src="docs/demo.gif" alt="A real Google Flights search at 1× speed, with generated city names and dynamic operation/target decisions" width="100%" /></a>

[Watch the MP4](docs/demo.mp4) · [Measurements](docs/performance.md) · [Read the loop](jev_ultrafast/agent.py)

## The action space

Every observation produces a new element table:

```text
[1] button    Change ticket type · Round trip
[2] combobox  Where from?        · San Francisco
[3] combobox  Where to?          · empty
[4] textbox   Departure          · empty
...
```

The operations are `CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_UP`, `SCROLL_DOWN`, `WAIT`, `DONE`, and `BLOCKED`. Only supported operations and targets are offered.

```text
                      one TypeSafe request
                     ┌─────────────────────────────────┐
page → element table → operation                       │
                     │ click_target                    │
                     │ type_text_target                │
                     │ select_target, if present       │
                     │ commit, per click/select target │
                     └─────────────┬───────────────────┘
                         use the matching target
                                   │
                    CLICK [7] ─────┤──→ commit? stop : browser
                TYPE_TEXT [3] ─────┘
                          ↓
                   small LLM → text → browser
```

Target questions are speculative. If the operation is `CLICK`, only `click_target` can execute. A yes/no commit question per click or dropdown target asks whether it would pay, buy, book, send, delete, or change account settings. Only the chosen target's answer is read, and a likely commit stops before input unless the caller passed `allow_commit`. Three decisions, **one network round trip**. Each target head contains only compatible elements. Native dropdown choices carry an observed element/option index.

There are no site-specific action scripts or prepared field strings in the policy. The Flights example supplies a goal and independently verifies the outcome. The screenshot renderer adds labels afterward; it does not drive the browser.

## Try it

```bash
git clone https://github.com/browser-use/jev-ultrafast.git
cd jev-ultrafast
uv sync
cp .env.example .env
# Add TYPESAFE_API_KEY and TEXT_MODEL_API_KEY.
uv run jev
```

Open **http://127.0.0.1:8766** and click **Start demo → Run automatically**. The inspector shows numbered elements, operation probabilities, target probabilities, and executed actions. **Choose next** pauses before execution.

Chrome connects through [Browser Harness](https://github.com/browser-use/browser-harness), installed by `uv sync`. Run `uv run browser-harness --doctor` if it needs connecting. Allow remote debugging in Chrome when prompted. Each run works in its own Chrome window, opened behind yours without taking keyboard focus; `JEV_BACKGROUND_TAB=1` in `.env` uses a hidden tab in your current window instead. To watch a run, `run_goal`'s `foreground_window=true` brings its window to the front before the first step.

`TEXT_MODEL_API_KEY` is an OpenRouter key in the example configuration. The current demo uses `inception/mercury-2.5` with reasoning disabled. Gemini, GLM, and DeepSeek can also use the OpenAI-compatible text helper; configure the appropriate model, endpoint, and reasoning setting.

## Use the library

```python
from datetime import date, timedelta

from jev_ultrafast import Agent

departure = date.today() + timedelta(weeks=4)
with Agent(
    "https://www.google.com/travel/flights?hl=en",
    f"Find one-way flights from Zurich to London on {departure:%B} {departure.day}, {departure.year}, "
    "for one adult in economy. Stop when matching flight options are visible.",
    allowed_operations=["CLICK", "TYPE_TEXT", "SELECT", "SCROLL_UP", "SCROLL_DOWN", "WAIT"],
) as agent:
    for state in agent.run():
        print(state["elapsed_ms"], state["status"])
```

Run with `uv run --env-file .env python your_script.py`. Every goal, including `new_goal` and MCP continuations, requires an explicit `allowed_operations` list. Use `[]` for observation and terminal answers, or `["WAIT"]` to also wait. Element numbers and visible field evidence stay the same under restricted policies. The executor checks permissions before text generation and input; `allow_commit` cannot broaden them. Explicit starting-URL navigation is separate setup. Invalid goals or policies preserve the previous run. Refused choices stop with `operation_not_allowed` and saved diagnostics; older reports say `legacy: policy not recorded`.

Every run, including the inspector's, stops before input on a site other than its start site unless `allowed_sites` names it. The same policy can run a different task:

```bash
uv run --env-file .env python examples/run.py \
  --url https://en.wikipedia.org/wiki/Main_Page \
  --allowed-operations CLICK TYPE_TEXT SELECT SCROLL_UP SCROLL_DOWN WAIT \
  --goal 'Find and open the Wikipedia article about Gödel’s incompleteness theorems.'
```

`uv run --env-file .env python examples/flights.py --keep-open` performs the flight search, checks the actual route/date/results, and saves its trace. It does not select or book a flight.

## Use from Claude Code

```bash
claude mcp add jev-ultrafast --scope user -- uv run --directory /path/to/jev-ultrafast jev-mcp
```

Claude delegates a bounded browser sub-goal with `run_goal`, checks the returned page and screenshot, and labels the run with `report_outcome`. When a page waits for you, such as for a sign-in or a passcode, Claude brings its window up with `show_window` and asks you to finish there. The executor stops before a likely payment, booking, message, deletion, or account change unless Claude passes `allow_commit`. Each run is saved to `artifacts/runs/`; `uv run python scripts/report_runs.py` summarizes them. Runs that stop for one of four recognized causes get a failure code, and their next step names its recovery; results show site notes from earlier runs. At most once a day, an automatic review sends scrubbed summaries of waiting runs and site notes to Anthropic, capped at $0.50, never the pages' visible text or screenshots ([exactly what is sent](docs/claude-code-integration.md#76-privacy-and-data-flows)); `JEV_AUTO_REVIEW=0` in `.env` turns it off.

## Why it moves

- **One request per decision cycle.** Operation and target heads share the same observed state.
- **No screenshots in the default agent loop.** Jev consumes structured state. The inspector opts into screenshots; the video uses a separate continuous screencast.
- **One browser call per snapshot.** Read visible controls, their names, values, and text atomically. Keep references to the actual DOM nodes.
- **Validate the selected target.** Clicks check the document, form values, target, and nearby context. Animation alone does not force another prediction. Resolve current geometry and reject covered controls before input.
- **Wait for useful state.** After typing into a combobox, wait for visible suggestions, capped at 200 ms. Other interactions get at most two animation frames or 50 ms. These reads happen after execution is logged.
- **Keep hidden tabs rendering.** Focus emulation prevents background animation throttling without switching Chrome's visible tab.
- **Send visible text.** Offscreen article bodies and footers do not fill the model context.
- **Reuse an interrupted text request.** A generated value survives a stale-page retry only if the entire text-helper input is unchanged.

Every entry path shares a 90-second execution budget beginning with the first `tick`, `predict`, or `act`.
The 120th stale outcome stops before another recovery read; a changed page does not refill that budget.
Deadline and cancellation checks prevent new input, while an already confirmed mouse or key press receives its
single matching release. Unconfirmed input is retained as an uncertain attempt and is never automatically repeated.
These limits are cooperative: HTTP phases and CDP responses are bounded by the remaining budget, while an in-flight
request or IPC connection can still finish later. Completed late model calls retain their measured latency and known
usage; missing usage is shown as unknown. MCP setup time and its one best-effort final read are reported separately;
the final read has a five-second budget and cannot resume a stopped run.

Every executed target is resolved from an observed node. The executor rechecks page freshness and click occlusion. Model output never becomes selectors, coordinates, shell commands, or executable JavaScript. Text-helper output must parse as a small JSON object before typing.

## Small enough to read

| File | Job |
| --- | --- |
| [agent.py](jev_ultrafast/agent.py) | The complete loop and text-helper handoff |
| [snapshot.js](jev_ultrafast/snapshot.js) | Atomic DOM snapshot, indexed controls, freshness guards |
| [browser.py](jev_ultrafast/browser.py) | Browser connection, current geometry, execution |
| [model.py](jev_ultrafast/model.py) | Dynamic operation/target heads and text generation |
| [questions.py](jev_ultrafast/questions.py) | Model instructions |
| [demo.py](jev_ultrafast/demo.py) | Local inspector |
| [mcp_server.py](jev_ultrafast/mcp_server.py) | Claude Code tools: `run_goal`, `report_outcome` and `show_window` |
| [site_notes.py](jev_ultrafast/site_notes.py) | Failure codes, next steps, and site notes for Claude, never for the executor |
| [review_runs.py](scripts/review_runs.py) | Reviews of recorded runs, and note approval |

## Evidence and limits

The current video is a **7,073 ms** Google Flights run, recorded at commit `452c1ad`, before the Claude Code changes. Timing starts after initial page observation and includes model calls, generated text, browser work, stale decisions, and loading waits. A fresh independent check verifies the one-way setting, Zürich, London, September 20, 2026, and visible flight options. The video plays at 1×, with no opening hold and a 0.5-second final hold.

In six alternating runs with identical models and settings, both versions passed **3/3**. Median task time went from **9.450 s → 7.092 s**, a **25% reduction**; median browser protocol calls went from **1,092 → 101**. This is three repeats of one task on one browser profile, not a general reliability benchmark.

At that commit, the policy opened the requested Wikipedia article in **2.798 s** and passed a local hotel search/filter task in **1.896 s**. Runs, failures, source hashes, and measurement boundaries are in [performance.md](docs/performance.md).

On 2026-09-24, after the Claude Code changes, six re-measured runs all passed but took 64–185 s. TypeSafe was slow that day: even one-question requests took a median 4.4 s, against 178 ms per decision in the recording. The per-target commit questions add 82% more input tokens per request; their latency effect was not resolved. The dated note in performance.md has the details.

A `DONE` choice still requires independent outcome verification. The DOM reader handles common HTML and ARIA controls, not the full accessible-name specification. Shadow roots, frames, canvas, uploads, pop-up tabs, nested scrolling, and arbitrary keyboard widgets remain outside this MVP; `run_goal` closes and reports pop-up tabs instead of following them, and dismisses JavaScript dialogs without accepting them. A pop-up still brings Chrome to the front before it is closed. Owned tabs share the existing Chrome profile.

## Development

```bash
uv run ruff check .
uv run pytest
node --check jev_ultrafast/static/app.js
node --check jev_ultrafast/snapshot.js
uv build
```

Tests are offline. `uv run python scripts/check_guards.py` checks real controls in a local browser without model calls. Live examples, recording scripts, and run reviews make paid API calls; the MCP server may start a review on its own, which `JEV_AUTO_REVIEW=0` turns off. `scripts/record_flights.py <new-folder>` captures original browser timestamps; `scripts/render_demo.py <recording-folder>` renders that verified run at 1× and crops out the Google account strip. Credentials and raw traces stay ignored.

---

[Browser Use](https://github.com/browser-use/browser-use) · [Browser Harness](https://github.com/browser-use/browser-harness) · [TypeSafe speculative fan-out](https://docs.typesafe.ai/patterns/fan-out)
