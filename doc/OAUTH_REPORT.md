# MCP Server Authentication Report: Codex, Gemini CLI, and Cursor

> Research date: February 2026
> Sources: official documentation for each client, community forums, ai-sync client adapter source code

---

## TL;DR

All three clients support OAuth for remote MCP servers, but in very different ways. **Gemini CLI is the most capable**, supporting OAuth without Dynamic Client Registration (DCR), Google ADC, and service account impersonation. **Codex and Cursor are both limited to DCR-based OAuth flows**, which fails against most major OAuth providers (Google, Azure AD, Slack…). The recommended workaround for Codex and Cursor is to proxy the connection through `mcp-remote --static-oauth-client-info`.

---

## 1. Codex

### Supported transports

- Stdio (`command` + `args`)
- Streamable HTTP (`url`)

### Authentication methods

| Method              | Config key                                  | How it works                                                             |
| ------------------- | ------------------------------------------- | ------------------------------------------------------------------------ |
| **Bearer token**    | `bearer_token_env_var = "MY_VAR"`           | Reads the token from an env var, injects it as `Authorization: Bearer …` |
| **Static headers**  | `http_headers = { "X-Key" = "val" }`        | Headers hardcoded in config                                              |
| **Env-var headers** | `env_http_headers = { "X-Key" = "MY_VAR" }` | Header values pulled from env vars                                       |
| **OAuth**           | `codex mcp login <server>`                  | Interactive OAuth flow — **requires DCR**                                |

### OAuth: the DCR requirement

`codex mcp login` relies entirely on **Dynamic Client Registration (DCR, RFC 7591)**: it contacts the remote server to register itself as an OAuth client at runtime. If the server does not support DCR (Google OAuth, Azure AD, Slack…), the command fails immediately with:

```
Error: Registration failed: Dynamic registration failed: Registration failed: Dynamic client registration not supported
```

### Callback configuration (for DCR-compatible servers)

```toml
# ~/.codex/config.toml or .codex/config.toml
mcp_oauth_callback_port = 5555                           # fixed port for the OAuth callback
mcp_oauth_callback_url  = "https://devbox.example/cb"   # custom URL (e.g. remote devbox ingress)
```

By default, Codex binds to an ephemeral port, which is incompatible with OAuth providers that require pre-registered redirect URIs.

### Workaround for servers without DCR support

Use `mcp-remote` with `--static-oauth-client-info` as a stdio wrapper. `mcp-remote` handles the browser-based OAuth flow itself using pre-registered client credentials, bypassing DCR entirely:

```toml
[mcp_servers.my-server]
command = "sh"
args = [
    "-c",
    "npx -y mcp-remote https://api.example.com/mcp 3335 --static-oauth-client-info \"{\\\"client_id\\\":\\\"$CLIENT_ID\\\",\\\"client_secret\\\":\\\"$CLIENT_SECRET\\\"}\"",
]

[mcp_servers.my-server.env]
CLIENT_ID     = "your-client-id"
CLIENT_SECRET = "your-client-secret"
```

The OAuth callback URL for `mcp-remote` on port 3335 is `http://localhost:3335/oauth/callback`. For **Google "Desktop app" OAuth clients**, any `http://localhost` redirect is automatically allowed — no pre-registration needed. For "Web application" OAuth clients, the URI would need to be explicitly registered.

---

## 2. Gemini CLI

### Supported transports

- Stdio (`command` + `args`)
- SSE — `url` field (e.g. `http://localhost:8080/sse`)
- Streamable HTTP — `httpUrl` field

### Authentication methods

| Method             | Config                                       | How it works                                 |
| ------------------ | -------------------------------------------- | -------------------------------------------- |
| **Static headers** | `"headers": { "Authorization": "Bearer …" }` | Injected on every HTTP request               |
| **Env vars**       | `"env": { "TOKEN": "$MY_VAR" }`              | Native `$VAR` / `${VAR}` expansion supported |
| **Full OAuth**     | `"oauth": { … }` section                     | See below                                    |

### OAuth: the most capable of the three

Gemini supports an `authProviderType` field that fundamentally changes the authentication strategy:

#### `dynamic_discovery` (default)

Automatically discovers OAuth endpoints from server metadata and performs DCR if the server supports it. Same limitation as Codex and Cursor for servers without DCR support.

#### `google_credentials`

Uses **Google Application Default Credentials (ADC)**. Ideal for Google APIs — no interactive browser flow, works transparently if the user is already authenticated via `gcloud auth application-default login`.

