# Apollo MCP Server Authentication Implementation

## Summary of Changes

This document describes the authentication modifications made to Apollo MCP Server to support user-level authorization while maintaining backward compatibility with the MCP protocol.

### Problem Statement

The original Apollo MCP Server required authentication for **all** MCP operations, including tool discovery (`initialize`, `tools/list`). This created challenges when integrating with agent frameworks like Google ADK that need to:

1. Discover available tools anonymously during agent initialization
2. Authenticate users only when tools are actually executed
3. Pass user credentials (not service credentials) to the MCP server for proper authorization

### Solution Overview

Modified the authentication middleware to implement a **two-tier authentication model**:

- **Anonymous Discovery**: Allow unauthenticated access to MCP protocol handshake and tool listing
- **Authenticated Execution**: Require user authentication for actual tool execution

This enables:
- ✅ Agent frameworks to build tool catalogs without authentication
- ✅ User consent screens only when tools are called
- ✅ True user-level authorization at the MCP server
- ✅ Per-user access control and audit logging

## Technical Implementation

### Files Modified

**`crates/apollo-mcp-server/src/auth.rs`**

Modified the `oauth_validate` middleware function to:

1. **Parse MCP Request Body**: Extract the `method` field from JSON-RPC requests
2. **Exempt Discovery Methods**: Allow anonymous access for:
   - `initialize` - MCP protocol handshake
   - `initialized` - MCP initialization notification
   - `notifications/initialized` - Alternative notification format
   - `tools/list` - Tool discovery
3. **Require Authentication**: Enforce OAuth token validation for all other methods (e.g., `tools/call`)
4. **Audit Logging**: Log authenticated requests with user identifier (`sub`) and audiences

**Key Code Changes:**

```rust
// Parse JSON-RPC request to extract method
let (parts, body) = request.into_parts();
let body_bytes = axum::body::to_bytes(body, usize::MAX)
    .await
    .map_err(|_| unauthorized_error())?;

let mcp_method: Option<String> = serde_json::from_slice(&body_bytes)
    .ok()
    .and_then(|v: serde_json::Value|
        v.get("method").and_then(|m| m.as_str().map(String::from))
    );

// Reconstruct request with body for downstream handlers
let request = Request::from_parts(parts, Body::from(body_bytes));

// Exempt discovery methods from authentication
let is_discovery_method = mcp_method
    .as_ref()
    .map(|m| {
        m == "initialize"
            || m == "initialized"
            || m == "notifications/initialized"
            || m == "tools/list"
    })
    .unwrap_or(false);

if is_discovery_method {
    tracing::debug!("Allowing anonymous access for discovery method: {:?}", mcp_method);
    return Ok(next.run(request).await);
}

// Require authentication for all other methods
tracing::debug!("Requiring authentication for method: {:?}", mcp_method);
// ... token validation ...
```

**`crates/apollo-mcp-server/src/auth/valid_token.rs`**

Enhanced the `ValidToken` structure to store decoded JWT claims:

```rust
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TokenClaims {
    pub aud: Vec<String>,  // Token audiences
    pub sub: String,       // User/service identifier
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct ValidToken {
    pub(crate) token: Authorization<Bearer>,
    pub(crate) claims: TokenClaims,
}
```

This enables:
- Access to user identifier (`sub`) for audit logging
- Verification of token audiences
- Per-user authorization logic in downstream handlers

### Authentication Flow

#### Phase 1: Anonymous Tool Discovery

```
Client → MCP Server
  POST /mcp
  {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {...}
  }

MCP Server:
  ✓ No authentication required
  ✓ Returns server capabilities
```

```
Client → MCP Server
  POST /mcp
  {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list"
  }

MCP Server:
  ✓ No authentication required
  ✓ Returns available tools
```

#### Phase 2: Authenticated Tool Execution

```
Client → MCP Server
  POST /mcp
  Authorization: Bearer <user_access_token>
  {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "GetAstronautsCurrentlyInSpace",
      "arguments": {}
    }
  }

MCP Server:
  1. Validate OAuth token with Auth0
  2. Extract user identifier (sub)
  3. Log: "✓ Authenticated request: method=Some("tools/call"), sub=auth0|68ffbd8a..."
  4. Execute tool with user context
  5. Return results
```

### Logging and Audit Trail

The authentication middleware now logs:

**Debug Level** (`RUST_LOG=debug`):
- All discovery methods allowed anonymously
- Authentication requirements for protected methods
- Token validation steps

**Info Level** (default):
- Successful authenticated requests with user identifier
- Example: `✓ Authenticated request: method=Some("tools/call"), sub=auth0|68ffbd8aaf776b8a87695db2, audiences=["http://127.0.0.1:8000/mcp"]`

**Warning Level**:
- Missing tokens for protected methods
- Invalid tokens

This provides:
- Full audit trail of user actions
- Security monitoring capabilities
- Debugging information for authentication issues

## Security Considerations

### ✅ Security Enhancements

1. **User-Level Authorization**: MCP server now receives actual user tokens, enabling:
   - Per-user access control
   - User-specific rate limiting
   - Audit trails tied to individual users

