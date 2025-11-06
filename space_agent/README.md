# Space Explorer Agent

A Google ADK agent that connects to an authenticated Apollo MCP Server to explore space data from The Space Devs API.

## Features

- **Dual OAuth Authentication Flow**:
  - **Client Credentials Flow**: For initial MCP server connection (listTools)
  - **Authorization Code Grant Flow**: For user-authenticated tool execution
  - **Automatic Token Management**: ADK handles token refresh with `offline_access` scope
- **Space Data Tools**: Access to GraphQL operations for:
  - Searching upcoming rocket launches
  - Getting astronaut details
  - Finding out who's currently in space
  - Exploring celestial bodies

## Prerequisites

1. **Python 3.10+** (required for MCP SDK)
2. **Apollo MCP Server running** on `http://127.0.0.1:8000/mcp`
3. **Auth0 account** with:
   - **Regular Web Application** configured (NOT Machine-to-Machine)
   - **Grant Types Enabled**: Authorization Code, Refresh Token, Client Credentials
   - **Allowed Callback URLs**: `http://127.0.0.1:8081/dev-ui/`
   - **API configured** with identifier `http://127.0.0.1:8000/mcp`
   - **Application authorized** for the API with `read:users` scope
4. **Google Cloud Project** or **Gemini API Key** for the Gemini model

## Setup

### 1. Install Dependencies

```bash
cd space_agent
pip install -r requirements.txt
```

### 2. Configure Auth0

Create a `.env` file in the `space_agent` directory (or copy from `.env.example`):

```bash
# Auth0 Configuration
AUTH0_DOMAIN=your-domain.us.auth0.com
AUTH0_CLIENT_ID=your_client_id
AUTH0_CLIENT_SECRET=your_client_secret
AUTH0_API_AUDIENCE=http://127.0.0.1:8000/mcp
ADK_CALLBACK_URL=http://127.0.0.1:8081/dev-ui/

# Google API Key (or use GOOGLE_CLOUD_PROJECT)
GOOGLE_API_KEY=your_gemini_api_key
```

**How the dual authentication flow works:**

1. **Initial Connection (Client Credentials)**:
   - When ADK starts, it needs to connect to the MCP server to discover available tools (`listTools`)
   - Uses client credentials flow (M2M) to get a token without user interaction
   - This happens in `get_mcp_headers()` function

2. **Tool Execution (Authorization Code Grant)**:
   - When a user actually calls a tool, ADK initiates user authentication
   - Opens Auth0 consent screen for user to authorize
   - Exchanges authorization code for access + refresh tokens
   - Tokens are cached and automatically refreshed via `oauth_helper.py`

3. **Token Lifecycle**:
   - Tokens cached using `credential_cache_key` in session state
   - Automatically refreshed when expired (thanks to `offline_access` scope)
   - No manual token management required!

**Important - How ADK Merges Authentication:**

Based on ADK source code analysis, both `header_provider` and `auth_scheme` are converted to HTTP headers and merged. Without careful handling, `header_provider` can override `auth_scheme` credentials.

**✅ Our Implementation (User Token Priority):**

The `get_mcp_headers()` function implements smart credential routing:

```python
def get_mcp_headers(context: ReadonlyContext) -> dict[str, str]:
    # Check if user has already authenticated
    user_credential = context._invocation_context.session_state.get(CREDENTIAL_CACHE_KEY)

    if user_credential and user_credential.oauth2.access_token:
        # User token available - let auth_scheme handle Authorization
        return {"Content-Type": "application/json"}  # No Authorization header

    # No user token - use client credentials for server connection
    return {
        "Authorization": f"Bearer {client_credentials_token}",
        "Content-Type": "application/json",
    }
```

**Authentication Flow:**

1. **Agent starts** → `listTools` → No user token → Client credentials used ✅
2. **First tool call** → User authenticates → Token cached → Subsequent calls use user token ✅
3. **Tool execution** → User token in session → `header_provider` skips Authorization → `auth_scheme` provides user token ✅
4. **MCP server receives** → User-specific token for proper authorization ✅

**Why this approach:**
- **Enables user-level authorization**: MCP server can enforce per-user permissions
- **Graceful fallback**: Client credentials used when user hasn't authenticated yet
- **No token collision**: User tokens take precedence when available
- **Production-ready**: Works for multi-user scenarios with proper authorization

See `../ADK_AUTHENTICATION_INTERNALS.md` for detailed source code analysis.

### 3. Start the MCP Server

Make sure your Apollo MCP server is running on `http://127.0.0.1:8000/mcp` with Auth0 authentication enabled.

```bash
# In your apollo-mcp-server directory
cd /Users/pskulkarni/Documents/source-code/apollo-mcp-server
APOLLO_GRAPH_REF=My-Graph-ihs6vg@current \
APOLLO_KEY=service:My-Graph-ihs6vg:hXBv0drEkeMFiELbdIDPSg \
rover dev \
  --supergraph-config ./graphql/TheSpaceDevs/supergraph.yaml \
  --router-config ./graphql/TheSpaceDevs/router.yaml \
  --mcp ./graphql/TheSpaceDevs/config.yaml
```

