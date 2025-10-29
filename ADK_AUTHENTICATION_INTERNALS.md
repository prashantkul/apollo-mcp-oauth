# ADK Authentication Internals: How header_provider and auth_scheme Work Together

This document explains the internal implementation of Google ADK's authentication mechanisms for MCP tools, based on source code analysis.

## Executive Summary

When a tool is executed, ADK **merges** both `header_provider` headers and `auth_scheme` credentials into a single set of HTTP headers sent to the MCP server. The credentials from `auth_scheme` are **NOT** sent in the request body - they are converted to HTTP headers and combined with `header_provider` headers.

## The Question

When `callTool` is executed with both `header_provider` and `auth_scheme` configured:
- Does ADK use the `header_provider` token OR the `auth_scheme` user token in the Authorization header?
- Are both tokens sent? If so, how?
- Does the user token get passed in the MCP request body instead of headers?

## The Answer

**Both are used together and merged into HTTP headers.**

The authentication flow works as follows:

1. **auth_scheme credentials** are converted to HTTP headers (e.g., `Authorization: Bearer <user_token>`)
2. **header_provider** returns additional HTTP headers
3. **Both sets of headers are merged** into a single dictionary
4. If there's a collision (same header key), **header_provider wins** (overrides auth_scheme)
5. The merged headers are sent with **all MCP server requests**

## Source Code Analysis

### 1. McpToolset Initialization

**File:** `google/adk/tools/mcp_tool/mcp_toolset.py`

Both authentication parameters are stored during initialization:

```python
def __init__(
    self,
    *,
    connection_params: ...,
    auth_scheme: Optional[AuthScheme] = None,
    auth_credential: Optional[AuthCredential] = None,
    header_provider: Optional[Callable[[ReadonlyContext], Dict[str, str]]] = None,
):
    self._auth_scheme = auth_scheme
    self._auth_credential = auth_credential
    self._header_provider = header_provider
```

### 2. Tool Execution Flow

**File:** `google/adk/tools/mcp_tool/mcp_tool.py` (lines 187-220)

The `_run_async_impl` method handles tool execution:

```python
async def _run_async_impl(
    self, *, args, tool_context: ToolContext, credential: AuthCredential
) -> Dict[str, Any]:
    # Step 1: Extract auth headers from credential (from auth_scheme)
    auth_headers = await self._get_headers(tool_context, credential)

    # Step 2: Get dynamic headers from header_provider
    dynamic_headers = None
    if self._header_provider:
        dynamic_headers = self._header_provider(
            ReadonlyContext(tool_context._invocation_context)
        )

    # Step 3: MERGE both sets of headers
    headers: Dict[str, str] = {}
    if auth_headers:
        headers.update(auth_headers)  # Add auth headers first
    if dynamic_headers:
        headers.update(dynamic_headers)  # Add/override with dynamic headers
    final_headers = headers if headers else None

    # Step 4: Create session with merged headers
    session = await self._mcp_session_manager.create_session(
        headers=final_headers
    )

    # Step 5: Call the MCP tool
    response = await session.call_tool(self._mcp_tool.name, arguments=args)
    return response.model_dump(exclude_none=True, mode="json")
```

### 3. Credential to Header Conversion

**File:** `google/adk/tools/mcp_tool/mcp_tool.py` (lines 222-304)

The `_get_headers` method converts `auth_scheme` credentials to HTTP headers:

```python
async def _get_headers(
    self, tool_context: ToolContext, credential: AuthCredential
) -> Optional[dict[str, str]]:
    headers: Optional[dict[str, str]] = None
    if credential:
        # OAuth2: Bearer token in Authorization header
        if credential.oauth2:
            headers = {"Authorization": f"Bearer {credential.oauth2.access_token}"}

        # HTTP Auth: Bearer/Basic/Custom schemes
        elif credential.http:
            if credential.http.scheme.lower() == "bearer":
                headers = {"Authorization": f"Bearer {credential.http.credentials.token}"}
            elif credential.http.scheme.lower() == "basic":
                credentials = f"{credential.http.credentials.username}:{credential.http.credentials.password}"
                encoded_credentials = base64.b64encode(credentials.encode()).decode()
                headers = {"Authorization": f"Basic {encoded_credentials}"}
            else:
                headers = {"Authorization": f"{credential.http.scheme} {credential.http.credentials.token}"}

        # API Key: Custom header name (ONLY header-based, not query/cookie)
        elif credential.api_key:
            headers = {
                self._credentials_manager._auth_config.auth_scheme.name: credential.api_key
            }

    return headers
```

## Detailed Authentication Flow

### Scenario: Our Space Agent Implementation

```python
mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(...),
    header_provider=get_mcp_headers,      # Returns client credentials token
    auth_scheme=auth_scheme,              # OAuth2 authorization code flow
    auth_credential=auth_credential,      # User OAuth2 credentials
)
```

### When a Tool is Called

**Step 1: Get auth_scheme headers**
```python
# ADK converts user's OAuth2 credential to header
auth_headers = {"Authorization": "Bearer <user_access_token>"}
```

