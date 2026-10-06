# Governance / Permission Engine — Design Notes

*Companion to [PLAN.md](PLAN.md). Captures the reasoning behind the
governance-layer design, written up as a Q&A discussion so the "why" behind
each decision isn't lost. Read PLAN.md section 5.1 first for how this maps to
the competitor research (OpenBot's policy engine, Rakazo's approval rules).*

## 1. The core principle

**No rule means ask. Never means proceed on a guess.**

Every action the AI wants to take resolves to exactly one of three outcomes:

1. A rule explicitly allows it → proceeds automatically.
2. A rule explicitly blocks it (e.g. "never let it spend money") → refused,
   doesn't even ask.
3. No rule exists either way → **pause and ask the user**.

There is no fourth case where silence defaults to "allow." This is what
makes the system safe for a non-technical user without them having to
anticipate every situation in advance.

## 2. The engine judges actions, not tasks

The system never tries to evaluate whether a whole task ("write a poem and
post it to Medium") is safe. It only ever evaluates one *action* at a time,
at the moment the AI is about to actually do something external.

Example: "write a poem and post it on Medium" breaks into two very different
steps:

- **Write the poem** — pure text generation, nothing leaves the sandbox →
  no permission needed.
- **Call Medium's publish action** — reaches outside the sandbox, public,
  hard to reverse → requires approval.

The task's *content* (a poem) is irrelevant to the decision. What matters is
the *shape* of the action being attempted.

## 3. Risk is classified by action "bucket," not by platform

We can't predict in advance which platforms a user will ask about (Medium
today, Discord tomorrow, something we've never heard of next week). So
instead of writing rules per platform, every action any connector can
perform gets sorted, once, into a small fixed set of risk buckets:

| Bucket | Examples | Default |
|---|---|---|
| Read / look up | search, list, view | Always allowed |
| Create draft / save internally | write a file, save a draft | Low risk, generally allowed |
| Publish / send externally | post publicly, send an email/message | Ask by default |
| Move money | pay, subscribe, charge a card | Ask by default, can be made non-bypassable |
| Delete / destroy | delete a file, remove an account | Ask by default |
| Run arbitrary system commands | shell commands, installs | Ask by default |

**Who assigns an action to a bucket, and when?** Developers, at the time a
connector is built — not the end user, and not on the fly per task. When we
build the Medium connector, we tag "publish" as *publish/send externally*
and "list my drafts" as *read*, once. Every future task that happens to
touch Medium's publish action inherits that same classification
automatically. New tasks are never novel to the engine as long as the
underlying action was already bucketed — the novelty is in the task, never
in the bucket.

For actions with no dedicated connector (e.g. driving a website via clicks,
or raw shell commands), pattern-matching provides a generic safety net
(e.g. commands matching `rm`, `DROP TABLE`, outbound POST requests get
bucketed as delete/send even without bespoke integration code). Anything
genuinely unrecognized defaults to the most cautious bucket — ask — rather
than being assumed safe.

## 4. Rule specificity

When more than one rule could apply, the most specific one wins:
tool-specific rule > connector-specific rule > general bucket default
(borrowed directly from Rakazo's approval-engine design, see PLAN.md §3).
E.g. "always allow Medium posts" beats a generic "ask before any publish"
default, without needing to touch the general rule.

## 5. How rules get set (non-technical UX)

**No upfront configuration wizard.** A new user isn't asked to fill out a
permissions matrix before they can use the product — that requires
predicting needs they can't yet picture.

Instead:

- **First-run setup is minimal**: 2-3 unmissable toggles for the highest-risk
  buckets only (e.g. "never let it spend money," "never let it delete
  files"), already set to safe defaults. Nothing connector-specific.
- **Rules are created reactively**, as a side effect of answering real
  approval prompts. When an action with no matching rule comes up, the user
  sees an inline prompt in the same chat, e.g.:

  > 🔔 This task wants to **publish "My Poem" to your Medium account**.
  > `[ Allow once ]` `[ Always allow Medium posts ]` `[ Deny ]`

  Tapping "Always allow" creates a standing rule without the user ever
  visiting a settings page.
- An optional settings/history page lets a user review or revoke
  accumulated rules later, but it's never a gate blocking first use.

## 6. Server-side verification ("don't trust the AI's self-report")

The AI's own claim about what it did ("I published your poem") is never
treated as truth. After a risky action executes, the system independently
checks the *actual outcome* against a source that can't lie:

- Where a clean API exists (Medium, Gmail, YouTube), the platform's own
  response is ground truth — a real post ID/URL back from Medium means it
  really published; an error code means it didn't. This is plain,
  deterministic backend code, **not** a second AI reviewing the first one's
  work — asking another model to grade the first model's claim just moves
  the same trust problem up one level.
- Where no clean API exists (raw UI-clicking), the fallback is a screenshot
  compared against expected page state — weaker than an API check, but
  still not reliant on the acting AI's own narration.

This entire mechanism is invisible to the user — it's what allows a "✅
Done" message to actually be trustworthy without the user ever having to
check anything themselves. Any optional audit-trail/history view is a
byproduct of this, not the mechanism itself.

## 7. Connectors: who builds them, and for which platforms

- **Developers build connector integrations ahead of time**, one per
  platform (Medium, YouTube, Gmail, Discord, etc.), the same way "Connect
  Claude" and "Connect GitHub" already work in the current codebase
  ([ConnectClaude.tsx](../code/frontend/components/ConnectClaude.tsx),
  [ConnectGitHub.tsx](../code/frontend/components/ConnectGitHub.tsx)) — user
  clicks Connect, logs into their own account via that platform's own login
  screen, no API key ever touches the user.
- We don't need to predict which platforms a given user will want — we
  build a growing library of the most common ones (like Zapier/IFTTT's app
  directory), and expand based on demand.
- If a task needs a platform with no connector yet, the assistant either
  asks for an alternative ("not connected to X yet — post to Medium
  instead?") or falls back to generic browser-driving with weaker
  (screenshot-based) verification.
- **Scope note**: PLAN.md itself only specifies OAuth-based BYO-subscription
  for *AI providers* (Claude/ChatGPT/Grok) and GitHub. Building a broader
  connector library for content/publishing platforms (Medium, YouTube,
  Discord, etc.) is an extension of that idea, not yet an explicitly scoped
  item in PLAN.md — worth a deliberate scope decision before committing to
  it.

## 8. Multiple named "employees" instead of one assistant

**User perspective**: instead of a single do-everything chat, the user
manages a list of named bots/employees (e.g. "Inbox Bot," "Research Bot"),
each with its own job, its own chat/task history, and its own permission
rules.

Creating one:

- **Templates** (e.g. "Inbox Manager," "Research Desk," "Social Poster")
  come with sensible default permissions pre-filled for that job — this is
  what avoids asking a non-technical user to invent rules from scratch.
  Even a template's defaults stay conservative (e.g. Inbox Manager can
  read/draft freely, but sending still asks by default).
- **A "Custom / blank" option** starts with zero rules — not crippled, just
  maximally cautious: by the rule in §1, it will ask about every risky
  action it ever attempts until it accrues its own rule set through use,
  the same organic way described in §5.
- Open question worth deciding: should template defaults be editable
  *before* first use (so a cautious user can tighten them upfront), or only
  after seeing the bot in action? Leaning toward upfront-editable, since
  otherwise a user who wants stricter-than-default has no way to say so
  until after something has already happened.

**Developer perspective — what this changes in the current codebase**
([code/backend](../code/backend)):

- Today, everything hangs off a single user: one sandbox, one Claude
  credential, tasks/schedules linked directly to `user_id`.
- New concept needed: a **Bot/Employee record**, belonging to a user, with a
  name, a job description/system prompt, and its own permission rule set.
- **Tasks and schedules need a `bot_id`**, not just `user_id`, so history
  and behavior stay scoped per employee.
- **Permission rules and audit logs must be scoped per bot**, not per user —
  that's the actual point of the feature. An "always allow send email" rule
  on Inbox Bot must not silently apply to Research Bot.
- **Sandbox/credentials**: the underlying AI login (Claude) and connector
  logins (Gmail, GitHub, etc.) can be shared across a user's employees —
  no need to log in five times — but *which connectors each bot is allowed
  to use* is per-bot. Open decision: one shared sandbox per user across
  employees (cheaper) vs. one sandbox per employee (more isolation, matches
  Rakazo/OpenBot's per-bot container pattern, costs more compute per idle
  bot).
- **Templates** live as a small config/table (name, description, default
  rule set) that the "create employee" UI reads from.

This is a real schema/architecture change (new table, foreign keys threaded
through tasks/schedules/permissions) — worth scoping as its own unit of
work rather than folding into the base governance engine build.

## 9. Summary of what's genuinely new vs. what exists today

| Piece | Status |
|---|---|
| Sandbox per user, Claude OAuth login, GitHub device-flow linking, task execution, cron scheduling | **Already built** ([code/](../code)) |
| Action risk-bucket taxonomy + rule engine (allow/deny/ask), hooked into real task execution via `PermissionRequest` | **Built** — `permission_rule`/`check_permission`, wired through a `.claude/settings.json` hook (§10) |
| Inline chat-based + web-UI approval prompts, with pause/resume | **Built** — `permission_ask` table, Telegram inline buttons and a web answer endpoint both converge on one `answer_ask` function (§12) |
| Per-connector action classification beyond a flat tool→bucket map | **Built for GitHub only** (`github_classifier.py`, §12) — a `git status`/`commit`/`push` get independently governed instead of one flat `Bash` bucket. Other connectors still need their own classifier. |
| Server-side outcome verification (vs. trusting the AI's self-report) | **Not built** |
| Audit trail of attempted vs. actual actions | **Not built** (the `permission_ask`/`permission_rule` tables are a start, but nothing yet records actual post-execution outcomes) |
| Connector library beyond Claude/GitHub (Medium, YouTube, Discord, etc.) | **Not built**, not yet explicitly scoped in PLAN.md |
| Multiple named "employees" per user, with per-bot rules | **Not built** — requires schema changes (`bot_id` on tasks/schedules, new permission-rule table) |
| Real web-UI authentication | **Not built** — see open decision 5 below |

## Open decisions to resolve before implementation

1. Scope: do we commit to building out a content/publishing connector
   library (Medium, YouTube, Discord, ...), or keep the first version
   limited to AI-provider + GitHub connectors with the governance engine
   built generically enough to extend later?
2. Sandbox isolation model for multi-bot: shared sandbox per user vs.
   one per employee.
3. Are template permission defaults editable before first use?
4. For UI-only connectors with no clean API (screenshot-based
   verification), what confidence threshold triggers a "couldn't verify,
   please check manually" message instead of a false "done"?
5. Real web-UI authentication. The app already has a user concept
   (`user_id`, either a Telegram numeric id or a guest id) — every table
   including the new `permission_rules` table hangs off it — but that id is
   only actually authenticated on the Telegram side (Telegram's own servers
   supply it; a client can't fake it). On the web side it's whatever id is
   sitting in `localStorage`, with no server-side verification, per the
   original app's "Known limitations." That gap was low-stakes for the
   original tool but isn't acceptable once permission rules and audit trails
   are attached to that identity — spoofing `localStorage` would mean
   inheriting someone else's accumulated "always allow" rules, or reading
   their history. Doesn't block building the governance engine itself
   (which only needs a `user_id` to key off, same as every other table), but
   is a launch-blocker for the open-source product: needs real session/
   cookie-based auth to replace the web UI's localStorage-trusted identity
   before this ships publicly. Telegram's side of identification doesn't
   need to change.
6. Git identity inside the sandbox. The `claude` and `github` provider
   credentials are injected independently per `user_id`
   (`inject_credential_into_box`), with nothing enforcing they belong to the
   same real-world person — confirmed in testing, where a sandbox's GitHub
   CLI was correctly authenticated as the real connected account, while git
   commit authorship fell back to whatever identity the *Claude* login
   happened to carry, since no `user.name`/`user.email` was ever configured.
   Not a security issue (nothing leaked — the Claude account's own harness
   context is a visible, documented feature, not a secret), but commits made
   on a real user's behalf could be misattributed unless `start_task`
   explicitly sets a per-user git identity before running anything.
7. Classifier coverage. `github_classifier.py` is the only per-connector
   classifier today — every other `Bash` command, and every tool besides
   `Bash`, still gets the flat per-tool bucket from §3's original coarse
   map. Extending real specificity to another connector (or to non-git
   shell commands generally) means writing another classifier, not
   touching `check_permission` or the ask/answer mechanism.

## 10. How the engine actually hooks into task execution

Today a task runs as one opaque `claude -p ... --dangerously-skip-permissions`
command inside the sandbox ([task_execution_service.py](../backend/app/services/task_execution_service.py))
— the backend only sees the final JSON result, with no visibility into
individual actions as they happen. Making §2 real (judging actions, not
tasks) requires a way to intercept each tool call before it executes.

**Ruled out**: calling the Claude API directly with our own tool-use loop.
Would require either our own API key (real per-token billing) or the user's
API key (most Pro/Max subscriptions don't grant API access separately) —
either way it defeats the BYO-subscription model this whole project depends
on ([PLAN.md](PLAN.md) §5.1).

**Chosen approach**: Claude Code CLI's `PermissionRequest` hook, type
`"http"`. Before a task runs, the backend writes a `.claude/settings.json`
into the sandbox (using the sandbox API's existing `write_file`, already
used for credential injection — [box_operations.py](../backend/app/services/box_operations.py))
configuring that hook to POST to a backend endpoint whenever a tool call
needs a decision. The command template drops `--dangerously-skip-permissions`
so the hook actually fires. No MCP server needed — just a plain HTTP
endpoint ([permission.py](../backend/app/routers/permission.py)) that maps
`tool_name`/`tool_input` to `(bucket, connector, tool)`, calls
`check_permission`, and returns a decision in the shape Claude Code expects.
A decision of `"ask"` is no longer collapsed to deny — see §12 for how it's
actually answered.

Two real constraints this surfaces: (1) the sandbox is a remote box and
can't reach `localhost` — dev needs a tunnel (ngrok or similar), production
needs the backend's real public URL; (2) the hook payload carries no
`user_id`, so it's baked into the hook URL itself at write-time, along with
the `task_id` (needed so a `permission_ask` row — §12 — can be tied back to
the right task; a user can have more than one task running at once).

**A built-in gotcha worth remembering**: Claude Code auto-approves a fixed,
non-configurable set of read-only Bash commands (`ls`, `cat`, `grep`,
`diff`, and read-only forms of `git` like `status`/`log`/`diff` among
others) *before* the permission system runs at all — these never reach the
hook, regardless of what the hook or any rule says. This is why the
`github_classifier`'s "read" bucket for git verbs is effectively unreachable
for the verbs on that built-in list; it only actually matters for verbs
Claude Code doesn't already auto-approve (e.g. `git config`, which looked
read-only but isn't on the built-in list and correctly still asks).

**Rejected alternative**: `--permission-prompt-tool` (registering as an MCP
server the CLI calls back into). Works, and is confirmed as a real pattern
in the wild (OpenMausBot does exactly this — see below), but is strictly
more infrastructure than the HTTP hook for the same outcome.

## 11. Notes from competitor source code worth revisiting later

From the source-code audit in [PLAN.md](PLAN.md) §3 — flagging the specific
pieces relevant to this doc rather than re-reading the full audit each time:

- **OpenMausBot** (`milind-soni/OpenMausBot`) confirms CLI-level tool
  interception is a proven pattern: it `spawn()`s the real `claude`/`codex`
  binary and wires permission through `--permission-prompt-tool`, registering
  itself as an MCP server. Validates the general approach in §10 above, but
  we're using the simpler HTTP-hook route instead of replicating their MCP
  plumbing.
- **Rakazo** (`elie222/rakazo`)'s approval engine
  (`packages/core/src/action-approval.ts`) uses the same specificity
  ordering (tool > connector > category) as `check_permission`, plus a
  **regex-based verb classifier** (`send/pay/delete/charge` vs
  `get/list/search`) that auto-assigns a risk bucket from a tool's
  name/shape. **Now built for GitHub**: `github_classifier.py` adapts this
  idea to git's own verbs (§12) instead of requiring every connector action
  to be manually classified at build time as §3 originally assumed. Still
  worth re-reading when building the next connector's classifier.
- **OpenBot** (`CopilotKit/OpenBot`)'s audit-trail ordering: write the audit
  row *before* honoring any policy decision, so refused actions are logged
  too, not just approved ones. Apply this when building the audit trail
  (§6/§9) — `permission_ask` rows are already written before a decision is
  known (status starts `pending`), so this ordering is already followed for
  asks; a true audit trail covering allow/deny-without-asking is still open.

## 12. What's actually built: the "ask" flow, end to end

§5 described the inline-approval UX as a goal; this section records how it
was actually implemented, since the real design differs in one important
way from the original sketch: the backend and the thing a human answers
from are **different processes that only share the database** (the
Telegram bot runs its own long-polling process, entirely separate from the
FastAPI app) — so "pause and wait for an answer" can't be an in-memory
`asyncio.Event`, it has to be a database row that gets polled.

- **`permission_ask`** (`app/db/models/permission_ask.py`): one row per
  pending question — `task_id`, `bucket`/`connector`/`tool`, `status`
  (`pending` → `answered`/`expired`), `decision`, `always`.
- **`permission_ask_service.py`**: `create_ask` records the question and
  flips the task to a new `waiting_approval` status; `answer_ask` resolves
  it (writing a standing `permission_rule` if `always=True`) and resumes the
  task; `poll_for_answer` is the sleep-loop the hook endpoint blocks on
  (bounded under the hook's own timeout, defaulting to **deny** on expiry —
  consistent with §1, an unanswered question is still "no rule").
- **Two answering channels, one function**: a Telegram inline keyboard
  (`notification_service.send_permission_ask`, decoded by a
  `CallbackQueryHandler` in `telegram_bot.py`) and a web endpoint
  (`POST /permissions/ask/{id}/answer`, surfaced in the frontend's task
  card) both call the exact same `answer_ask` — whichever channel a human
  answers from, the result is identical. This matters because a web-only
  guest has no Telegram chat to be asked in at all.
- **A real bug this surfaced and fixed**: the "always allow" rule must be
  written at the *same specificity the decision was actually checked at*.
  Writing a rule scoped to a `tool` that the hook never passes into
  `check_permission` makes that rule permanently invisible — it was
  committed once (coarse `Bash`→`"system"` mapping, no real tool identity)
  and is now correct again now that the GitHub classifier makes `connector`/
  `tool` meaningful and consistently derived.
- **`github_classifier.py`**: the first (and so far only) per-connector
  classifier, turning a raw `Bash` command into `(bucket, connector, tool)`
  when it's a `git` invocation — `status`/`log`/`diff`/etc. → `read`,
  `push` → `publish`, anything else recognized or not → `create` (unknown
  verbs default to the risk-bearing bucket, not the safe one, per §1). A
  compound command (`git add . && git commit && git push`) is classified by
  its single riskiest verb. Adding a classifier for another connector is
  the only change needed to extend this pattern — `check_permission`'s
  specificity model and the ask/answer mechanism don't change at all.
