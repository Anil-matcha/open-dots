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
| Action risk-bucket taxonomy + rule engine (allow/deny/ask) | **Not built** — this doc's core proposal |
| Inline chat-based approval prompts | **Not built** |
| Server-side outcome verification (vs. trusting the AI's self-report) | **Not built** |
| Audit trail of attempted vs. actual actions | **Not built** |
| Connector library beyond Claude/GitHub (Medium, YouTube, Discord, etc.) | **Not built**, not yet explicitly scoped in PLAN.md |
| Multiple named "employees" per user, with per-bot rules | **Not built** — requires schema changes (`bot_id` on tasks/schedules, new permission-rule table) |

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
