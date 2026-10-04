# Open Dots: Open-Source Personal AI Agent Workspace


<p align="center">
  <video src="https://github.com/Anil-matcha/open-dots/raw/main/assets/open-dots-demo.mp4" poster="assets/open-dots-demo-poster.png" controls muted width="800"></video>
</p>

<p align="center"><a href="https://youtu.be/hROKO0dG_a0"><img src="https://i.ytimg.com/vi/hROKO0dG_a0/maxresdefault.jpg" width="720"></a></p>
<p align="center"><a href="https://youtu.be/hROKO0dG_a0"><b>▶ Watch: Free Open Source Meta Muse Alternative: Unlimited, Any Model </b></a></p>

**Open Dots is an open-source, self-hosted personal AI agent workspace** for chat, tool use, approvals, connectors, and computer tasks. It brings model conversations, a governed action gateway, approval prompts, and an optional browser runtime into one local-first app. It can be evaluated by people searching for open-source alternatives to OpenAI Dots, Meta Muse, Grok Bot, Instinct, Manus Cue, Claude Cowork, or ChatGPT agent; it is an early prototype, not a feature-equivalent replacement for those products.

Open Dots is independently built and is not affiliated with or endorsed by OpenAI, xAI, or any model provider. It offers a self-hostable, inspectable alternative for people looking for an open-source OpenAI Dots alternative, with local data and explicit approval for higher-risk actions.

> **Status:** Prototype / active development. Intended for local experimentation; multi-user hosting and hostile-web isolation are not production ready.

## What it does

- Create assistant personas with separate instructions, model IDs, and visual identities.
- Stream chat responses, persist conversations locally, render Markdown, attach images, and dictate messages where the browser supports speech input.
- Connect to models through the included inference adapter and choose from its configured model catalog.
- Request confined workspace reads and writes or computer actions through a deny-by-default gateway. Higher-risk actions pause for approval and produce audit events.
- Connect apps through Composio, with explicit OAuth and narrow GitHub issue lookup/create actions.
- Search the web from chat with `/search <query>`. It runs through the governed action gateway like the other tools, works with the keyless You.com free profile, and produces audit events.
- Run an optional bot-scoped Docker/Playwright computer runtime or connect a compatible remote computer service.
- Keep application state in SQLite and encrypt provider credentials at rest.

## Why Open Dots

Open Dots gives developers and individuals a self-hosted AI workspace they can inspect and adapt. It is an open-source alternative for people who want local-first conversation storage, configurable model access, visible approval steps, and an optional computer runtime under their control. It is a separate project with its own implementation and limitations; see the provider and runtime notes below before deploying it.

## Quick start

### Requirements

- Node.js and npm
- Python 3.10+ and pip
- An inference API key and base URL for live model responses

Clone and start the API:

```bash
git clone https://github.com/Anil-matcha/open-dots.git
cd open-dots/server
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export MODEL_API_KEY="your_api_key"
export MODEL_API_BASE_URL="https://your-inference-host.example/api/v1"
python run.py
```

The API is available at `http://127.0.0.1:8000`; interactive docs are at `/docs`.

In a second terminal, start the web client:

```bash
cd open-dots/client
npm install
npm run dev
```

Open `http://127.0.0.1:3000` and sign in with the Open Dots owner token. On first start, the server creates `.auth-token` under `DATA_DIR` (default `~/.open-dots`). Read that file locally and paste its value into the sign-in form, or use the value of `APP_AUTH_TOKEN` if you configured one. This is a separate credential from your model provider API key, which you enter in App Settings after signing in. Never commit, share, or put the owner token in a public frontend environment variable.

Browser sessions use distinct HttpOnly cookies with server-enforced expiry. Sign out revokes the current session, and restarting the API invalidates all browser sessions. Direct API clients can continue to send the owner token as a Bearer credential. Loopback requests, including container gateway and reverse-proxy traffic, must authenticate too.

## Model provider

The default inference adapter sends a prediction request to `{MODEL_API_BASE_URL}/{model_id}` and uploads images to `{MODEL_API_BASE_URL}/upload_file`. Configure it with a service that implements this request and response contract and supports the model IDs you select.

Open **Settings → Model provider** and expand the collapsed panel to enter the API base URL, choose Responses or Prediction, save an API key, and configure model IDs and the default model. Use the API root (usually ending in `/v1`), without appending `/responses`. Model IDs accept one per line or comma-separated values. Saving refreshes the model menus and sets the default for newly created assistants; existing assistants keep their selected model.

For an OpenAI Responses-compatible service, choose **Responses API**. Requests stream from `/responses` with Bearer authentication, preserve conversation roles, and send attached images as data URLs. The Chat Completions protocol is not implemented. Under **Custom headers**, keep stored headers, replace the complete set, or explicitly remove them. Keys and header values are encrypted locally and are not displayed after saving; a blank API key preserves its stored value.

The same settings are available through the authenticated settings API (`POST /api/v1/settings`): `model_api_wire_api`, `model_api_base_url`, `model_api_key`, and `model_api_headers`. Use `clear_model_api_headers: true` to remove stored headers explicitly.