## Running the Agent

### Using ADK CLI

```bash
adk run space_agent
```

### Using ADK Web UI

```bash
adk web space_agent
```

This will start a local web server (typically at `http://localhost:3000`) where you can interact with the agent through a chat interface.

### Programmatically

```python
from google.adk.runners import Runner
from agent import root_agent

runner = Runner(root_agent)

# Run a single query
response = await runner.run("Who is currently in space?")
print(response.content)

# Interactive loop
await runner.run_interactive()
```

## Example Queries

Try asking the agent:

- "What rocket launches are happening soon?"
- "Who is currently in space?"
- "Tell me about astronaut John Smith"
- "What celestial bodies can you show me?"

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Google ADK Agent                        │
│                    (Space Explorer)                         │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              LlmAgent (Gemini 2.0)                  │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                       │
│  ┌─────────────────▼──────────────────────────────────┐   │
│  │              McpToolset                             │   │
│  │  • header_provider (Client Credentials)            │   │
│  │  • auth_scheme (Authorization Code Grant)          │   │
│  │  • auth_credential (OAuth2Auth)                    │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                       │
│  ┌─────────────────▼──────────────────────────────────┐   │
│  │         oauth_helper.py                             │   │
│  │  • get_user_credentials()                          │   │
│  │  • Token caching & refresh                         │   │
│  │  • Credential lifecycle management                 │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
           │                              │
           │ MCP Protocol                 │ OAuth 2.0
           │ (HTTP + JSON-RPC)           │ (Authorization Code)
           │                              │
           ▼                              ▼
┌──────────────────────┐        ┌──────────────────────┐
│   Apollo MCP Server  │◄──────►│   Auth0 OAuth Server │
│                      │        │                      │
│  • /mcp endpoint     │ Token  │  • /authorize        │
│  • Auth0 validation  │ Valid  │  • /oauth/token      │
│  • Tool discovery    │        │  • Client: Regular   │
│  • Tool execution    │        │    Web Application   │
└──────────┬───────────┘        └──────────────────────┘
           │
           │ GraphQL
           │
           ▼
┌──────────────────────┐
│  The Space Devs API  │
│                      │
│  • Launches          │
│  • Astronauts        │
│  • Celestial Bodies  │
└──────────────────────┘
```

### Authentication Flow Sequence

#### Phase 1: Agent Initialization (Client Credentials)

```
User              ADK Agent           MCP Server         Auth0
 │                   │                     │               │
 │ adk web          │                     │               │
 │─────────────────►│                     │               │
 │                   │                     │               │
 │                   │ get_mcp_headers()  │               │
 │                   │────────────────────►│               │
 │                   │                     │ POST /oauth/token
 │                   │                     │ grant_type=client_credentials
 │                   │                     │ audience=http://127.0.0.1:8000/mcp
 │                   │                     │──────────────►│
 │                   │                     │               │
 │                   │                     │ access_token  │
 │                   │                     │◄──────────────│
 │                   │ Bearer token       │               │
 │                   │◄────────────────────│               │
 │                   │                     │               │
 │                   │ listTools (MCP)    │               │
 │                   │ Authorization: Bearer <token>      │
 │                   │────────────────────►│               │
 │                   │                     │               │
 │                   │ tools list         │               │
 │                   │◄────────────────────│               │
 │                   │                     │               │
 │  ◄─Agent Ready──  │                     │               │
 │                   │                     │               │
```

#### Phase 2: Tool Execution (Authorization Code Grant)

```
User              ADK Agent           MCP Server         Auth0
 │                   │                     │               │
 │ "upcoming launches"                    │               │
 │─────────────────►│                     │               │
 │                   │                     │               │
 │                   │ Tool needs auth    │               │
 │                   │ (oauth_helper)     │               │
 │                   │                     │               │
 │  ◄────Redirect────│                     │               │
 │  https://auth0.../authorize?           │               │
 │      client_id=...                     │               │
 │      redirect_uri=http://127.0.0.1:8081/dev-ui/        │
 │      response_type=code                │               │
 │      scope=openid profile email offline_access read:users
 │      audience=http://127.0.0.1:8000/mcp│               │
 │                   │                     │               │
 │─────Login/Consent Screen──────────────────────────────►│
 │                   │                     │               │
 │  ◄────Redirect with auth code──────────────────────────│
 │  http://127.0.0.1:8081/dev-ui/?code=...│               │
 │                   │                     │               │
 │─────Code──────────►│                     │               │
 │                   │                     │               │
 │                   │ Exchange code      │               │
 │                   │ POST /oauth/token  │               │
 │                   │ grant_type=authorization_code      │
 │                   │ code=...           │               │
 │                   │────────────────────────────────────►│
 │                   │                     │               │
 │                   │ access_token       │               │
 │                   │ refresh_token      │               │
 │                   │◄────────────────────────────────────│
 │                   │                     │               │
 │                   │ Cache tokens       │               │
 │                   │ (session_state)    │               │
 │                   │                     │               │
 │                   │ callTool (MCP)     │               │
 │                   │ Authorization: Bearer <user_token> │
 │                   │────────────────────►│               │
 │                   │                     │ Validate     │
 │                   │                     │──────────────►│
 │                   │                     │ Valid        │
 │                   │                     │◄──────────────│
 │                   │                     │               │
 │                   │                     │ GraphQL Query │
 │                   │                     │──────────────►The Space Devs
 │                   │                     │               │
 │                   │                     │ Response     │
 │                   │                     │◄──────────────│
 │                   │ tool result        │               │
 │                   │◄────────────────────│               │
 │                   │                     │               │
 │  ◄────Answer──────│                     │               │
 │                   │                     │               │
