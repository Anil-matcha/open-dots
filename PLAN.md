# Open-Source Grok Bot / Meta Muse Alternative — Research & Plan

*As of 2026-09-27.*

## 1. Executive summary

The category (persistent personal AI agents / "AI employees") is real and growing fast — but the specific slot of "open-source alternative to Grok Bot / Meta Muse" is **already occupied by four live projects**, not empty. Three of them (Rakazo, OpenMausBot, OpenBot) were source-code-audited for this plan; OpenClaw was deliberately excluded from the deep-dive per direction. None of the three has closed the actual gap: **a genuinely non-technical, hosted (no Docker/no self-hosting), BYO-subscription "AI employees" product with a real, understandable trust layer.** All three are still either self-hosted-only, developer-oriented, or missing a shipped hosted tier despite marketing one. The recommended wedge is to build exactly that, using your existing MuAPI/Pixelrelay model-routing infrastructure as the core technical advantage, and borrowing three concrete, source-verified mechanisms from competitors: Rakazo's rule-based approval engine, OpenBot's server-side action verification (never trust the model's self-report of what it clicked), and OpenMausBot's direct CLI/API driver pattern for BYO-subscription support.

## 2. Market sizing recap

- Personal AI Assistant market: ~$4.8B (2026) → ~$19.6B (2030), 41.9% CAGR (aggressive estimates run to $78B by 2035).
- Broader AI agents market: ~$12B (2026) → ~$53B (2030); some estimates as high as $183B by 2033.
- Capital is moving fast in this exact niche: **Instinct** raised $350M at a $2.5B valuation (Aug 2026), reportedly back in talks for $1B at a **$10B** valuation weeks later. **Meta Muse** has millions of users and topped app-store charts. **Lindy** (closest "AI employee" comp) raised only $54M and had just $5.1M ARR in 2024 against ~$5B secondary chatter — a sign valuations are running well ahead of proven revenue.
- Standard caveat: market-research TAM figures are soft. Treat as "large and compounding," not precise.

## 3. Competitive landscape (source-code audited)

### Rakazo (`elie222/rakazo`) — Apache-2.0, backed by Inbox Zero Inc.
- **Maturity**: ~2,994 stars, 524 forks, 947 commits, 71 contributors but heavily concentrated (elie222 = 447 commits, an automated "cursoragent" bot = 169). Created 2026-08-13, actively developed daily. Extensive test suite incl. offline emulators for every external adapter (sandbox, cloud-agent, connector) — unusually strong test discipline for something this young.
- **Self-host reality**: genuinely painful. Requires 4 independently-generated high-entropy secrets (`BETTER_AUTH_SECRET`, `ENCRYPTION_KEY`, `SANDBOX_SUPERVISOR_TOKEN`, `SCREEN_PROXY_SECRET`), mounts the **host Docker socket** into the supervisor container (a real privilege-escalation surface), requires building a custom sandbox image, running Prisma migrations, and configuring 2-4 more secrets per messaging channel. Zero one-click deploy.
- **Permission model**: genuinely well-designed — rule-based approval engine (`packages/core/src/action-approval.ts`) with specificity ordering (tool > connector > category), regex-based verb classification for connector mutability (`send/pay/delete/charge` vs `get/list/search`), a non-bypassable `EXPLICIT_APPROVAL_BUILTIN_TOOLS` tier, and "fail closed on judge error" for consequential actions even when an LLM auto-reviewer is in the loop.
- **BYO-subscription mechanism**: real, via an external `@earendil-works/pi-ai` library. Ships actual OAuth sign-in for **Claude Pro/Max, ChatGPT Plus/Pro, GitHub Copilot, SuperGrok/X Premium** — with UI copy explicitly stating "Uses your OpenAI subscription. Rakazo does not pay." A recent commit hardens this boundary further (rejecting API keys where a subscription login is required).
- **"Cloud edition"**: **marketing only.** No Stripe, no billing routes, no waitlist backend found anywhere in the actual code. The only "cloud" plumbing that exists is a `cloud_agent_launch` feature that delegates to *Cursor's* cloud-agent API — not a Rakazo-hosted product.
- **Sandbox**: real per-bot Docker container (Debian + Xvfb + noVNC + Chromium), managed by a supervisor daemon with CPU/memory/PID caps; also supports pluggable alternate backends (e2b, Daytona, CreateOS) via a clean `sandbox-factory.ts`.

### OpenMausBot (`milind-soni/OpenMausBot`) — Apache-2.0 core, **open-core with a paid enterprise module**
- **Maturity**: ~3,607 stars, 620 forks, 2,854 commits, 91 contributors but small core team (~5-6 people; milind-soni alone = 1,440 commits). Created 2026-08-11 (~7 weeks old), 340 open issues (fast-moving). 696 test files vs. 591 source files.
- **Correction to earlier assumption**: this is **not** fully free/no-plan-gating. A separate `enterprise/` directory ships under its own source-available paid license (`OMB_LICENSE_KEY`), gating whitelabel, SSO, admin, spend budgets, and — notably — a **billing feature built for reselling** (custom sell-prices + billable CSV export). Clean open-core architecture: OSS core never statically imports enterprise code, degrades gracefully if it's absent.
- **BYO-subscription mechanism (the deepest of the three)**: it directly `spawn()`s the actual installed `claude`/`codex` CLI binary on PATH, writes prompts via stdin as streamed JSON (dodging argv length limits), and parses the CLI's own event stream. Tool permission is wired through the CLI's own `--permission-prompt-tool` mechanism — it registers itself as an MCP server the CLI calls back into. This is a real, no-proxy technical moat, not a thin wrapper.
- **"Cloud computer per bot" reality**: genuinely three tiers, not one marketing claim — (1) a real hosted VM backend ("boat.dev"/Box) with screenshot polling for full remote-desktop turns, (2) a BYO-VPS mode (Docker container over SSH), (3) plain local CLI with no VM at all. Only tiers 1-2 are true "cloud computer."
- **Permission broker**: clean ask/answer gate with a 15-minute fail-closed timeout default.
- **What doesn't transfer**: this is an Electron-desktop-first codebase (main process spawns a local server process) — not built web-native, and the CLI-shelling approach is irrelevant if you're calling provider APIs directly from a hosted backend.

### OpenBot (`CopilotKit/OpenBot`) — MIT, backed by CopilotKit (real dev-tools company)
- **Maturity**: ~5,629 stars, 737 forks, 431 commits, 31 contributors, top 5 authors = 305 of 431 commits (single-company team). Created 2026-08-17. Zero TODO/stub hits across the repo — unusually clean for an "Alpha."
- **Positioning**: explicitly enterprise/organizational ("the AI assistant your company can actually own"), framework-agnostic via the real AG-UI protocol (13 separate framework adapters — LangGraph, CrewAI, Mastra, Pydantic AI, etc. — each with its own Dockerfile and tests, not stubs). Self-declared "a template, not a product."
- **Best-in-class governance model (the single most useful thing to borrow)**: a real CEL-based policy engine (`server/src/computer/policy.ts`) where deny rules are checked before allow rules, and a *broken* rule (throws, or returns non-boolean) still counts as a match — i.e. fail-closed on error, not just fail-closed on absence. Critically: **the system resolves "what was actually clicked" server-side from its own snapshot, never trusting the agent's self-reported claim** — this is a direct, portable defense against a model lying about or misdescribing its own actions. The audit row is written *before* the policy decision is honored, so every attempted action is logged regardless of outcome.
- **Isolation**: real Docker-per-bot containers when deployed with its supervisor; falls back to a single Playwright browser-profile-per-bot (explicitly documented as *not* real isolation) when run standalone on a laptop — an honest but confusing two-tier model.
- **Human takeover**: a real state machine (holder = bot or person, TTL'd handoff requests, forced snapshot invalidation on handback) — solid design, not superficial.
- **Requires**: Docker, Bun 1.3+, a CopilotKit Intelligence project, and your own LLM key — still fully a developer tool, not consumer-facing.

### OpenClaw
Excluded from this round's source audit per direction. Known from prior research: ~380K+ GitHub stars, MIT-licensed, self-hosted (Docker/VPS), messaging-first (WhatsApp/Telegram/Discord), supports named sub-agents via `sessions_spawn`. Confirmed independently (via multiple hosting write-ups) to require real DevOps competence to run — several third-party managed-hosting services exist specifically to hide that complexity for a fee ($3-50/month).

### Comparison

| | OpenClaw | Rakazo | OpenMausBot | OpenBot |
|---|---|---|---|---|
| Stars | ~380K | ~3,000 | ~3,600 | ~5,600 |
| License | MIT | Apache-2.0 | Apache-2.0 core + **paid enterprise** | MIT |
| Backing | Solo dev origin | Inbox Zero Inc. | Small team (~5-6) | CopilotKit (co.) |
| Self-host required | Yes (Docker/VPS) | Yes (Docker + 4 secrets + socket mount) | No (signed installer) but desktop-only | Yes (Docker + Bun) |
| Hosted/managed tier that actually exists in code | 3rd-party only | **No** (marketing only) | No (BYO VPS/Box instead) | No |
| BYO-subscription (Claude/Codex/Grok login, not just API key) | Partial | **Yes, OAuth, 4 providers** | **Yes, drives real installed CLI** | No (API key only) |
| Governance/permission engine | Config-file based | Rule-based, well-designed | Ask/answer + CLI-native | **Best-designed (CEL, fail-closed, server-verified)** |
| Target user | Technical | Prosumer/technical | Technical (despite easy install) | Enterprise/developer |
| Monetization live today | 3rd-party hosting only | None | **Yes — enterprise reselling module** | None |

## 4. The gap

None of the four has shipped **all** of: (a) zero self-hosting — fully hosted for the user, (b) genuinely non-technical onboarding (no Docker, no secrets, no CLI knowledge assumed), (c) real BYO-subscription support (not just API keys), (d) a trust/permission layer that's simple enough for a non-technical person to understand and configure. Rakazo and OpenMausBot both have real BYO-subscription plumbing but require self-hosting or a desktop-first technical setup. OpenBot has the best governance model but is explicitly enterprise/developer-only and self-hosted. This four-way split — instead of one competitor doing all of it — is the actual opening.

## 5. Product plan

### 5.1 Architecture (borrow, don't reinvent)
- **Governance layer** — port OpenBot's model conceptually, not its CEL syntax: intent-based action taxonomy (activate/type/navigate/read/write/run_command) exposed to non-technical users as plain-language toggles ("never let this bot send money or delete files"), compiling underneath to the same deny-before-allow, fail-closed-on-error rule evaluation. Server-side resolution of "what was actually done" (never trust the agent's self-report) is non-negotiable — this is OpenBot's single best idea and the cheapest to copy.
- **Approval engine** — Rakazo's specificity-ordered rule model (tool > connector > category) plus a regex-based mutability classifier for connector actions (send/pay/delete vs. get/list/search) as a zero-config default that's safe out of the box, with a non-bypassable tier for the highest-risk actions.
- **BYO-subscription driver layer** — OpenMausBot's pattern is the right one technically (a clean provider-adapter contract with typed error codes: `missing_cli`, `invalid_credentials`, `inactive_subscription`), but adapted for a **hosted** context: instead of shelling out to a local CLI binary, talk to provider APIs/OAuth directly server-side, using Rakazo's OAuth-based subscription sign-in flow (Claude Pro/Max, ChatGPT Plus/Pro, SuperGrok/X Premium) as the reference implementation.
- **Sandbox/compute layer** — this is where MuAPI/Pixelrelay infrastructure becomes the actual moat: you already operate model/provider routing, failover, and billing plumbing. Point that same routing discipline at agent compute (managed sandbox APIs — e2b/Daytona-style — rather than owning Docker-in-Docker yourself, which both Rakazo and OpenBot's own code show is real operational risk: Rakazo mounts the host Docker socket into its supervisor, a privilege-escalation surface worth avoiding even internally).
- **Audit trail** — write the audit row before honoring any policy decision (OpenBot's ordering), so refused actions are logged too.

### 5.2 What NOT to build
- Don't build Electron-desktop-first (OpenMausBot's mistake for a hosted product) — web-native from day one.
- Don't self-manage Docker-in-Docker with a mounted host socket (Rakazo's real security exposure) — use a managed sandbox provider.
- Don't expose raw policy syntax (CEL, regex rules) to end users — that's OpenBot's own gap, and exactly the simplification opportunity.
- Don't assume API-key-only BYO support is enough — Rakazo's OAuth-subscription-login pattern is the credibility bar now that it exists in the wild.

### 5.3 Leveraging MuAPI/Pixelrelay specifically
- MuAPI's existing provider-aggregation/failover logic maps almost directly onto the "BYO-subscription or bring-your-own-key across Claude/Codex/Grok/local models" layer every competitor above has independently built from scratch.
- Pixelrelay's async-failover-across-generative-APIs thesis is the same shape of problem as "keep an AI employee's task running smoothly across flaky model/tool calls" — this is a genuine, non-obvious existing asset none of the four competitors have.

## 6. Go-to-market and monetization
- Free hosted tier funded the way opencode funds "Zen" — a model-access markup/routing fee, not a seat-based SaaS price. This is a mechanism you already operate.
- OpenMausBot's open-core split (free core, paid "enterprise" reselling/whitelabel/budgets module) is a proven shape if a self-hosted tier is ever added later — but is not the primary wedge; the primary wedge is the hosted tier none of the four currently ship.
- Rakazo's own marketing already promises a "Cloud edition" that doesn't exist in code yet — there is a live, time-limited window to ship the real thing before they do.

## 7. Risks
- **Execution window is short, not long.** Rakazo, OpenMausBot, and OpenBot are all six-to-seven weeks old and shipping fast (Rakazo pushed code the same day this research was done). Any of them could close this exact gap within weeks.
- **Anthropic has already blocked some third-party subscription-login flows** for Claude Pro/Max in early 2026 — Rakazo's own recent commit ("reject API-key credentials for ChatGPT-subscription Codex") shows this exact boundary is actively being tightened industry-wide. Confirm current ToS before building a product that depends on it.
- **Managed sandbox costs** (e2b/Daytona-style) at scale need real unit-economics modeling against the model-routing margin — this determines whether the free hosted tier is sustainable.
- **OpenMausBot's enterprise reselling module** is direct evidence a well-resourced competitor is already targeting the "resell model access to your own customers" business model you'd also want — not a greenfield monetization idea either.

## 8. Suggested timeline
- **Weeks 1-2**: Thin hosted MVP — one bot type, OAuth-based BYO-subscription (Claude + Codex only), plain-language permission toggles, managed sandbox (e2b or similar), no self-hosting option at all.
- **Weeks 3-6**: Add named multi-bot "employees" with concrete use-cases (mirror Rakazo's clarity here — inbox manager, research desk, meeting follow-ups), server-side action verification, full audit trail.
- **Weeks 7-10**: Add Grok/local-model support, refine approval-engine defaults, begin monetizing via model-routing margin.
- Ongoing: watch Rakazo's actual Cloud-edition ship date and OpenMausBot's enterprise-module growth as the two most direct threats to this window.

## Sources
All source-code findings above came from direct `git clone --depth 1` inspection of `elie222/rakazo`, `milind-soni/OpenMausBot`, and `CopilotKit/OpenBot` on 2026-09-27, plus `gh api` metadata for star/commit/contributor counts. Market figures from web research the same day (Research and Markets, market.us, Precedence Research, TechCrunch, PYMNTS, Yahoo Finance, GetLatka/Crunchbase for Lindy).
