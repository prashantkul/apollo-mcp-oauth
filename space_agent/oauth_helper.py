"""OAuth helper for Auth0 authentication with ADK agents.

Based on: https://github.com/VeerMuchandi/Learn_ADK_Agents/blob/main/route_planner_agent/oauth_helper.py
"""

import logging
from typing import List, Union

from google.adk.auth.auth_credential import AuthCredential, AuthCredentialTypes, OAuth2Auth
from google.adk.auth.auth_schemes import ExtendedOAuth2
from google.adk.auth.auth_tool import AuthConfig
from google.adk.auth.credential_manager import CredentialManager
from google.adk.auth.exchanger.oauth2_credential_exchanger import OAuth2CredentialExchanger
from google.adk.auth.refresher.oauth2_credential_refresher import OAuth2CredentialRefresher
from google.adk.tools.tool_context import ToolContext
from fastapi.openapi.models import OAuthFlowAuthorizationCode, OAuthFlows

logger = logging.getLogger(__name__)


def get_user_credentials(
    tool_context: ToolContext,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    scopes: List[str],
    credential_cache_key: str,
    auth0_domain: str,
    api_audience: str,
) -> Union[AuthCredential, AuthConfig, None]:
    """Get user credentials for Auth0 OAuth2 flow.

    This function manages the credential lifecycle:
    1. Check for cached credentials
    2. Try to refresh if expired
    3. Handle new authorization responses
    4. Return AuthConfig to initiate new auth if needed

    Args:
        tool_context: The tool execution context
        client_id: Auth0 client ID
        client_secret: Auth0 client secret
        redirect_uri: OAuth redirect URI
        scopes: List of OAuth scopes
        credential_cache_key: Key for caching credentials
        auth0_domain: Auth0 domain (e.g., "dev-xxx.us.auth0.com")
        api_audience: Auth0 API audience/identifier

    Returns:
        AuthCredential if authenticated, AuthConfig if auth needed, None otherwise
    """
    # Step 1: Create OAuth2 auth scheme with authorization code flow
    auth_scheme = ExtendedOAuth2(
        flows=OAuthFlows(
            authorizationCode=OAuthFlowAuthorizationCode(
                authorizationUrl=f"https://{auth0_domain}/authorize",
                tokenUrl=f"https://{auth0_domain}/oauth/token",
                scopes={scope: scope for scope in scopes},
            )
        ),
        issuer_url=f"https://{auth0_domain}",
    )

    # Step 2: Create auth config with redirect_uri for authorization code flow
    auth_config = AuthConfig(
        auth_scheme=auth_scheme,
        raw_auth_credential=AuthCredential(
            auth_type=AuthCredentialTypes.OAUTH2,
            oauth2=OAuth2Auth(
                client_id=client_id,
                client_secret=client_secret,
                audience=api_audience,
                redirect_uri=redirect_uri,
            ),
        ),
    )

    # Step 3: Initialize credential manager
    credential_manager = CredentialManager(
        auth_config=auth_config,
        credential_cache_key=credential_cache_key,
    )

    # Step 4: Check for cached credential
    try:
        cached_credential = tool_context.get_from_session_state(credential_cache_key)
        if cached_credential and isinstance(cached_credential, AuthCredential):
            logger.info("Using cached Auth0 credential")

            # Check if token needs refresh
            if cached_credential.oauth2 and cached_credential.oauth2.refresh_token:
                refresher = OAuth2CredentialRefresher()
                try:
                    refreshed = refresher.refresh(cached_credential, auth_scheme)
                    if refreshed and refreshed.oauth2.access_token:
                        logger.info("Refreshed Auth0 access token")
                        tool_context.set_to_session_state(credential_cache_key, refreshed)
                        return refreshed
                except Exception as e:
                    logger.warning(f"Token refresh failed: {e}, will try to re-authenticate")

            # Return cached credential if still valid
            if cached_credential.oauth2 and cached_credential.oauth2.access_token:
                return cached_credential

    except Exception as e:
        logger.debug(f"No cached credential found: {e}")

    # Step 5: Check if we have an authorization response to handle
    auth_response_uri = tool_context.get_from_session_state("auth_response_uri")
    if auth_response_uri:
        logger.info("Processing authorization response")
        try:
            exchanger = OAuth2CredentialExchanger()
            exchanged = exchanger.exchange(
                auth_config.raw_auth_credential, auth_scheme
            )
            if exchanged and exchanged.oauth2.access_token:
                logger.info("Successfully exchanged authorization code for tokens")
                tool_context.set_to_session_state(credential_cache_key, exchanged)
                tool_context.remove_from_session_state("auth_response_uri")
                return exchanged
        except Exception as e:
            logger.error(f"Failed to exchange authorization code: {e}")

    # Step 6: No valid credential - return AuthConfig to initiate auth
    logger.info("No valid credentials, returning AuthConfig for new authorization")
    return auth_config
