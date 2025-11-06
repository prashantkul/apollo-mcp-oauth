# Apollo MCP Server with Auth0 Authentication + Google ADK Agent

This project demonstrates how to integrate **Apollo MCP Server**, **Auth0 OAuth2**, and **Google ADK (Agent Development Kit)** to create an authenticated AI agent with access to external APIs.

## Overview

The system consists of three main components:

1. **Apollo MCP Server**: Provides MCP (Model Context Protocol) tools backed by GraphQL APIs, protected by Auth0 authentication
2. **Auth0 OAuth2 Server**: Handles authentication and authorization using OAuth 2.0 flows
3. **Google ADK Agent**: An AI agent that consumes MCP tools with dual OAuth authentication flows

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    User / Developer                              │
└────────────┬─────────────────────────────────────────────────────┘
             │
             │ Chat / API Calls
             │
┌────────────▼──────────────────────────────────────────────────────┐
│                   Google ADK Agent                                │
│                   (space_explorer)                                │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ LlmAgent (Gemini 2.0 Flash)                                │  │
│  │  • Natural language understanding                          │  │
│  │  • Tool selection and execution                            │  │
│  │  • Response generation                                     │  │
│  └───────────────────────┬────────────────────────────────────┘  │
│                          │                                        │
│  ┌───────────────────────▼────────────────────────────────────┐  │
│  │ McpToolset                                                  │  │
│  │  • header_provider: Client credentials (M2M auth)          │  │
│  │  • auth_scheme: Authorization code grant (user auth)       │  │
│  │  • auth_credential: OAuth2 configuration                   │  │
│  └───────────────────────┬────────────────────────────────────┘  │
│                          │                                        │
│  ┌───────────────────────▼────────────────────────────────────┐  │
│  │ oauth_helper.py                                             │  │
│  │  • Credential lifecycle management                         │  │
│  │  • Token caching (session state)                           │  │
│  │  • Automatic token refresh                                 │  │
│  │  • Authorization code exchange                             │  │
│  └────────────────────────────────────────────────────────────┘  │
└───────────────────────┬──────────────────┬───────────────────────┘
                        │                  │
         MCP Protocol   │                  │ OAuth 2.0
        (HTTP+JSON-RPC) │                  │ (Authorization Code)
                        │                  │
                        ▼                  ▼
        ┌───────────────────────┐  ┌──────────────────────┐
        │  Apollo MCP Server    │  │  Auth0 OAuth Server  │
        │  (Port 8000)          │  │                      │
        │                       │  │  Grant Types:        │
        │  Endpoints:           │  │  • Client Credentials│
        │  • /mcp (MCP tools)   │  │  • Authorization Code│
        │  • /.well-known/...   │◄─┤  • Refresh Token     │
        │    (OAuth metadata)   │  │                      │
        │                       │  │  Endpoints:          │
        │  Features:            │  │  • /authorize        │
        │  • Bearer token auth  │  │  • /oauth/token      │
        │  • Tool discovery     │  │  • /.well-known/...  │
        │  • Tool execution     │  │                      │
        │  • GraphQL proxy      │  └──────────────────────┘
        └───────────┬───────────┘
                    │
                    │ GraphQL
                    │
                    ▼
        ┌───────────────────────┐
        │  The Space Devs API   │
        │  (thespacedevs.com)   │
        │                       │
        │  Data:                │
        │  • Rocket launches    │
        │  • Astronauts         │
        │  • Celestial bodies   │
        │  • Space missions     │
        └───────────────────────┘