```json
{
  "mcpServers": {
    "my-google-server": {
      "httpUrl": "https://my-gcp-service.run.app/mcp",
      "authProviderType": "google_credentials",
      "oauth": {
        "scopes": ["https://www.googleapis.com/auth/cloud-platform"]
      }
    }
  }
}
```

#### `service_account_impersonation`

Impersonates a GCP service account. Designed for IAP-protected services (e.g. Cloud Run).

```json
{
  "httpUrl": "https://my-iap-service.run.app/mcp",
  "authProviderType": "service_account_impersonation",
  "targetServiceAccount": "sa@project.iam.gserviceaccount.com",
  "targetAudience": "oauth-client-id-allowlisted-on-iap"
}
```

#### Pre-registered credentials (no DCR required)

**Unlike Codex and Cursor**, Gemini CLI can authenticate using pre-registered OAuth client credentials directly, without requiring the server to support DCR:

```json
{
  "url": "https://api.example.com/sse",
  "oauth": {
    "enabled": true,
    "clientId": "xxx.apps.googleusercontent.com",
    "clientSecret": "GOCSPX-…",
    "authorizationUrl": "https://accounts.google.com/o/oauth2/auth",
    "tokenUrl": "https://oauth2.googleapis.com/token",
    "redirectUri": "http://localhost:7777/oauth/callback",
    "scopes": ["https://www.googleapis.com/auth/cloud-platform"]
  }
}
```

### Full list of OAuth configuration properties

| Property           | Type     | Description                                                           |
| ------------------ | -------- | --------------------------------------------------------------------- |
| `enabled`          | boolean  | Enable OAuth for this server                                          |
| `clientId`         | string   | OAuth client identifier (optional with DCR)                           |
| `clientSecret`     | string   | OAuth client secret (optional for public clients)                     |
| `authorizationUrl` | string   | Authorization endpoint (auto-discovered if omitted)                   |
| `tokenUrl`         | string   | Token endpoint (auto-discovered if omitted)                           |
| `redirectUri`      | string   | Custom redirect URI (default: `http://localhost:7777/oauth/callback`) |
| `scopes`           | string[] | Required OAuth scopes                                                 |
| `tokenParamName`   | string   | Query parameter name for tokens in SSE URLs                           |
| `audiences`        | string[] | Audiences the token must be valid for                                 |

### Token management

- Tokens stored automatically in `~/.gemini/mcp-oauth-tokens.json`
- Automatic refresh when expired (if refresh token is available)
- Callback **always on port 7777**: `http://localhost:7777/oauth/callback`
- `/mcp auth <serverName>` to trigger the flow manually
- `/mcp auth` to list all servers requiring authentication

---

## 3. Cursor

### Supported transports

- Stdio (`command` + `args`)
- SSE / Streamable HTTP (`url`)

### Authentication methods

| Method               | Config                    | How it works                                            |
| -------------------- | ------------------------- | ------------------------------------------------------- |
| **Env vars (stdio)** | `"env": { … }`            | Passed to the server process                            |
| **OAuth (DCR only)** | `"url": "https://…"` only | Cursor detects a 401, triggers OAuth — **requires DCR** |

### OAuth: DCR-only with limited configuration

When connecting to an HTTP server, Cursor:

1. Attempts a connection
2. On a 401 response, tries the OAuth flow **with mandatory DCR**
3. If the server does not support DCR → `Incompatible auth server: does not support dynamic client registration`

For servers that do support DCR (Notion, GitHub, Figma…), Cursor displays a **"Needs login"** button in the UI and the flow works end-to-end without any extra configuration.

There is no `bearer_token_env_var` equivalent in Cursor's `mcp.json` format. Static bearer tokens must be injected either via a command-line wrapper or by passing a token in the URL itself (e.g. `?token=…`).

### Workaround for servers without DCR support

