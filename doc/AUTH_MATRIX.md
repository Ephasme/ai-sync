# MCP Authentication Matrix

> Research date: February 2026
> Sources: official documentation for each client and MCP server, community forums, ai-sync client adapter source code

---

## TL;DR

|                   |               **Codex**                |             **Gemini CLI**             |                 **Cursor**                 |
| ----------------- | :------------------------------------: | :------------------------------------: | :----------------------------------------: |
| **Slack**         |            🔶 `mcp-remote`             |            ✅ native OAuth             |          ✅ native (partner app)           |
| **Notion**        |          ✅ `codex mcp login`          |                ✅ auto                 |                  ✅ auto                   |
| **Google Maps**   | 🔶 `mcp-remote` or `env_http_headers`¹ | ✅ `headers` (API key) or native OAuth | 🔶 `headers` (static only) or `mcp-remote` |
| **workspace-mcp** |                ✅ stdio                |                ✅ stdio                |                  ✅ stdio                  |

¹ `env_http_headers` is a Codex config field not yet exposed in the ai-sync model.

Legend: ✅ works natively out of the box · 🔶 requires a workaround · ❌ not supported

---

## Part 1 — MCP Servers

### 1.1 Slack MCP

| Property                   | Value                                                                               |
| -------------------------- | ----------------------------------------------------------------------------------- |
| Endpoint                   | `https://mcp.slack.com/mcp`                                                         |
| Transport                  | Streamable HTTP only (no SSE)                                                       |
| DCR (RFC 7591)             | **❌ Explicitly not supported**                                                     |
| Auth mechanism             | Confidential OAuth 2.0 with a pre-registered Slack app                              |
| Required credentials       | `client_id` + `client_secret` from a Slack app                                      |
| App requirement            | Only Slack Marketplace-published or internal apps; unlisted apps are **prohibited** |
| Discovery                  | RFC 8414 at `https://mcp.slack.com/.well-known/oauth-authorization-server`          |
|                            | RFC 9470 at `https://mcp.slack.com/.well-known/oauth-protected-resource`            |
| Authorization endpoint     | `https://slack.com/oauth/v2_user/authorize`                                         |
| Token endpoint             | `https://slack.com/api/oauth.v2.user.access`                                        |
| Redirect URI               | Must be pre-registered in the Slack app settings                                    |
| Partner clients (built-in) | Cursor, Claude Code, Claude.ai, Perplexity                                          |

**Key constraint**: Slack requires a pre-registered `client_id`/`client_secret` from a Slack app you own. There is no way around this — no API key, no public client, no DCR. The partner clients listed above work out of the box because Slack pre-registered them; any other client needs its own Slack app.

---

### 1.2 Notion MCP

| Property                   | Value                                                          |
| -------------------------- | -------------------------------------------------------------- |
| Endpoint (recommended)     | `https://mcp.notion.com/mcp` (Streamable HTTP)                 |
| Endpoint (fallback)        | `https://mcp.notion.com/sse` (SSE)                             |
| Transport                  | Streamable HTTP + SSE fallback                                 |
| DCR (RFC 7591)             | **✅ Supported** — `registration_endpoint` present in metadata |
| Auth mechanism             | OAuth 2.0 Authorization Code + **PKCE mandatory**              |
| Discovery                  | RFC 9470 then RFC 8414 (standard two-step auto-discovery)      |
| Token lifetime             | Access token: 1 hour; refresh tokens rotate on every use       |
| Pre-registered credentials | Optional — clients can also use DCR                            |
| Implementation             | Cloudflare `workers-oauth-provider`                            |

**Key property**: Notion is the most standards-compliant server in this list. It supports full auto-discovery and DCR, meaning any client that follows the MCP OAuth spec works with zero configuration beyond providing the URL.

---

### 1.3 Google Maps Grounding Lite