```

## Key Features

### Dual OAuth 2.0 Authentication Flow

This implementation uses **two different OAuth flows** for different purposes:

#### 1. Client Credentials Flow (M2M)
- **Purpose**: Initial MCP server connection to discover available tools
- **When**: Agent initialization (`listTools` MCP method)
- **Why**: No user interaction needed for tool discovery
- **Implementation**: `get_mcp_headers()` function in `agent.py`

#### 2. Authorization Code Grant Flow
- **Purpose**: User-authenticated tool execution
- **When**: First time a tool is actually called
- **Why**: Tools may access user-specific data or require user consent
- **Implementation**: `oauth_helper.py` with ADK's credential management
- **Features**:
  - User consent screen (first use only)
  - Token caching in session state
  - Automatic token refresh with `offline_access` scope
  - Secure authorization code exchange

### Automatic Token Management

The ADK agent handles the complete OAuth2 token lifecycle:

1. **Token Exchange**: Converts authorization codes to access + refresh tokens
2. **Token Caching**: Stores tokens in session state using `credential_cache_key`
3. **Token Refresh**: Automatically refreshes expired tokens using refresh token
4. **Error Handling**: Re-initiates auth flow if refresh fails

### How ADK Determines Authentication Flow

ADK uses `header_provider` and `auth_scheme` for **different purposes** at **different stages**:

#### When `header_provider` is Used

**Purpose**: MCP protocol-level communication (server connection)

**Triggers**:
- `initialize` - Initial MCP handshake
- `listTools` - Discovering available tools
- `callTool` - Executing tools
- Any MCP protocol method

The `header_provider` is **always called** for every HTTP request to the MCP server.

```python
def get_mcp_headers(context: ReadonlyContext) -> dict[str, str]:
    # Uses client credentials to get token
    # Called for every MCP server request
    return {"Authorization": f"Bearer {token}"}
```

#### When `auth_scheme`/`auth_credential` is Used

**Purpose**: Tool-level user authentication

**Triggers**:
- **Only when a tool is executed** (`callTool`)
- **Only if `auth_scheme` is configured**
- ADK checks if valid cached credentials exist

**Flow**:
1. User asks to call a tool
2. ADK checks: "Does this McpToolset have auth_scheme configured?"
3. If yes: "Do we have valid cached credentials?"
4. If no cached credentials: Initiate OAuth flow (show consent screen)
5. After getting credentials: Execute tool with user's token

#### ADK Decision Tree

```
MCP Server Request (initialize, listTools):
  ├─ ADK calls header_provider()
  └─ Uses returned headers for HTTP request

Tool Execution (callTool):
  ├─ ADK calls header_provider() for MCP communication
  └─ IF auth_scheme is configured:
      ├─ Check for cached credentials (via oauth_helper)
      ├─ If no valid credentials:
      │   └─ Initiate OAuth flow (authorization code grant)
      └─ Include user token in tool execution context
```

#### Authentication Stages in Practice

**Stage 1: Agent Initialization**
```
User runs: adk web space_agent
  ↓
ADK → listTools (MCP method)
  ├─ header_provider() called
  │   └─ Returns: Client Credentials Token
  └─ MCP server authenticates request
      └─ Returns: Available tools list
```

**Stage 2: First Tool Call**
```
User asks: "What rocket launches are happening soon?"
  ↓
ADK → callTool (MCP method)
  ├─ header_provider() called
  │   └─ Returns: Client Credentials Token (for MCP protocol)
  │
  └─ auth_scheme configured?
      └─ Yes → oauth_helper.get_user_credentials()
          └─ No cached token found
              └─ Return AuthConfig
                  └─ ADK shows Auth0 consent screen
                      └─ User authorizes
                          └─ Authorization Code Grant flow
                              └─ Cache user token
                                  └─ Execute tool with user token
```

**Stage 3: Subsequent Tool Calls**
```
User asks: "Who is currently in space?"
  ↓
ADK → callTool (MCP method)
  ├─ header_provider() called
  │   └─ Returns: Client Credentials Token (for MCP protocol)
  │
  └─ auth_scheme configured?
      └─ Yes → oauth_helper.get_user_credentials()
          └─ Cached token found ✓
              └─ Execute tool with cached user token
                  └─ No consent screen needed
```

**Stage 4: Token Refresh**
```
User asks: "More launches please"
  ↓
ADK → callTool (MCP method)
  ├─ header_provider() called
  │   └─ Returns: Client Credentials Token (for MCP protocol)
  │
  └─ auth_scheme configured?
      └─ Yes → oauth_helper.get_user_credentials()
          └─ Cached token expired ✗
              └─ Refresh token found ✓
                  └─ OAuth2CredentialRefresher.refresh()
                      └─ Get new access + refresh tokens
                          └─ Update cache
                              └─ Execute tool with new user token