Set `model_ids` to the service's supported chat model IDs and `default_model` to one of those exact IDs. Both model menus use the configured catalog; the application does not rewrite model IDs. Omitted settings retain their previous values, and empty credential/header values retain stored secrets.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MODEL_API_KEY` | empty | Provider key fallback when no key is saved in settings |
| `MODEL_API_BASE_URL` | empty | Required base URL for the configured inference API |
| `DEFAULT_MODEL` | `gpt-5-mini` | Initial model for new assistants |
| `COMPOSIO_API_KEY` | empty | Optional connector credential |
| `YDC_API_KEY` | empty | Optional You.com API key for `/search`; the keyless free profile is used when unset |
| `SERPLY_API_KEY` | empty | Optional [Serply](https://serply.io) API key; when set, `/search` returns Google results through Serply instead of You.com |
| `DATA_DIR` | `~/.open-dots` | SQLite state and local keys |
| `APP_ENCRYPTION_KEY` | generated in `DATA_DIR` | Optional Fernet key for encrypted credentials |
| `APP_AUTH_TOKEN` | generated in `DATA_DIR` | Server-side owner credential for sign-in and direct API access |
| `WORKSPACE_ROOT` | project root | Directory boundary for approved workspace actions |
| `COMPUTER_PROVIDER` | `fake` | Computer provider: `fake`, `docker`, or `remote` |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | API bind address |

For non-loopback access, set `APP_AUTH_TOKEN` only on the server, use HTTPS with `AUTH_COOKIE_SECURE=1`, and set a narrow `CORS_ORIGINS` list. Configure the public API address with `NEXT_PUBLIC_API_URL`, and sign in through the form; do not embed credentials in `NEXT_PUBLIC_*` variables. Keep the UI and API on the same site so the browser can send the session cookie. The built-in session store targets one API process; sessions are not shared between workers or instances.

If you previously built with `NEXT_PUBLIC_API_TOKEN`, rotate the owner credential, remove that variable, and rebuild/redeploy the client. Existing public assets may contain the old credential. Old cookies containing the master token are no longer accepted; users must sign in again.

## Web search

`/search <query>` in chat runs a governed, read-only web lookup through the [You.com MCP server](https://you.com/docs/build-with-agents/mcp-server) and hands the results to the assistant as action context, so it can answer with current information.

- No key is required: without `YDC_API_KEY` the keyless free profile is used, which serves a reduced read-only tool set.
- Set `YDC_API_KEY` to use the authenticated endpoint with higher limits.
- Set `SERPLY_API_KEY` to send `/search` to [Serply](https://serply.io) (Google results, [API docs](https://serply.io/docs)) instead. You.com stays the default when it is unset.
- The lookup registers as `search.web` (risk `external`). Like `connector.github_list_issues`, it is an explicit, read-only command typed by the user, so it does not pause for approval; every run still produces the standard gateway audit events.

## Optional computer runtime

The default `fake` adapter is for local development and deterministic behavior. To enable the Docker/Playwright computer provider:

```bash
docker build -t open-dots-computer:1.62.1 ./runtime
export COMPUTER_PROVIDER=docker
export COMPUTER_DOCKER_IMAGE=open-dots-computer:1.62.1
```

The daemon must be running. Containers use a separate workspace per assistant, a read-only root filesystem, dropped capabilities, and resource limits. Computer navigation and other higher-risk operations go through the action gateway and approval flow. This is not a hardened sandbox for hostile websites; review network egress, image provenance, and credential exposure before using it with untrusted content.

For a remote computer service, configure `COMPUTER_PROVIDER=remote` and the `COMPUTER_REMOTE_*` variables in `server/app/config.py`.

## Architecture

```text
Next.js client ── HTTP + SSE ── FastAPI API
                                  ├── SQLite + encrypted settings
                                  ├── configurable inference adapter
                                  ├── Composio connector adapter
                                  └── action gateway + approvals + audit
                                        ├── confined workspace tools
                                        └── fake / Docker / remote computer
```

The main code areas are `client/` (Next.js UI), `server/app/routers/` (HTTP API), `server/app/services/` (providers, persistence, approvals, and tools), and `runtime/` (Docker computer driver).

## Current limitations

- One local owner; user provisioning, roles, and multi-user grants are not implemented.
- SQLite is local state; coordinated multi-instance storage and backup workflows are not included.
- Inference supports the original prediction API and Responses-compatible services; Chat Completions and a generic provider plugin interface are not implemented.
- The computer runtime is opt-in and is not a hardened security boundary for arbitrary web content.
- Connector actions are intentionally narrow; arbitrary tool discovery and writes are not implemented.
- There is no mobile or desktop client, durable memory service, or scheduled routine engine.

## Contributing

Issues and pull requests are welcome. Keep the documentation aligned with behavior, avoid committing credentials or local transcripts, and describe API or persistence changes clearly.

## License

MIT. See [LICENSE](LICENSE).