| Property          | Value                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------- |
| Endpoint          | `https://mapstools.googleapis.com/mcp`                                                |
| Transport         | Streamable HTTP only                                                                  |
| DCR (RFC 7591)    | **❌ Not supported** (standard Google OAuth)                                          |
| Auth mechanism 1  | **API key** via `X-Goog-Api-Key` HTTP header                                          |
| Auth mechanism 2  | **Google OAuth** with a pre-registered OAuth client (Desktop or Web app type)         |
| For Desktop OAuth | Any `http://localhost` redirect is automatically allowed — no pre-registration needed |
| For Web app OAuth | Redirect URIs must be explicitly registered in Google Cloud Console                   |
| Scopes            | `https://www.googleapis.com/auth/cloud-platform`                                      |
| Status            | Experimental, no charge, quotas apply                                                 |

**Key property**: This is the only server in this list that supports **API key authentication** as a first-class option. The API key approach (a static header) is simpler than OAuth and completely avoids any auth flow. Google's own Gemini CLI docs demonstrate this as the primary setup method:

```bash
gemini mcp add -s user -t http -H 'X-Goog-Api-Key: YOUR_KEY' maps-grounding-lite https://mapstools.googleapis.com/mcp
```

---

### 1.4 workspace-mcp (Gmail / Google Workspace)

| Property             | Value                                                                               |
| -------------------- | ----------------------------------------------------------------------------------- |
| Package              | `workspace-mcp` (PyPI)                                                              |
| Transport            | **stdio only** (local subprocess)                                                   |
| Auth mechanism       | Google Desktop OAuth 2.0 — managed internally by the package                        |
| Required credentials | `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET` env vars                    |
| Redirect URI         | Not needed — Desktop OAuth allows any localhost port automatically                  |
| Token storage        | `WORKSPACE_MCP_CREDENTIALS_DIR` (defaults to `~/.google_workspace_mcp/`)            |
| DCR                  | N/A — stdio server, auth is handled inside the process                              |
| First-run behavior   | Opens a browser window for Google consent on first run; tokens are cached afterward |

**Key property**: Since it's a stdio server, the MCP client (Codex, Gemini, Cursor) has no involvement in the OAuth flow. The package handles everything internally. The only thing the client needs to do is launch the process with the right env vars.

---

## Part 2 — Clients

### 2.1 Codex

| Capability               | Details                                                                     |
| ------------------------ | --------------------------------------------------------------------------- |
| **DCR OAuth**            | `codex mcp login <server>` — triggers DCR + browser flow                    |
| **Bearer token**         | `bearer_token_env_var = "MY_VAR"` — injects `Authorization: Bearer <value>` |
| **Static headers**       | `http_headers = { "X-Goog-Api-Key" = "value" }` — hardcoded headers         |
| **Env-var headers**      | `env_http_headers = { "X-Goog-Api-Key" = "MY_VAR" }` — headers from env     |
| **Pre-registered OAuth** | ❌ — always attempts DCR; pre-configured credentials have no effect         |
| **Callback port**        | `mcp_oauth_callback_port = 5555` — fixed port for OAuth redirect            |
| **Callback URL**         | `mcp_oauth_callback_url = "https://..."` — custom redirect URL              |
| **Stdio auth**           | Via `env` table — env vars passed to the subprocess                         |

**Note on ai-sync**: `env_http_headers`, `http_headers`, and `bearer_token_env_var` are valid Codex config fields but are **not yet in ai-sync's `ServerConfig` model**. They cannot be set via `mcp-servers/<server-id>/artifact.yaml` today.

---

### 2.2 Gemini CLI

| Capability               | Details                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------ |
| **DCR OAuth**            | Automatic — triggers on first connection if server supports it (`dynamic_discovery`) |
| **Pre-registered OAuth** | ✅ `oauth.clientId` + `oauth.clientSecret` — bypasses DCR entirely                   |
| **Static headers**       | ✅ `"headers": { "X-Goog-Api-Key": "value" }`                                        |
| **Env-var in headers**   | ✅ `"headers": { "X-Goog-Api-Key": "$MY_VAR" }` — native `$VAR` expansion            |
| **Google ADC**           | ✅ `authProviderType: "google_credentials"` — no browser flow needed                 |
| **Service Account**      | ✅ `authProviderType: "service_account_impersonation"`                               |
| **Callback port**        | Fixed at **7777** — `http://localhost:7777/oauth/callback`                           |
| **Token storage**        | `~/.gemini/mcp-oauth-tokens.json` — automatic refresh                                |
| **Manual auth**          | `/mcp auth <serverName>`                                                             |
| **Stdio auth**           | Via `env` table with native `$VAR` expansion                                         |