```

#### Why Both Authentication Methods?

Our dual-auth approach serves different needs:

1. **`header_provider`**: MCP server itself requires Auth0 authentication to even connect
2. **`auth_scheme`**: Tools may need user-specific authentication (different from server auth)

**Other configurations possible**:
- **Only `header_provider`**: If MCP server requires auth but tools don't need user consent
- **Only `auth_scheme`**: If MCP server is public but tools need user auth
- **Neither**: If everything is public

**Key insight**: `header_provider` is for **transport-level auth**, `auth_scheme` is for **tool-level auth**. ADK always uses `header_provider` for MCP communication, but only engages `auth_scheme` when tools are actually called.

#### Important: Header Merging Behavior

**How ADK Actually Works** (based on source code analysis):

Both `auth_scheme` and `header_provider` are converted to HTTP headers and **merged together**:

1. `auth_scheme` credentials → HTTP headers (e.g., `Authorization: Bearer <user_token>`)
2. `header_provider()` → Additional HTTP headers
3. Both sets are merged: `headers.update(auth_headers)` then `headers.update(dynamic_headers)`
4. **If there's a collision, `header_provider` wins** (applied last)

**In Our Implementation:**

Both try to set the `Authorization` header:
- `auth_scheme` → `Authorization: Bearer <user_token>`
- `header_provider` → `Authorization: Bearer <client_credentials_token>`

**Result:** The MCP server receives the **client credentials token** (from `header_provider`), not the user token. The user token is generated by the OAuth flow but gets overridden before reaching the MCP server.

**Why This Still Works:**

Our MCP server only validates that a valid Auth0 token is present. It doesn't require user-specific permissions, so the client credentials token is sufficient.

**For User-Level Authentication:**

If you need the MCP server to receive the user token instead (e.g., for user-level authorization):

**✅ Implemented Solution:**

Our `get_mcp_headers()` function now checks for user credentials and adapts:

```python
def get_mcp_headers(context: ReadonlyContext) -> dict[str, str]:
    # Check if user credentials are cached in session
    user_credential = context._invocation_context.session_state.get(CREDENTIAL_CACHE_KEY)

    if user_credential and user_credential.oauth2.access_token:
        # User is authenticated - don't set Authorization header
        # Let auth_scheme provide the user token
        return {"Content-Type": "application/json"}

    # No user credentials - use client credentials for initial connection
    return {
        "Authorization": f"Bearer {get_client_credentials_token()}",
        "Content-Type": "application/json",
    }
```

**How it works:**
1. **First request (listTools)**: No user credentials → client credentials used
2. **After user login**: User credentials cached → `header_provider` skips Authorization header
3. **ADK's auth_scheme**: Provides `Authorization: Bearer <user_token>` without collision
4. **MCP server receives**: User-specific token for proper authorization

**Alternative Options:**
- **Option 2**: Use `header_provider` only for non-Authorization headers (e.g., custom headers, API keys)
- **Option 3**: Remove `header_provider` entirely if MCP server doesn't require auth for discovery

See [ADK_AUTHENTICATION_INTERNALS.md](ADK_AUTHENTICATION_INTERNALS.md) for detailed analysis with source code references.

## Project Structure

```
apollo-mcp-auth/
├── .env                             # Environment configuration (DO NOT COMMIT)
├── .env.example                    # Example environment variables template
├── .gitignore                      # Git ignore patterns
├── README.md                       # This file
├── ADK_AUTHENTICATION_INTERNALS.md # Deep dive into ADK auth mechanisms
│
├── space_agent/                    # Google ADK Agent
│   ├── __init__.py                # Package initialization
│   ├── agent.py                   # Main agent with dual OAuth flows
│   ├── oauth_helper.py            # Credential lifecycle management
│   ├── requirements.txt           # Python dependencies
│   └── README.md                  # Detailed agent documentation
│
├── test_mcp_auth.py               # Standalone Auth0 + MCP test script
└── requirements.txt               # Root-level Python dependencies
```

## Getting Started

### Prerequisites

1. **Python 3.10+** (required for MCP SDK)
2. **Auth0 Account** with Regular Web Application configured
3. **Google Gemini API Key** or Google Cloud Project
4. **Apollo MCP Server** running on port 8000

### Quick Start

1. **Clone the repository**:
   ```bash
   git clone git@github.com:prashantkul/apollo-mcp-oauth.git
   cd apollo-mcp-oauth
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your Auth0 and Google credentials
   ```

3. **Install dependencies**:
   ```bash
   cd space_agent
   pip install -r requirements.txt
   ```

4. **Start the agent**:
   ```bash
   adk web space_agent
   ```

5. **Interact with the agent**:
   - Open the ADK web UI (typically http://localhost:3000)
   - Ask questions like "What rocket launches are happening soon?"
   - First tool call will trigger Auth0 consent screen
   - Subsequent calls use cached credentials

## Auth0 Configuration

### Application Settings

- **Application Type**: Regular Web Application
- **Grant Types**:
  - ✅ Authorization Code
  - ✅ Refresh Token
  - ✅ Client Credentials
- **Allowed Callback URLs**: `http://127.0.0.1:8081/dev-ui/`
- **Allowed Web Origins**: `http://127.0.0.1:8081`

