# Alternative Approaches for User-Level Authorization with MCP Tools

## The Challenge

ADK's header merging behavior means `header_provider` always overrides `auth_scheme` when both set the `Authorization` header. This creates a conflict when you need:
- Client credentials for MCP server connection (discovery)
- User credentials for tool execution (authorization)

## Why Our Conditional Approach Failed

```python
# This doesn't work reliably
def get_mcp_headers(context):
    if user_is_authenticated:
        return {}  # Skip Authorization, let auth_scheme provide it
    else:
        return {"Authorization": f"Bearer {client_token}"}
```

**Problem:** During graph building and tool discovery, `auth_scheme` is NOT applied, so skipping the Authorization header causes 401 errors.

## Alternative Solutions

### Option 1: Custom User Context Header (Recommended)

**Don't fight ADK's header merging.** Use a custom header for user identity:

```python
def get_mcp_headers(context: ReadonlyContext) -> dict[str, str]:
    """Provide both client credentials AND user identity."""
    headers = {
        "Authorization": f"Bearer {get_client_credentials_token()}",
        "Content-Type": "application/json",
    }

    # Add user identity in a custom header
    try:
        user_cred = context._invocation_context.session_state.get(CREDENTIAL_CACHE_KEY)
        if user_cred and user_cred.oauth2 and user_cred.oauth2.access_token:
            # MCP server can validate this separately
            headers["X-User-Token"] = user_cred.oauth2.access_token
    except (AttributeError, KeyError, TypeError):
        pass

    return headers
```

**MCP Server Side:**
```python
# In your MCP server middleware
async def auth_middleware(request):
    # Validate client credentials (required for all requests)
    client_token = request.headers.get("Authorization")
    validate_client_token(client_token)  # Raises if invalid

    # Check for user context (optional, for user-specific operations)
    user_token = request.headers.get("X-User-Token")
    if user_token:
        user_info = validate_user_token(user_token)
        request.state.user = user_info  # Attach to request
    else:
        request.state.user = None  # Anonymous/service request
```

**Benefits:**
- ✅ No header collision
- ✅ Works with graph building
- ✅ MCP server can enforce user-level permissions
- ✅ Graceful fallback for discovery operations

**Drawbacks:**
- ❌ Non-standard (not using Authorization header for user auth)
- ❌ Requires MCP server support for custom headers

### Option 2: Remove header_provider, Make MCP Public for Discovery

```python
# Remove header_provider entirely
mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://127.0.0.1:8000/mcp",
        timeout=10.0,
    ),
    # No header_provider!
    auth_scheme=auth_scheme,
    auth_credential=auth_credential,
    tool_name_prefix="space",
)
```

**MCP Server Changes:**
```python
# Allow anonymous access for tool discovery
@app.post("/mcp")
async def mcp_endpoint(request):
    # Parse MCP method
    method = request.json().get("method")

    if method in ["initialize", "listTools"]:
        # Allow without auth
        return handle_discovery(request)

    # Tool execution requires user auth
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(401, "Authentication required for tool execution")

    user_info = validate_user_token(auth_header)
    return handle_tool_execution(request, user_info)
```

**Benefits:**
- ✅ User tokens reach MCP server via auth_scheme
- ✅ Clean separation: public discovery, authenticated execution

**Drawbacks:**
- ❌ MCP server must allow anonymous discovery
- ❌ Exposes tool signatures publicly
- ❌ May not be acceptable in production environments

### Option 3: User Context in Tool Arguments

**Pass user identity as tool parameters:**

```python
# Custom tool wrapper that injects user context
from google.adk.tools import BaseTool
from typing import Any

class UserContextTool(BaseTool):
    """Wraps MCP tool to inject user context."""

    def __init__(self, mcp_tool, credential_cache_key):
        self._mcp_tool = mcp_tool
        self._credential_cache_key = credential_cache_key
        super().__init__(
            name=mcp_tool.name,
            description=mcp_tool.description,
            parameters=mcp_tool.parameters,
        )

    async def run_async(self, *, args, tool_context):
        # Get user token
        user_cred = tool_context.get_from_session_state(self._credential_cache_key)

        # Inject into tool arguments
        if user_cred and user_cred.oauth2:
            args["_user_token"] = user_cred.oauth2.access_token

        # Call actual MCP tool
        return await self._mcp_tool.run_async(args=args, tool_context=tool_context)

# Wrap MCP tools
mcp_tools = await mcp_toolset.get_tools(context)
wrapped_tools = [UserContextTool(tool, CREDENTIAL_CACHE_KEY) for tool in mcp_tools]

root_agent = LlmAgent(
    name="space_explorer",
    model="gemini-2.0-flash-exp",
    tools=wrapped_tools,  # Use wrapped tools
)
```

**MCP Server Side:**
```python
# Extract user token from tool arguments
@app.post("/mcp")
async def mcp_endpoint(request):
    method = request.json().get("method")

    if method == "tools/call":
        params = request.json().get("params", {})
        args = params.get("arguments", {})

        # Extract user token from arguments
        user_token = args.pop("_user_token", None)
        if user_token:
            user_info = validate_user_token(user_token)
            # Use user_info for authorization
```

**Benefits:**
- ✅ No header conflicts
- ✅ Explicit user context passing
- ✅ Works with existing auth setup

**Drawbacks:**
- ❌ Requires tool wrapper
- ❌ User token visible in tool arguments (may appear in logs)
- ❌ More complex implementation

### Option 4: MCP Server-Side User Mapping

**Map client credentials to user sessions:**

```python
# ADK side: Just use client credentials
def get_mcp_headers(context):
    return {"Authorization": f"Bearer {client_token}"}

# MCP Server: Track which client credential belongs to which user
session_store = {}  # In-memory or Redis

@app.post("/mcp/authenticate")
async def authenticate_user(user_token: str, session_id: str):
    """User authenticates and links to session."""
    user_info = validate_user_token(user_token)
    client_token = generate_session_token()  # Create session-specific token
    session_store[client_token] = {
        "user": user_info,
        "session_id": session_id,
        "created": datetime.now(),
    }
    return {"token": client_token}

@app.post("/mcp")
async def mcp_endpoint(request):
    client_token = extract_token(request)
    session_data = session_store.get(client_token)

    if session_data:
        # This is a user session
        user_info = session_data["user"]
        # Enforce user-level permissions
```

**Benefits:**
- ✅ Server-side user tracking
- ✅ No ADK changes needed
- ✅ Clean separation of concerns

**Drawbacks:**
- ❌ Requires session management on server
- ❌ Complex token lifecycle
- ❌ Additional authentication endpoint

## Recommendation

For most use cases, **Option 1 (Custom User Context Header)** is the best approach:

1. Simple to implement
2. Works with ADK's header merging
3. No graph building issues
4. Clear separation of server auth vs user auth
5. Production-ready

Example implementation available in `agent_with_user_context.py`.