**Note on ai-sync**: `headers` and `authProviderType` are not yet in ai-sync's `ServerConfig` model. Only `oauth.clientId`/`clientSecret`/`scopes` are generated for Gemini today.

---

### 2.3 Cursor

| Capability               | Details                                                                                                                                         |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **DCR OAuth**            | Automatic — shows **"Needs login"** button in the UI for servers that support DCR                                                               |
| **Pre-registered OAuth** | ❌ — always attempts DCR; fails with `Incompatible auth server: does not support dynamic client registration` for servers that don't support it |
| **Static headers**       | ✅ `"headers": { "X-Goog-Api-Key": "value" }` in `mcp.json` — **works in IDE, not in CLI** (known bug)                                          |
| **Env-var in headers**   | ❌ — no native `$VAR` expansion in headers; values must be inlined                                                                              |
| **Bearer token**         | ❌ — no `bearer_token_env_var` equivalent in `mcp.json`                                                                                         |
| **Partner integrations** | Slack (and likely others) have pre-registered credentials — work without `mcp-remote`                                                           |
| **Callback port**        | Not configurable                                                                                                                                |
| **Stdio auth**           | Via `env` table                                                                                                                                 |

**Note on ai-sync**: `headers` is a valid Cursor `mcp.json` field but is **not generated by ai-sync's cursor adapter** today.

---

## Part 3 — Full Cross Matrix

### Slack