```

#### Phase 3: Subsequent Calls (Cached Token)

```
User              ADK Agent           MCP Server         Auth0
 │                   │                     │               │
 │ "who's in space?" │                     │               │
 │─────────────────►│                     │               │
 │                   │                     │               │
 │                   │ Check cache        │               │
 │                   │ (session_state)    │               │
 │                   │ ✓ Valid token      │               │
 │                   │                     │               │
 │                   │ callTool (MCP)     │               │
 │                   │ Authorization: Bearer <cached_token>
 │                   │────────────────────►│               │
 │                   │                     │               │
 │                   │ tool result        │               │
 │                   │◄────────────────────│               │
 │                   │                     │               │
 │  ◄────Answer──────│                     │               │
 │                   │                     │               │
```

#### Phase 4: Token Refresh (Expired Access Token)

```
User              ADK Agent           MCP Server         Auth0
 │                   │                     │               │
 │ "more launches"  │                     │               │
 │─────────────────►│                     │               │
 │                   │                     │               │
 │                   │ Check cache        │               │
 │                   │ ✗ Token expired    │               │
 │                   │ ✓ Has refresh_token│               │
 │                   │                     │               │
 │                   │ POST /oauth/token  │               │
 │                   │ grant_type=refresh_token           │
 │                   │ refresh_token=...  │               │
 │                   │────────────────────────────────────►│
 │                   │                     │               │
 │                   │ new access_token   │               │
 │                   │ new refresh_token  │               │
 │                   │◄────────────────────────────────────│
 │                   │                     │               │
 │                   │ Update cache       │               │
 │                   │                     │               │
 │                   │ callTool (MCP)     │               │
 │                   │ Authorization: Bearer <new_token>  │
 │                   │────────────────────►│               │
 │                   │                     │               │
 │                   │ tool result        │               │
 │                   │◄────────────────────│               │
 │                   │                     │               │
 │  ◄────Answer──────│                     │               │
 │                   │                     │               │
```

## Troubleshooting

### "MCP Tool requires Python 3.10 or above"

- Upgrade your Python version to 3.10 or higher

### "401 Unauthorized" when connecting to MCP server

- Verify Auth0 credentials in `.env` file are correct
- Check that the Regular Web Application is authorized for the API in Auth0
- Verify the API audience matches: `http://127.0.0.1:8000/mcp`
- Ensure both Client Credentials and Authorization Code grant types are enabled

### "Connection refused" to MCP server

- Make sure the Apollo MCP server is running
- Check that it's listening on `http://127.0.0.1:8000/mcp`

### Agent can't find tools

- Check that the MCP server has the space tools configured
- Verify initial authentication is working (check `get_mcp_headers()` function)
- Check server logs for authentication errors

### Consent screen appears on every tool call

- This is expected on the **first** tool call only
- After accepting, ADK caches credentials in session state
- If it persists, check that `offline_access` scope is included
- Verify refresh token is being stored (check `oauth_helper.py` logs)

## Files

- `agent.py` - Main agent definition with dual OAuth2 authentication flows
- `oauth_helper.py` - ADK credential lifecycle management (cache, refresh, exchange)
- `requirements.txt` - Python dependencies
- `.env` - Environment configuration (Auth0 credentials, API keys)
- `.env.example` - Example environment variables template
- `__init__.py` - Python package initialization
- `README.md` - This file

## Key ADK Features Used

- **McpToolset**: Connects to MCP servers and dynamically loads tools
- **Dual OAuth2 Flows**:
  - Client credentials for server connection
  - Authorization code grant for user authentication
- **ExtendedOAuth2**: Auth scheme supporting OAuth2 authorization code flow
- **AuthCredential**: Secure credential storage with audience support
- **CredentialManager**: Session-based token caching and lifecycle management
- **OAuth2CredentialRefresher**: Automatic token refresh with refresh tokens
- **OAuth2CredentialExchanger**: Authorization code to token exchange

## Implementation Pattern

This agent follows the ADK sample pattern from [VeerMuchandi/Learn_ADK_Agents](https://github.com/VeerMuchandi/Learn_ADK_Agents), specifically:
- Environment-based configuration
- Separation of concerns (oauth_helper.py for credential management)
- Standard OAuth2 authorization code grant flow
- Session-based credential caching
- Automatic token refresh