**Step 2: Get header_provider headers**
```python
# Our get_mcp_headers() function is called
dynamic_headers = get_mcp_headers(context)
# Returns: {"Authorization": "Bearer <client_credentials_token>", "Content-Type": "application/json"}
```

**Step 3: Merge headers**
```python
headers = {}
headers.update(auth_headers)      # {"Authorization": "Bearer <user_access_token>"}
headers.update(dynamic_headers)   # Overwrites with client credentials!
# Final: {"Authorization": "Bearer <client_credentials_token>", "Content-Type": "application/json"}
```

**Step 4: Send to MCP server**
```
POST http://127.0.0.1:8000/mcp
Headers:
  Authorization: Bearer <client_credentials_token>  ← From header_provider (won the collision!)
  Content-Type: application/json
```

## Important Discovery: Header Collision

**In our implementation, there's a collision!**

Both `auth_scheme` and `header_provider` try to set the `Authorization` header:
- `auth_scheme` → `Authorization: Bearer <user_token>`
- `header_provider` → `Authorization: Bearer <client_credentials_token>`

Since `header_provider` is applied **after** `auth_scheme`, the **client credentials token wins**.

### What This Means for Our Implementation

Our MCP server is **always receiving the client credentials token**, not the user token!

The user authentication flow (OAuth consent screen) is happening, and ADK is managing user credentials, but those credentials are being **overridden** by `header_provider` before reaching the MCP server.

### Why It Still Works

Our implementation works because:
1. The MCP server only validates that **some valid Auth0 token** is present
2. The client credentials token is valid for the API audience
3. We don't need user-specific permissions at the MCP level

### Alternative Approaches

**Option 1: Remove header_provider for tool calls (use only for initialization)**

This would require conditional logic - not directly supported by McpToolset.

**Option 2: Modify header_provider to check for user credentials**

```python
def get_mcp_headers(context: ReadonlyContext) -> dict[str, str]:
    # Check if user token is available in session
    user_cred = context.get_from_session_state(CREDENTIAL_CACHE_KEY)
    if user_cred and user_cred.oauth2 and user_cred.oauth2.access_token:
        # User is authenticated, don't override
        return {"Content-Type": "application/json"}
    else:
        # No user token, use client credentials
        token = get_auth0_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
```

**Option 3: Accept current behavior**

If user-level permissions aren't needed, the current implementation is fine.

## Test Evidence

**File:** `tests/unittests/tools/mcp_tool/test_mcp_tool.py` (lines 690-730)

```python
async def test_run_async_impl_with_header_provider_and_oauth2(self):
    """Test running tool with header_provider and OAuth2 auth."""
    dynamic_headers = {"X-Tenant-ID": "test-tenant"}
    header_provider = Mock(return_value=dynamic_headers)

    oauth2_auth = OAuth2Auth(access_token="test_access_token")
    credential = AuthCredential(
        auth_type=AuthCredentialTypes.OAUTH2, oauth2=oauth2_auth
    )

    # ... execute tool ...

    # Verify merged headers
    headers = call_args[1]["headers"]
    assert headers == {
        "Authorization": "Bearer test_access_token",  # From auth_scheme
        "X-Tenant-ID": "test-tenant",                # From header_provider
    }
```

**Note:** In this test, `header_provider` returns `X-Tenant-ID` (not Authorization), so there's no collision. Both headers coexist peacefully.

## Key Findings Summary

1. ✅ **Both authentication mechanisms are converted to HTTP headers**
2. ✅ **Headers from both sources are merged**
3. ✅ **header_provider wins in case of collision** (applied last)
4. ✅ **User credentials are NOT sent in request body**
5. ⚠️ **In our implementation, header_provider overrides auth_scheme's Authorization header**
6. ✅ **This is why MCP server always sees client credentials token**

## Relevant Source Files

1. **McpToolset:** `google/adk/tools/mcp_tool/mcp_toolset.py` (lines 95-236)
2. **McpTool (header merging):** `google/adk/tools/mcp_tool/mcp_tool.py` (lines 187-220)
3. **Credential conversion:** `google/adk/tools/mcp_tool/mcp_tool.py` (lines 222-304)
4. **Session management:** `google/adk/tools/mcp_tool/mcp_session_manager.py` (lines 297-373)
5. **Test evidence:** `tests/unittests/tools/mcp_tool/test_mcp_tool.py` (lines 690-730)

## Recommendations

For future implementations where user-level authentication at the MCP server is required:

1. **Don't set Authorization in header_provider** if auth_scheme is configured
2. **Use header_provider for non-Authorization headers** (e.g., custom headers, API keys)
3. **Let auth_scheme handle Authorization header** when user auth is needed
4. **Use conditional logic in header_provider** to detect user authentication state

## Conclusion

ADK's authentication model is elegant: it treats all credentials as HTTP headers and merges them. The flexibility comes from having two extension points (`header_provider` for dynamic headers, `auth_scheme` for standard OAuth/API key flows). However, developers must be careful about header collisions, particularly with the `Authorization` header.

In our space agent implementation, the current behavior is acceptable because the MCP server doesn't enforce user-level permissions. The OAuth consent flow still provides value by demonstrating ADK's credential management capabilities, even though the resulting user token is currently being overridden.
