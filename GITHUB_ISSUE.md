# GitHub Issue: Enhanced Authentication for Apollo MCP Server

## Issue Title
Feature Request: Support Anonymous Tool Discovery with User-Level Authorization

## Issue Body

### Summary

We've implemented an enhancement to Apollo MCP Server's authentication middleware that enables **anonymous tool discovery** while maintaining **user-level authorization** for tool execution. This change significantly improves integration with agent frameworks like Google ADK while enhancing security through per-user audit trails.

### Problem Statement

The current Apollo MCP Server requires authentication for **all** MCP protocol operations, including:
- `initialize` - Protocol handshake
- `tools/list` - Tool discovery

This creates integration challenges with modern agent frameworks that need to:
1. Build tool catalogs during agent initialization (before user authentication)
2. Authenticate users only when tools are actually executed
3. Pass user credentials (not service credentials) to the MCP server for proper authorization

**Real-world impact:**
- Agent frameworks must use client credentials (machine-to-machine) for tool discovery
- When using both `header_provider` (for discovery) and `auth_scheme` (for user auth) in Google ADK, the header_provider overrides user tokens
- MCP server only receives service credentials, preventing per-user authorization and audit logging

### Proposed Solution

Implement a **two-tier authentication model**:

1. **Anonymous Discovery** (no auth required):
   - `initialize` - MCP protocol handshake
   - `initialized` / `notifications/initialized` - Initialization notifications
   - `tools/list` - Tool discovery

2. **Authenticated Execution** (user auth required):
   - `tools/call` - Tool execution
   - Any other MCP methods

### Benefits

✅ **Better Agent Framework Integration**
- Agent frameworks can discover tools without upfront authentication
- User consent screens appear only when tools are actually used
- Natural OAuth user experience

✅ **Enhanced Security**
- Per-user authorization and access control
- Full audit trail with user identifiers
- User-specific rate limiting capabilities
- Principle of least privilege (anonymous access only to discovery)

✅ **Backward Compatibility**
- Existing clients that send auth tokens for all operations continue to work
- Progressive enhancement - doesn't break existing integrations

✅ **Production Ready**
- Comprehensive audit logging with user identifiers (`sub` field)
- Security best practices maintained
- No credential exposure

### Implementation Details

**Files Modified:**
1. `crates/apollo-mcp-server/src/auth.rs`
   - Modified `oauth_validate` middleware to parse MCP method from request body
   - Exempted discovery methods from authentication
   - Added comprehensive audit logging

2. `crates/apollo-mcp-server/src/auth/valid_token.rs`
   - Enhanced `ValidToken` to store decoded JWT claims
   - Exposed `sub` (user identifier) and `aud` (audiences) for audit logging

**Key Code Changes:**

```rust
// Parse MCP method from JSON-RPC request
let mcp_method: Option<String> = serde_json::from_slice(&body_bytes)
    .ok()
    .and_then(|v: serde_json::Value|
        v.get("method").and_then(|m| m.as_str().map(String::from))
    );

// Exempt discovery methods
let is_discovery_method = mcp_method
    .as_ref()
    .map(|m| m == "initialize" || m == "initialized"
        || m == "notifications/initialized" || m == "tools/list")
    .unwrap_or(false);

if is_discovery_method {
    tracing::debug!("Allowing anonymous access for discovery method: {:?}", mcp_method);
    return Ok(next.run(request).await);
}

// Require authentication for all other methods
tracing::info!(
    "✓ Authenticated request: method={:?}, sub={}, audiences={:?}",
    mcp_method,
    valid_token.claims.sub,
    valid_token.claims.aud
);
```

### Testing

We've successfully tested this implementation with:
- **MCP Inspector**: Tool discovery works without authentication ✓
- **Google ADK Agent**: User OAuth flow works correctly ✓
- **Auth0**: User tokens (not client credentials) reach MCP server ✓
- **Audit Logs**: User identifier logged for all authenticated requests ✓

**Example log output:**
```
DEBUG Allowing anonymous access for discovery method: Some("initialize")
DEBUG Allowing anonymous access for discovery method: Some("tools/list")
INFO  ✓ Authenticated request: method=Some("tools/call"), sub=auth0|68ffbd8aaf776b8a87695db2, audiences=["http://127.0.0.1:8000/mcp"]
```

### Security Considerations

**✅ Security Enhancements:**
- User tokens (not service credentials) for tool execution
- Complete audit trail with user identifiers
- No bypass of existing token validation
- All cryptographic checks still enforced

**⚠️ Trade-offs:**
- Tool names/schemas are publicly discoverable
  - **Mitigation**: Standard practice for many APIs (OpenAPI, GraphQL introspection)
  - **Best Practice**: Don't include sensitive info in tool descriptions

**🔒 Production Recommendations:**
- Use HTTPS/TLS in production
- Short-lived access tokens (1 hour)
- Monitor audit logs for suspicious patterns
- Implement rate limiting per user

### Use Case: Google ADK Integration

**Before** (client credentials override user tokens):
```python
mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://127.0.0.1:8000/mcp",
    ),
    header_provider=get_client_credentials,  # ❌ Required for discovery, overrides user tokens
    auth_scheme=user_oauth_scheme,           # User OAuth configured but never reaches server
    auth_credential=user_oauth_credential,
)
```

**After** (user tokens reach MCP server):
```python
mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://127.0.0.1:8000/mcp",
    ),
    # No header_provider needed - anonymous discovery works
    auth_scheme=user_oauth_scheme,           # ✅ User tokens reach MCP server
    auth_credential=user_oauth_credential,
)
```

### Documentation

We've prepared comprehensive documentation covering:
- Technical implementation details
- Security considerations and best practices
- Production deployment recommendations
- Integration guides for agent frameworks
- Troubleshooting guide
- Migration guide for existing clients

Available at: [Link to APOLLO_MCP_AUTH_IMPLEMENTATION.md]

### Request for Feedback

We'd love to contribute this enhancement back to the Apollo MCP Server project. Questions for the maintainers:

1. **Interest Level**: Is this enhancement aligned with Apollo MCP Server's roadmap?
2. **Approach**: Any concerns or suggestions about the implementation approach?
3. **Configuration**: Should anonymous discovery be configurable (opt-in/opt-out)?
4. **Additional Features**: Interest in additional enhancements like:
   - Scope-based authorization per tool
   - Role-based access control (RBAC)
   - Built-in rate limiting per user

We're happy to:
- Submit a pull request with the changes
- Add unit/integration tests
- Update official documentation
- Address any feedback or concerns

### Environment

- **Apollo MCP Server Version**: 1.1.1
- **Rust Version**: [Your Rust version]
- **Platform**: macOS (also tested on Linux)
- **Agent Framework**: Google ADK
- **Auth Provider**: Auth0
- **MCP Protocol**: Streamable HTTP

### Related Issues

- [Any related issues if found]

### References

- [MCP Protocol Specification](https://spec.modelcontextprotocol.io/)
- [Google ADK Documentation](https://github.com/google/adk-python)
- [OAuth 2.0 Best Practices](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-security-topics)

---

**Would the Apollo team be interested in accepting a PR for this enhancement?**

We're excited to contribute to the Apollo MCP ecosystem and help make authenticated MCP servers more accessible to agent frameworks! 🚀