| Client     | Approach                                                 | Works? | Notes                                                |
| ---------- | -------------------------------------------------------- | :----: | ---------------------------------------------------- |
| Codex      | `mcp-remote --static-oauth-client-info` (stdio)          |   ✅   | Uses your own Slack app credentials                  |
| Gemini CLI | `oauth.clientId` + `oauth.clientSecret` in server config |   ✅   | Native, no mcp-remote needed                         |
| Cursor     | Native "Needs login" (uses Cursor's built-in Slack app)  |   ✅   | Only for the Cursor partner integration              |
| Cursor     | `mcp-remote --static-oauth-client-info` (stdio)          |   ✅   | Required if using your **own** Slack app credentials |

**Current ai-sync config**: `mcp-remote --static-oauth-client-info` — ✅ works for all three clients with custom app credentials, but Gemini could use the simpler native OAuth approach.

---

### Notion

| Client     | Approach                            | Works? | Notes                                    |
| ---------- | ----------------------------------- | :----: | ---------------------------------------- |
| Codex      | `codex mcp login notion` (DCR auto) |   ✅   | `method: http` in config, run login once |
| Gemini CLI | Auto-discovery + DCR                |   ✅   | Fully automatic on first connection      |
| Cursor     | Auto-discovery + DCR                |   ✅   | "Needs login" button, one-click          |

**Current ai-sync config**: `method: http, httpUrl: https://mcp.notion.com/mcp` — ✅ correct for all three clients.

---

### Google Maps Grounding Lite

Two distinct auth paths are possible:

#### Path A — OAuth (current approach)

| Client     | Approach                                                 | Works? | Notes                             |
| ---------- | -------------------------------------------------------- | :----: | --------------------------------- |
| Codex      | `mcp-remote --static-oauth-client-info` (stdio)          |   ✅   |                                   |
| Gemini CLI | `oauth.clientId` + `oauth.clientSecret` in server config |   ✅   | Native, browser flow on first use |
| Cursor     | `mcp-remote --static-oauth-client-info` (stdio)          |   ✅   |                                   |

#### Path B — API key (simpler, no auth flow)

| Client     | Approach                                                     | Works? | Notes                                   |
| ---------- | ------------------------------------------------------------ | :----: | --------------------------------------- |
| Codex      | `env_http_headers = { "X-Goog-Api-Key" = "MY_VAR" }`         |   ✅   | **Not yet in ai-sync model**            |
| Gemini CLI | `"headers": { "X-Goog-Api-Key": "$MY_VAR" }`                 |   ✅   | **Not yet in ai-sync model**            |
| Cursor     | `"headers": { "X-Goog-Api-Key": "value" }` (static, inlined) |   ⚠️   | Works in IDE, broken in CLI (known bug) |

**Current ai-sync config**: `mcp-remote --static-oauth-client-info` (Path A) — works but Path B (API key) would be simpler for all clients once the model supports `headers`.

---

### workspace-mcp (Gmail / Google Workspace)

| Client     | Approach                                         | Works? | Notes                            |
| ---------- | ------------------------------------------------ | :----: | -------------------------------- |
| Codex      | stdio + `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` in env |   ✅   | package handles OAuth internally |
| Gemini CLI | stdio + `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` in env |   ✅   | package handles OAuth internally |
| Cursor     | stdio + `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` in env |   ✅   | package handles OAuth internally |

**Current ai-sync config**: stdio + env vars — ✅ correct for all three clients.

---

## Part 4 — Implications for ai-sync

### Current model gaps

The following fields are valid in each client's config format but are not yet exposed in ai-sync's `ServerConfig` model:

| Field                     | Client             | Purpose                                            | Impact                                                                             |
| ------------------------- | ------------------ | -------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `headers`                 | Gemini CLI, Cursor | Static HTTP headers (API keys, custom auth)        | Can't configure Google Maps via API key; can't use Gemini's native OAuth for Slack |
| `env_http_headers`        | Codex              | HTTP headers sourced from env vars                 | Can't configure Google Maps API key for Codex                                      |
| `http_headers`            | Codex              | Static HTTP headers                                | Same as above                                                                      |
| `bearer_token_env_var`    | Codex              | `Authorization: Bearer` from env                   | Already handled in `codex.py` but not in the Pydantic model                        |
| `authProviderType`        | Gemini CLI         | Selects auth provider (`google_credentials`, etc.) | Can't use Google ADC for Google APIs                                               |
| `mcp_oauth_callback_port` | Codex              | Fixed OAuth callback port                          | Can't set a stable redirect URI without `mcp-remote`                               |

### Per-client config proposal

Adding these fields to the model requires a decision: some fields are universal (e.g. `headers` is supported by all three clients), while others are client-specific (e.g. `bearer_token_env_var` is Codex-only, `authProviderType` is Gemini-only).

A per-client override block in `mcp-servers/<server-id>/artifact.yaml` would solve both cases cleanly:

```yaml
# mcp-servers/google-maps-grounding-lite/artifact.yaml
method: http
httpUrl: https://mapstools.googleapis.com/mcp
per_client:
  codex:
    env_http_headers:
      X-Goog-Api-Key: GOOGLE_MAPS_API_KEY
    gemini:
      headers:
        X-Goog-Api-Key: "$GOOGLE_MAPS_API_KEY"
    cursor:
      headers:
        X-Goog-Api-Key: "actual-key-value" # cursor has no env expansion
  env:
    GOOGLE_MAPS_API_KEY: "${GOOGLE_MAPS_API_KEY}"
```

```yaml
# Example: Slack with native Gemini OAuth (no mcp-remote needed for Gemini)
slack:
  method: stdio
  command: sh
  args:
    [
      "-c",
      'npx -y mcp-remote https://mcp.slack.com/mcp 3334 --static-oauth-client-info "{\"client_id\":\"$$SLACK_MCP_CLIENT_ID\",\"client_secret\":\"$$SLACK_MCP_CLIENT_SECRET\"}"',
    ]
  env:
    SLACK_MCP_CLIENT_ID: "${SLACK_MCP_CLIENT_ID}"
    SLACK_MCP_CLIENT_SECRET: "${SLACK_MCP_CLIENT_SECRET}"
  per_client:
    gemini:
      method: http
      httpUrl: https://mcp.slack.com/mcp
      oauth:
        enabled: true
        clientId: "${SLACK_MCP_CLIENT_ID}"
        clientSecret: "${SLACK_MCP_CLIENT_SECRET}"
        authorizationUrl: https://slack.com/oauth/v2_user/authorize
        tokenUrl: https://slack.com/api/oauth.v2.user.access
```