### API Configuration

- **Identifier**: `http://127.0.0.1:8000/mcp`
- **Scopes**: `read:users` (custom scope for your API)
- **Authorized Applications**: Your Regular Web Application

### Standard OIDC Scopes

The agent requests these scopes (automatically available):
- `openid` - OpenID Connect authentication
- `profile` - User profile information
- `email` - User email address
- `offline_access` - Refresh token for token renewal

## Authentication Flow Walkthrough

### Phase 1: Agent Initialization
```
1. User runs: adk web space_agent
2. Agent calls get_mcp_headers()
3. get_mcp_headers() requests token from Auth0 (client credentials)
4. Auth0 returns access token
5. Agent calls listTools on MCP server with Bearer token
6. MCP server validates token and returns available tools
7. Agent is ready, web UI displays
```

### Phase 2: First Tool Call
```
1. User asks: "What rocket launches are happening soon?"
2. Agent selects: space_SearchUpcomingLaunches tool
3. ADK calls oauth_helper.get_user_credentials()
4. No cached credentials found, returns AuthConfig
5. ADK opens Auth0 consent screen in browser
6. User logs in and accepts permissions
7. Auth0 redirects to http://127.0.0.1:8081/dev-ui/?code=...
8. ADK exchanges code for access + refresh tokens
9. ADK caches tokens in session state
10. Agent executes tool with user's access token
11. MCP server validates token and executes GraphQL query
12. Agent returns results to user
```

### Phase 3: Subsequent Calls
```
1. User asks: "Who is currently in space?"
2. Agent selects: space_GetAstronauts tool
3. ADK checks session cache - valid token found
4. Agent executes tool with cached token
5. No authentication prompt needed
6. Results returned immediately
```

### Phase 4: Token Refresh
```
1. Access token expires (after ~1 hour typically)
2. ADK detects expiration
3. ADK uses refresh token to get new access token
4. Auth0 returns new access + refresh tokens
5. ADK updates cache with new tokens
6. Tool execution continues seamlessly
7. No user interaction needed
```

## Documentation

- **Space Agent**: See [space_agent/README.md](space_agent/README.md) for detailed agent documentation
- **Architecture Diagrams**: Component and sequence diagrams in agent README
- **Auth0 Setup**: Configuration instructions in agent README

## Technologies Used

- **[Google ADK](https://github.com/google/adk)**: Agent Development Kit for building AI agents
- **[Apollo Router](https://www.apollographql.com/docs/router/)**: GraphQL router with MCP support
- **[Auth0](https://auth0.com/)**: Identity and access management platform
- **[Model Context Protocol (MCP)](https://modelcontextprotocol.io/)**: Standard protocol for AI-tool communication
- **[The Space Devs API](https://thespacedevs.com/)**: Public API for space exploration data
- **[Gemini 2.0 Flash](https://ai.google.dev/)**: Google's large language model

## Implementation Pattern

Key patterns implemented:
- Environment-based configuration
- Separation of concerns (oauth_helper.py)
- Credential lifecycle management
- Session-based token caching
- Automatic token refresh

## Troubleshooting

See [space_agent/README.md](space_agent/README.md#troubleshooting) for detailed troubleshooting guide.

## Contributing

This is a demonstration project. Feel free to fork and adapt for your own use cases.

## License

MIT

## Acknowledgments

- **Google ADK Team** for the Agent Development Kit
- **Apollo GraphQL** for MCP support in Apollo Router
- **Auth0** for OAuth2 authentication platform
- **The Space Devs** for the space data API
