"""Streamlit Chatbot UI for Space Explorer Agent with OAuth Handling."""

import streamlit as st
import asyncio
from typing import Optional
import os
import sys

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import google.auth
import google.auth.transport.requests
from google.genai import types as genai_types
import vertexai

# Configuration - from environment variables (.env file)
PROJECT_ID = os.getenv("PROJECT_ID")
REGION = os.getenv("REGION")
AGENT_ENGINE_RESOURCE_NAME = os.getenv("AGENT_ENGINE_RESOURCE_NAME")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")  # Optional: use access token instead of gcloud auth

# Validate required environment variables
if not all([PROJECT_ID, REGION, AGENT_ENGINE_RESOURCE_NAME]):
    raise ValueError(
        "Missing required environment variables. "
        "Please set PROJECT_ID, REGION, and AGENT_ENGINE_RESOURCE_NAME in .env file"
    )

# Page config
st.set_page_config(
    page_title="Space Explorer Agent",
    page_icon="🚀",
    layout="wide"
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_id" not in st.session_state:
    st.session_state.user_id = "user_123"
if "agent_client" not in st.session_state:
    st.session_state.agent_client = None
if "agent_session_id" not in st.session_state:
    st.session_state.agent_session_id = None
if "pending_auth_config" not in st.session_state:
    st.session_state.pending_auth_config = None  # Store auth request to complete later
if "oauth_ready" not in st.session_state:
    st.session_state.oauth_ready = False  # Flag when OAuth code is received


def initialize_agent_client():
    """Initialize connection to deployed Agent Engine agent."""
    if st.session_state.agent_client is None:
        try:
            # Create credentials from access token if provided
            credentials = None
            if ACCESS_TOKEN:
                from google.auth.credentials import Credentials

                class StaticCredentials(Credentials):
                    """Simple credentials using a static access token."""
                    def __init__(self, token):
                        super().__init__()
                        self.token = token
                        self.expiry = None

                    def refresh(self, request):
                        pass

                    def apply(self, headers, token=None):
                        headers['authorization'] = f'Bearer {self.token}'

                    @property
                    def expired(self):
                        return False

                    @property
                    def valid(self):
                        return True

                credentials = StaticCredentials(ACCESS_TOKEN)

            # Initialize Vertex AI with production endpoint
            vertexai.init(
                project=PROJECT_ID,
                location=REGION,
                credentials=credentials,
            )

            # Get the deployed agent
            from vertexai.agent_engines import AgentEngine
            st.session_state.agent_client = AgentEngine(
                resource_name=AGENT_ENGINE_RESOURCE_NAME
            )

            return True
        except Exception as e:
            st.error(f"Failed to connect to Agent Engine: {e}")
            import traceback
            st.error(traceback.format_exc())
            return False
    return True


async def query_agent(user_message: str) -> dict:
    """Query the deployed agent using async_stream_query with session management."""
    import sys
    import uuid

    try:
        # Create or get session for this user
        if st.session_state.agent_session_id is None:
            print(f"Creating new session for user_id: {st.session_state.user_id}", file=sys.stderr)
            session_response = await st.session_state.agent_client.async_create_session(
                user_id=st.session_state.user_id
            )
            st.session_state.agent_session_id = session_response["id"]
            print(f"Created session: {st.session_state.agent_session_id}", file=sys.stderr)

        # Check if we have a pending OAuth response to send
        message_content = None
        if st.session_state.get('oauth_ready') and st.session_state.pending_auth_config:
            # Send auth response as a function_response
            function_call_id = st.session_state.pending_auth_config['function_call_id']
            auth_config = st.session_state.pending_auth_config['auth_config']

            message_content = {
                "role": "user",
                "parts": [{
                    "function_response": {
                        "name": "adk_request_credential",
                        "id": function_call_id,
                        "response": auth_config
                    }
                }]
            }
            print(f"Sending auth response with function_call_id: {function_call_id}", file=sys.stderr)
            # Clear the OAuth state
            st.session_state.oauth_ready = False
            st.session_state.pending_auth_config = None
        else:
            # Regular text message
            message_content = user_message

        # Query with session
        response_parts = []
        oauth_detected = False
        auth_url = None
        event_count = 0

        print(f"Querying agent with user_id: {st.session_state.user_id}, session_id: {st.session_state.agent_session_id}", file=sys.stderr)

        async for event in st.session_state.agent_client.async_stream_query(
            user_id=st.session_state.user_id,
            session_id=st.session_state.agent_session_id,
            message=message_content,
        ):
            event_count += 1
            # Debug: Log event details to stderr
            print(f"\n=== EVENT {event_count} ===", file=sys.stderr)
            print(f"Type: {type(event)}", file=sys.stderr)
            print(f"Event: {event}", file=sys.stderr)
            print(f"Dir: {[a for a in dir(event) if not a.startswith('_')]}", file=sys.stderr)

            # Process each event - extract text from various possible structures
            event_str = str(event)

            # Check for OAuth requirement and extract auth URL
            # Only set oauth_detected if we successfully extract a URL
            if isinstance(event, dict) and 'actions' in event:
                actions = event['actions']
                if isinstance(actions, dict) and 'requested_auth_configs' in actions:
                    auth_configs = actions['requested_auth_configs']
                    # auth_configs is a dict with credential keys
                    if isinstance(auth_configs, dict) and len(auth_configs) > 0:
                        # Get first auth config
                        first_key = next(iter(auth_configs))
                        auth_config = auth_configs[first_key]
                        # Store the auth config and function call ID for later
                        st.session_state.pending_auth_config = {
                            'function_call_id': first_key,
                            'auth_config': auth_config
                        }
                        # Extract auth_uri from exchanged_auth_credential
                        if isinstance(auth_config, dict) and 'exchanged_auth_credential' in auth_config:
                            exchanged = auth_config['exchanged_auth_credential']
                            if isinstance(exchanged, dict) and 'oauth2' in exchanged:
                                oauth2 = exchanged['oauth2']
                                if isinstance(oauth2, dict) and 'auth_uri' in oauth2:
                                    auth_url = oauth2['auth_uri']
                                    oauth_detected = True
                                    print(f"Found authorization URL: {auth_url}", file=sys.stderr)
                                    print(f"Stored auth config with ID: {first_key}", file=sys.stderr)

            # Extract content from event
            extracted_text = None

            # Try dictionary access first (most common for streaming events)
            if isinstance(event, dict):
                # Check for content.parts[].text pattern
                if 'content' in event and isinstance(event['content'], dict):
                    if 'parts' in event['content']:
                        parts = event['content']['parts']
                        if isinstance(parts, list):
                            for part in parts:
                                if isinstance(part, dict) and 'text' in part:
                                    extracted_text = part['text']
                                    break
                # Check for direct text field
                elif 'text' in event:
                    extracted_text = event['text']
            # Try attribute access for object-based events
            elif hasattr(event, 'content'):
                content = event.content
                if hasattr(content, 'parts'):
                    for part in content.parts:
                        if hasattr(part, 'text'):
                            extracted_text = part.text
                            break
                elif isinstance(content, str):
                    extracted_text = content
            elif hasattr(event, 'text'):
                extracted_text = event.text

            if extracted_text:
                print(f"Extracted text: {extracted_text}", file=sys.stderr)
                response_parts.append(extracted_text)
            else:
                # Don't append metadata-only events
                print(f"Skipping event (no text or metadata-only): {event_str[:100]}", file=sys.stderr)

        print(f"\n=== TOTAL EVENTS: {event_count} ===", file=sys.stderr)

        # Combine response
        full_response = '\n'.join(response_parts)

        if oauth_detected:
            return {
                "type": "oauth",
                "content": "Authentication required to access MCP tools.",
                "auth_url": auth_url,  # Use extracted URL from AuthConfig
                "requires_auth": True
            }

        return {
            "type": "text",
            "content": full_response if full_response else "No response from agent.",
            "requires_auth": False
        }

    except Exception as e:
        error_msg = str(e)

        # Check if it's an OAuth-related error
        if "auth" in error_msg.lower() or "oauth" in error_msg.lower():
            return {
                "type": "oauth",
                "content": f"Authentication required: {error_msg}",
                "auth_url": None,  # No URL available from exception
                "requires_auth": True
            }
        else:
            import traceback
            return {
                "type": "error",
                "content": f"Error: {error_msg}\n\nTraceback:\n{traceback.format_exc()}",
                "requires_auth": False
            }


def display_oauth_message(auth_url: Optional[str] = None):
    """Display OAuth authentication instructions."""
    st.warning("🔐 **OAuth Authentication Required**")

    if auth_url:
        st.markdown("""
        The Space Explorer Agent needs authentication to access MCP tools.

        **To authenticate:**
        1. Click the authorization button below
        2. Sign in with your Auth0 credentials
        3. You'll be redirected back here automatically
        4. Send any message to retry your request
        """)

        # Store pending_auth_config in localStorage before redirect
        import streamlit.components.v1 as components
        import json

        if st.session_state.pending_auth_config:
            auth_config_json = json.dumps(st.session_state.pending_auth_config)
            # Escape for JavaScript
            auth_config_json_escaped = auth_config_json.replace("'", "\\'").replace('"', '\\"')
            js_safe_url = auth_url.replace("'", "\\'")

            redirect_html = f"""
            <script>
                function authorizeAndRedirect() {{
                    // Store auth config in localStorage
                    localStorage.setItem('pending_auth_config', '{auth_config_json_escaped}');
                    // Redirect to Auth0
                    window.location.href = '{js_safe_url}';
                }}
            </script>
            <button onclick="authorizeAndRedirect();"
                    style="background-color: #FF4B4B; color: white; padding: 0.5rem 1rem; border: none; border-radius: 0.25rem; cursor: pointer; font-size: 1rem; font-weight: 500;">
                🔗 Authorize Access
            </button>
            """
            components.html(redirect_html, height=50)
        else:
            st.link_button("🔗 Authorize Access", auth_url, use_container_width=False)

        st.info("💡 Once authenticated, the agent can access space mission data, rocket launches, and astronaut information.")
    else:
        st.error("Authentication is required but no authorization URL was provided by the agent. Please check the agent logs.")


def handle_oauth_callback():
    """Handle OAuth callback from Auth0."""
    import streamlit.components.v1 as components
    import json

    query_params = st.query_params

    if "code" in query_params and "state" in query_params:
        code = query_params["code"]
        state = query_params["state"]

        # Try to restore from session state first, then from localStorage via JS
        if st.session_state.pending_auth_config is None:
            # Try to restore from localStorage
            restore_script = """
            <script>
                const stored = localStorage.getItem('pending_auth_config');
                if (stored) {
                    window.parent.postMessage({type: 'auth_restore', data: stored}, '*');
                }
            </script>
            """
            components.html(restore_script, height=0)

            # Check if we got it from query param (set by the restore script in main())
            if "auth_config" in query_params:
                try:
                    st.session_state.pending_auth_config = json.loads(query_params["auth_config"])
                    print(f"Restored auth config from localStorage", file=sys.stderr)
                except Exception as e:
                    print(f"Failed to parse auth config: {e}", file=sys.stderr)

        # Now process the callback
        if st.session_state.pending_auth_config:
            auth_config = st.session_state.pending_auth_config['auth_config']
            if 'exchanged_auth_credential' in auth_config and 'oauth2' in auth_config['exchanged_auth_credential']:
                callback_url = f"http://127.0.0.1:8501/?code={code}&state={state}"
                auth_config['exchanged_auth_credential']['oauth2']['auth_response_uri'] = callback_url

                if auth_config['exchanged_auth_credential']['oauth2'].get('state') == state:
                    st.session_state.oauth_ready = True
                    print(f"OAuth complete! Callback URL: {callback_url}", file=sys.stderr)

                    # Clear localStorage
                    cleanup_html = "<script>localStorage.removeItem('pending_auth_config');</script>"
                    components.html(cleanup_html, height=0)

                    # Clear query params and reload
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error(f"State mismatch! Got: {state}")
        else:
            st.warning("Session expired. Restore failed. Please try again.")
            if st.button("Clear and Restart"):
                st.query_params.clear()
                components.html("<script>localStorage.removeItem('pending_auth_config');</script>", height=0)
                st.rerun()

    return False


def main():
    """Main Streamlit app."""

    # Restore pending_auth_config from localStorage if available
    import streamlit.components.v1 as components

    # Check localStorage and restore to session state
    restore_html = """
    <script>
        const authConfig = localStorage.getItem('pending_auth_config');
        if (authConfig) {
            // Send to Streamlit via query param
            const currentUrl = new URL(window.location.href);
            if (!currentUrl.searchParams.has('auth_restored')) {
                currentUrl.searchParams.set('auth_config', authConfig);
                currentUrl.searchParams.set('auth_restored', 'true');
                window.location.href = currentUrl.toString();
            }
        }
    </script>
    """
    components.html(restore_html, height=0)

    # Restore from query param
    query_params = st.query_params
    if "auth_config" in query_params and st.session_state.pending_auth_config is None:
        import json
        try:
            st.session_state.pending_auth_config = json.loads(query_params["auth_config"])
            print(f"Restored pending_auth_config from localStorage", file=sys.stderr)
        except Exception as e:
            print(f"Failed to restore auth config: {e}", file=sys.stderr)

    # Check if this is an OAuth callback
    if handle_oauth_callback():
        return

    # Header
    st.title("🚀 Space Explorer Agent")
    st.markdown("Ask me about space missions, rocket launches, or astronauts!")

    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuration")
        st.text_input("User ID", value=st.session_state.user_id, key="user_id_input", disabled=True)

        st.markdown("---")
        st.markdown("### 📊 Status")

        if initialize_agent_client():
            st.success("✅ Connected to Agent Engine")
            st.code(f"Region: {REGION}", language="text")
        else:
            st.error("❌ Not connected")

        st.markdown("---")
        st.markdown("### 🛠️ MCP Tools")
        st.markdown("""
        - Space launches
        - Astronaut data
        - Celestial bodies
        - Mission information
        """)

        if st.button("Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

        if st.button("Clear Session", use_container_width=True):
            st.session_state.agent_session_id = None
            st.info("Session cleared. A new session will be created on next query.")
            st.rerun()

    # Chat interface
    chat_container = st.container()

    # Display chat history
    with chat_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                if message["type"] == "text":
                    st.markdown(message["content"])
                elif message["type"] == "oauth":
                    display_oauth_message(message.get("auth_url"))
                elif message["type"] == "error":
                    st.error(message["content"])

    # Show message if OAuth was completed
    if st.session_state.get('oauth_ready'):
        st.info("✅ OAuth completed! Send any message to retry your request with authentication.")

    # Chat input
    if prompt := st.chat_input("Ask about space exploration..."):
        # Add user message
        st.session_state.messages.append({
            "role": "user",
            "type": "text",
            "content": prompt
        })

        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)

        # Get agent response
        with st.chat_message("assistant"):
            with st.spinner("Agent thinking..."):
                # Run async query
                response = asyncio.run(query_agent(prompt))

                if response["type"] == "text":
                    st.markdown(response["content"])
                elif response["type"] == "oauth":
                    display_oauth_message(response.get("auth_url"))
                elif response["type"] == "error":
                    st.error(response["content"])

                # Add to chat history
                st.session_state.messages.append({
                    "role": "assistant",
                    "type": response["type"],
                    "content": response["content"],
                    "auth_url": response.get("auth_url")
                })


if __name__ == "__main__":
    main()