2. **Principle of Least Privilege**: Anonymous access only to discovery methods; all operations require authentication

3. **No Token Exposure**: User tokens are validated server-side; no credential leakage to client

4. **Audit Logging**: All authenticated requests logged with user identifier

### ⚠️ Security Trade-offs

1. **Public Tool Discovery**: Tool names and schemas are now publicly accessible
   - **Mitigation**: Tool descriptions don't expose sensitive data
   - **Best Practice**: Don't include sensitive information in tool names/descriptions

2. **Anonymous MCP Handshake**: Server capabilities disclosed without authentication
   - **Impact**: Minimal - only reveals server version and protocol support
   - **Standard Practice**: Many APIs allow unauthenticated OPTIONS/discovery

### 🔒 Security Best Practices

1. **Use HTTPS in Production**: Always use TLS for token transmission
   ```yaml
   # router.yaml
   server:
     listen: 0.0.0.0:8443
     tls:
       cert_file: /path/to/cert.pem
       key_file: /path/to/key.pem
   ```

2. **Rotate Client Secrets**: Regular rotation of Auth0 client secrets
   ```bash
   # Set in environment, not in code
   export AUTH0_CLIENT_SECRET=<new_secret>
   ```

3. **Token Expiration**: Use short-lived access tokens (e.g., 1 hour)
   ```
   Auth0 Dashboard → APIs → Token Expiration → 3600 seconds
   ```

4. **Monitor Audit Logs**: Set up log aggregation and alerting
   ```bash
   # Production logging
   RUST_LOG=info,apollo_mcp_server::auth=info
   ```

## Integration with Agent Frameworks

### Google ADK

**Before** (client credentials override user tokens):
```python
mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://127.0.0.1:8000/mcp",
    ),
    header_provider=get_client_credentials,  # ❌ Overrides user tokens
    auth_scheme=user_oauth_scheme,
    auth_credential=user_oauth_credential,
)
```

**After** (user tokens reach MCP server):
```python
mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://127.0.0.1:8000/mcp",
    ),
    # No header_provider - allows user tokens through
    auth_scheme=user_oauth_scheme,
    auth_credential=user_oauth_credential,
)
```

**Result**:
- Tool discovery: Anonymous (no auth prompt)
- Tool execution: User authenticates via OAuth consent screen
- MCP server receives: User's access token with their identity

### Other Agent Frameworks

Any agent framework can now:

1. **Initialize anonymously**:
   ```http
   POST /mcp
   Content-Type: application/json
   Accept: application/json, text/event-stream

   {"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
   ```

2. **List tools anonymously**:
   ```http
   POST /mcp
   Content-Type: application/json
   Accept: application/json, text/event-stream

   {"jsonrpc":"2.0","id":2,"method":"tools/list"}
   ```

3. **Call tools with user auth**:
   ```http
   POST /mcp
   Authorization: Bearer <user_token>
   Content-Type: application/json
   Accept: application/json, text/event-stream

   {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{...}}
   ```

## Production Deployment Recommendations

### 1. Environment Configuration

```yaml
# config.yaml (MCP server)
auth:
  servers:
    - https://your-domain.us.auth0.com
  audiences:
    - https://api.yourcompany.com/mcp
  resource: https://api.yourcompany.com/mcp
  scopes:
    - read:tools
    - execute:tools
```

### 2. Auth0 Configuration

**API Settings**:
- Identifier: `https://api.yourcompany.com/mcp`
- Token Expiration: 3600 seconds (1 hour)
- Allow Offline Access: Yes (for refresh tokens)

**Application Settings**:
- Application Type: Regular Web Application (NOT Machine to Machine)
- Grant Types: Authorization Code, Refresh Token
- Allowed Callback URLs: Your agent framework's callback URL
- Token Endpoint Authentication Method: Client Secret Post

**Permissions**:
- Create custom scopes for fine-grained access control
- Assign scopes to users/roles via Auth0 rules or actions

### 3. Logging Configuration

```bash
# Production
RUST_LOG=info,apollo_mcp_server::auth=info

# Debugging
RUST_LOG=debug,apollo_mcp_server::auth=debug

# Troubleshooting
RUST_LOG=trace
```

**Log Aggregation** (recommended):
- Send logs to centralized logging (Datadog, Splunk, CloudWatch)
- Set up alerts for authentication failures
- Monitor unusual patterns (e.g., excessive 401s)

### 4. Rate Limiting

Consider implementing rate limiting per user:

```rust
// Future enhancement
if let Some(rate_limiter) = &auth_config.rate_limiter {
    if !rate_limiter.check(&valid_token.claims.sub).await {
        return Err((
            StatusCode::TOO_MANY_REQUESTS,
            TypedHeader(WwwAuthenticate::Bearer { ... })
        ));
    }
}
```

### 5. Monitoring Metrics

Track these metrics:
- **Anonymous discovery requests**: `tools/list` call rate
- **Authenticated tool calls**: `tools/call` call rate per user
- **Authentication failures**: 401 response rate
- **Token validation latency**: Time to validate JWT
- **User distribution**: Unique users per day/hour

### 6. Disaster Recovery