Same approach as Codex — use `mcp-remote --static-oauth-client-info`:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "sh",
      "args": [
        "-c",
        "npx -y mcp-remote https://api.example.com/mcp 3335 --static-oauth-client-info \"{\\\"client_id\\\":\\\"$CLIENT_ID\\\",\\\"client_secret\\\":\\\"$CLIENT_SECRET\\\"}\""
      ],
      "env": {
        "CLIENT_ID": "your-client-id",
        "CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

---

## 4. Comparison matrix

| Capability                                     |            Codex            |        Gemini CLI         |       Cursor        |
| ---------------------------------------------- | :-------------------------: | :-----------------------: | :-----------------: |
| Stdio transport                                |             ✅              |            ✅             |         ✅          |
| HTTP / SSE transport                           |             ✅              |            ✅             |         ✅          |
| Bearer token via env var                       | ✅ (`bearer_token_env_var`) |    ✅ (via `headers`)     | ❌ (not documented) |
| Static HTTP headers                            |             ✅              |            ✅             |    ❌ (UI only)     |
| OAuth with DCR                                 |   ✅ (`codex mcp login`)    |      ✅ (automatic)       |   ✅ (automatic)    |
| OAuth without DCR (pre-registered credentials) |             ❌              |            ✅             |         ❌          |
| Google Application Default Credentials         |             ❌              | ✅ (`google_credentials`) |         ❌          |
| GCP Service Account Impersonation              |             ❌              |            ✅             |         ❌          |
| Configurable callback port                     |             ✅              |     ❌ (fixed: 7777)      |         ❌          |
| Configurable callback URL                      |             ✅              |    ✅ (`redirectUri`)     |         ❌          |
| Automatic token refresh                        |             ✅              |            ✅             |         ✅          |
| Manual auth command                            |      `codex mcp login`      |        `/mcp auth`        |       UI only       |
| `oauth.*` config fields documented             |             ❌              |            ✅             |         ❌          |

---

## 5. Implications for ai-sync

### What ai-sync generates per client

When a server has `oauth.enabled: true`, ai-sync behaves differently per client:

- **Codex** (`config.toml`): writes `enabled` and any explicitly set URL fields (`authorizationUrl`, `tokenUrl`, `issuer`, `redirectUri`).
- **Cursor** (`mcp.json`): same as Codex.
- **Gemini** (`settings.json`): writes the full `oauth` object including `clientId`, `clientSecret`, and `scopes`, because Gemini is the only client that uses them to perform a non-DCR OAuth flow.

### Recommended approach per server type

#### Servers with DCR support (Notion, GitHub, Figma, Make…)

No special handling needed. All three clients handle the OAuth flow automatically.

```yaml
# mcp-servers/my-server/artifact.yaml
method: http
httpUrl: https://mcp.example.com/mcp
# no oauth section needed — DCR is automatic
```

#### Servers without DCR (Google OAuth, Azure AD, Slack…)

Use stdio + `mcp-remote --static-oauth-client-info` for Codex and Cursor. Gemini can also use this approach (works fine), or use the native `oauth` section with pre-registered credentials.

```yaml
# mcp-servers/my-server/artifact.yaml — universal workaround
method: stdio
command: sh
args:
  [
    "-c",
    'npx -y mcp-remote https://api.example.com/mcp 3335 --static-oauth-client-info "{\"client_id\":\"$$MY_CLIENT_ID\",\"client_secret\":\"$$MY_CLIENT_SECRET\"}"',
  ]
env:
  MY_CLIENT_ID: "${MY_CLIENT_ID}"
  MY_CLIENT_SECRET: "${MY_CLIENT_SECRET}"
```

> **Note on `$$` escaping**: ai-sync's `env_loader.py` treats `$$` as an escape for a literal `$`. So `$$MY_CLIENT_ID` in `mcp-servers/<server-id>/artifact.yaml` becomes `$MY_CLIENT_ID` in the generated config file, which the shell then expands at runtime from the `env` section.

> **Redirect URI**: `mcp-remote` on port 3335 uses `http://localhost:3335/oauth/callback` as the redirect URI. For **Google "Desktop app" OAuth clients**, any `http://localhost` redirect (any port, any path) is automatically allowed — no pre-registration in the Cloud Console is needed. For **Google "Web application" OAuth clients**, you would need to explicitly register the URI, but Desktop clients handle this transparently by design.

#### Google APIs specifically

For Gemini, consider using `google_credentials` instead of `mcp-remote` — it avoids the browser flow entirely if the user already has ADC set up:

```yaml
# mcp-servers/my-google-server/artifact.yaml — Gemini-native approach
method: http
httpUrl: https://my-gcp-service.run.app/mcp
oauth:
  enabled: true
  # authProviderType not yet a field in ai-sync's OAuthConfig model
  scopes:
    - https://www.googleapis.com/auth/cloud-platform
```

However, since this only works for Gemini, the `mcp-remote` approach remains preferable for consistency across all three clients unless the server is Gemini-only.

---

## 6. Known gaps in ai-sync

Based on this research, the following improvements could be made to ai-sync:

1. **`authProviderType` field**: ai-sync's `OAuthConfig` model does not expose Gemini's `authProviderType`. Adding it would allow using `google_credentials` or `service_account_impersonation` for Gemini without a workaround.

2. **`mcp_oauth_callback_port` for Codex**: ai-sync does not currently expose this field. It is needed when `mcp-remote` is not used and the OAuth provider requires a pre-registered redirect URI with a fixed port.
