"""Space Explorer Agent - Uses Apollo MCP Server to explore space data.

OAuth approach (based on ADK sample pattern):
- Auth0 authorization code grant flow for user authentication
- Client credentials flow for initial MCP connection (listTools)
- ADK-managed credential lifecycle via oauth_helper
- Automatic token refresh with offline_access scope
"""

import os
import requests
from typing import Union
from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.auth.auth_credential import AuthCredential, AuthCredentialTypes, OAuth2Auth
from google.adk.auth.auth_schemes import ExtendedOAuth2
from google.adk.auth.auth_tool import AuthConfig
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.tool_context import ToolContext
from fastapi.openapi.models import OAuthFlowAuthorizationCode, OAuthFlows

from .oauth_helper import get_user_credentials


# Auth0 configuration from environment variables (.env file)
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
CLIENT_ID = os.getenv("AUTH0_CLIENT_ID")
CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET")
API_AUDIENCE = os.getenv("AUTH0_API_AUDIENCE")
REDIRECT_URI = os.getenv("ADK_CALLBACK_URL", "http://127.0.0.1:8081/dev-ui/")

# Validate required environment variables
if not all([AUTH0_DOMAIN, CLIENT_ID, CLIENT_SECRET, API_AUDIENCE]):
    raise ValueError(
        "Missing required Auth0 environment variables. "
        "Please set AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET, AUTH0_API_AUDIENCE in .env"
    )

SCOPES = ["read:users", "openid", "profile", "email", "offline_access"]
CREDENTIAL_CACHE_KEY = "auth0_mcp_credential"


def _get_credentials_or_auth_request(
    tool_context: ToolContext,
) -> Union[AuthCredential, AuthConfig]:
    """Get user credentials or return auth request.

    This function follows the ADK sample pattern from:
    https://github.com/VeerMuchandi/Learn_ADK_Agents/blob/main/route_planner_agent/route_planner.py
    """
    return get_user_credentials(
        tool_context=tool_context,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scopes=SCOPES,
        credential_cache_key=CREDENTIAL_CACHE_KEY,
        auth0_domain=AUTH0_DOMAIN,
        api_audience=API_AUDIENCE,
    )


def get_mcp_headers(context: ReadonlyContext) -> dict[str, str]:
    """Provides Auth0 authentication headers for MCP server connection.

    For initial MCP connection (listTools), we use client credentials flow
    since we need a token before user authentication.
    """
    token_payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "audience": API_AUDIENCE,
        "grant_type": "client_credentials",
    }
    token_url = f"https://{AUTH0_DOMAIN}/oauth/token"

    token_response = requests.post(token_url, data=token_payload, timeout=10)
    token_data = token_response.json()

    if "access_token" not in token_data:
        raise RuntimeError(f"Failed to get access token: {token_data}")

    return {
        "Authorization": f"Bearer {token_data['access_token']}",
        "Content-Type": "application/json",
    }


# Configure OAuth2 auth scheme for Auth0 with authorization code flow
auth_scheme = ExtendedOAuth2(
    flows=OAuthFlows(
        authorizationCode=OAuthFlowAuthorizationCode(
            authorizationUrl=f"https://{AUTH0_DOMAIN}/authorize",
            tokenUrl=f"https://{AUTH0_DOMAIN}/oauth/token",
            scopes={scope: scope for scope in SCOPES},
        )
    ),
    issuer_url=f"https://{AUTH0_DOMAIN}",
)

# Configure OAuth2 credentials with audience
auth_credential = AuthCredential(
    auth_type=AuthCredentialTypes.OAUTH2,
    oauth2=OAuth2Auth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        audience=API_AUDIENCE,
        redirect_uri=REDIRECT_URI,
    ),
)

# Create MCP toolset with both header_provider and auth config
# header_provider: for MCP connection authentication
# auth_scheme/credential: for tool-level authentication (ADK-managed)
mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://127.0.0.1:8000/mcp",
        timeout=10.0,
    ),
    header_provider=get_mcp_headers,
    auth_scheme=auth_scheme,
    auth_credential=auth_credential,
    tool_name_prefix="space",
)

# Define the root agent
root_agent = LlmAgent(
    name="space_explorer",
    model="gemini-2.0-flash-exp",
    instruction="""You are a space exploration assistant with access to The Space Devs API.

You can help users with:
- Finding information about upcoming rocket launches
- Learning about astronauts and who's currently in space
- Exploring information about celestial bodies and space missions

When answering questions:
1. Use the available space tools to get accurate, real-time data
2. Provide detailed and engaging responses about space exploration
3. If asked about current launches or astronauts, always use the tools to get the latest information
4. Be enthusiastic about space exploration!

Available tools allow you to:
- Search for upcoming launches
- Get details about astronauts
- Find out who's currently in space
- Explore celestial bodies and space objects
""",
    description="An AI agent that explores space data using The Space Devs GraphQL API through an authenticated MCP server",
    tools=[mcp_toolset],
)