**Token Rotation**:
```bash
# If credentials are compromised
1. Rotate Auth0 client secrets immediately
2. Revoke leaked tokens via Auth0 dashboard
3. Force user re-authentication
4. Update environment variables
5. Restart MCP server
```

**Rollback Plan**:
```bash
# If authentication changes cause issues
1. Keep previous binary: ~/.rover/bin/apollo-mcp-server-v1.1.0
2. Quick rollback: cp ~/.rover/bin/apollo-mcp-server-v1.1.0 ~/.rover/bin/apollo-mcp-server-v1.1.1
3. Restart rover dev
```

## Testing

### Manual Testing

```bash
# Test anonymous discovery
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Should return 200 with tools list

# Test authenticated call (should fail without token)
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"test"}}'

# Should return 401 Unauthorized
```

### Automated Testing

See `test_mcp_protocol.py` for comprehensive protocol tests.

## Backwards Compatibility

### Breaking Changes

⚠️ **Client applications must be updated** to handle the new authentication flow:

1. **Old Behavior**: All MCP operations required authentication
2. **New Behavior**: Discovery is anonymous, execution requires auth

### Migration Guide

**For existing MCP clients**:

1. **Remove authentication from discovery calls**:
   ```python
   # Before
   headers = {"Authorization": f"Bearer {token}"}
   session.initialize(headers=headers)

   # After
   session.initialize()  # No auth needed
   ```

2. **Add authentication to tool calls**:
   ```python
   # Before (if not using auth)
   session.call_tool("MyTool", args)

   # After
   headers = {"Authorization": f"Bearer {user_token}"}
   session.call_tool("MyTool", args, headers=headers)
   ```

3. **Update token management**:
   - Use user tokens (authorization code flow), not client credentials
   - Implement OAuth consent screen for user authorization
   - Cache and refresh user tokens

### Compatibility Matrix

| MCP Client Version | Old MCP Server | New MCP Server |
|--------------------|----------------|----------------|
| With auth on all calls | ✅ Works | ✅ Works (auth accepted but not required for discovery) |
| No auth on any calls | ❌ Fails | ⚠️ Partial (discovery works, execution fails) |
| Updated client | ❌ Fails on discovery | ✅ Works |

## Future Enhancements

### 1. Scope-Based Authorization

Add support for OAuth scopes to control tool access:

```rust
// Check if user has required scope
if !valid_token.claims.scopes.contains(&"execute:launches") {
    return Err((
        StatusCode::FORBIDDEN,
        Json(json!({"error": "insufficient_scope"}))
    ));
}
```

### 2. Role-Based Access Control (RBAC)

Integrate with Auth0 roles:

```rust
// Extract roles from token
let user_roles = extract_roles(&valid_token);
if !user_roles.contains(&"admin") {
    // Deny access to admin-only tools
}
```

### 3. Tool-Level Permissions

Fine-grained permissions per tool:

```yaml
tools:
  - name: SearchUpcomingLaunches
    required_scopes: [read:launches]
  - name: CancelLaunch
    required_scopes: [write:launches]
    required_roles: [admin]
```

### 4. Rate Limiting Per User

```rust
// Track requests per user per time window
let user_id = &valid_token.claims.sub;
if rate_limiter.is_exceeded(user_id, window_seconds, max_requests) {
    return Err(StatusCode::TOO_MANY_REQUESTS);
}
```

### 5. Webhook Notifications

Notify on suspicious activity:

```rust
if failed_auth_count > threshold {
    webhook::send_alert("Suspicious authentication activity", user_id).await;
}
```

## Troubleshooting

### Common Issues

**1. MCP Inspector shows 406 Not Acceptable**

**Solution**: Ensure Accept header includes both content types:
```http
Accept: application/json, text/event-stream
```

**2. ADK shows "401 Unauthorized" during tool execution**

**Cause**: User token not reaching MCP server

**Solution**: Remove `header_provider` from McpToolset configuration

**3. Logs show client credentials instead of user tokens**

**Check**: Look for `sub` ending in `@clients` (bad) vs `auth0|...` (good)

**Fix**: Verify agent is using authorization code flow, not client credentials

**4. Auth0 consent screen appears on every tool call**

**Cause**: Tokens not being cached

**Fix**:
- Ensure `offline_access` scope is included
- Verify refresh token is being stored
- Check ADK session state configuration

### Debug Commands

```bash
# Enable detailed auth logging
RUST_LOG=trace,apollo_mcp_server::auth=trace rover dev ...

# Test token validation
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"test"}}'

# Decode JWT token (check sub and aud)
echo $TOKEN | cut -d. -f2 | base64 -d | jq
```

## References

- [MCP Protocol Specification](https://spec.modelcontextprotocol.io/)
- [OAuth 2.0 RFC](https://datatracker.ietf.org/doc/html/rfc6749)
- [JWT RFC](https://datatracker.ietf.org/doc/html/rfc7519)
- [Auth0 Documentation](https://auth0.com/docs)
- [Apollo MCP Server](https://github.com/apollographql/apollo-mcp-server)

---

**Document Version**: 1.0
**Last Updated**: October 29, 2025
**Project**: Apollo MCP Authentication Implementation
