"""
Streamlit UI for Space Exploration Agent connected to deployed Agent Engine
This version connects to the actual deployed agent on Vertex AI
"""

import streamlit as st
import asyncio
import os
import json
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration from .env file
PROJECT_ID = os.getenv("PROJECT_ID")
REGION = os.getenv("REGION")
AGENT_ENGINE_RESOURCE_NAME = os.getenv("AGENT_ENGINE_RESOURCE_NAME")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

# Validate required environment variables
if not all([PROJECT_ID, REGION, AGENT_ENGINE_RESOURCE_NAME]):
    st.error(
        "Missing required environment variables. "
        "Please set PROJECT_ID, REGION, and AGENT_ENGINE_RESOURCE_NAME in .env file"
    )
    st.stop()

# Page config
st.set_page_config(
    page_title="Space Exploration Assistant (Deployed Agent)",
    page_icon="🚀",
    layout="wide"
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "remote_app" not in st.session_state:
    st.session_state.remote_app = None
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "user_id" not in st.session_state:
    st.session_state.user_id = f"user_{os.urandom(8).hex()}"
if "pending_auth_config" not in st.session_state:
    st.session_state.pending_auth_config = None
if "oauth_ready" not in st.session_state:
    st.session_state.oauth_ready = False
if "paused_invocation_id" not in st.session_state:
    st.session_state.paused_invocation_id = None


def get_temp_auth_file(state: str) -> Path:
    """Get path to temporary auth config file for a given state."""
    temp_dir = Path("/var/folders/qk/99ssm7tj7_v89lrm57xn_k6m00pkm0/T/streamlit_oauth")
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"auth_{state}.json"


def save_auth_config(state: str, data: dict):
    """Save auth configuration to temporary file."""
    file_path = get_temp_auth_file(state)
    with open(file_path, 'w') as f:
        json.dump(data, f)
    print(f"Saved auth config to {file_path}", file=sys.stderr)


def load_auth_config(state: str) -> Optional[dict]:
    """Load auth configuration from temporary file."""
    file_path = get_temp_auth_file(state)
    if file_path.exists():
        with open(file_path, 'r') as f:
            data = json.load(f)
        print(f"Loaded auth config from {file_path}", file=sys.stderr)
        return data
    return None


async def initialize_remote_app():
    """Initialize connection to deployed Agent Engine."""
    if st.session_state.remote_app is None:
        try:
            print(f"Connecting to deployed agent...", file=sys.stderr)
            print(f"Resource: {AGENT_ENGINE_RESOURCE_NAME}", file=sys.stderr)

            import vertexai
            from vertexai.preview import agent_engines

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

            # Initialize Vertex AI
            vertexai.init(
                project=PROJECT_ID,
                location=REGION,
                credentials=credentials
            )

            # Get the deployed agent using agent_engines.get()
            # This returns the remote app object with async_create_session and async_stream_query methods
            st.session_state.remote_app = agent_engines.get(AGENT_ENGINE_RESOURCE_NAME)

            # Create a session
            session = await st.session_state.remote_app.async_create_session(
                user_id=st.session_state.user_id
            )

            # Handle both dict and object responses
            if isinstance(session, dict):
                st.session_state.session_id = session.get('id') or session.get('session_id')
                print(f"Connected to agent with session: {st.session_state.session_id}", file=sys.stderr)
            else:
                st.session_state.session_id = session.id
                print(f"Connected to agent with session: {session.id}", file=sys.stderr)
            return True

        except Exception as e:
            st.error(f"Failed to connect to Agent Engine: {e}")
            print(f"Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return False

    return True


async def query_agent(message_content, is_auth_response=False) -> dict:
    """Send a query to the deployed agent."""
    try:
        # Initialize connection if needed
        if not await initialize_remote_app():
            return {
                "type": "error",
                "content": "Failed to connect to Agent Engine"
            }

        # Process events from the agent
        response_parts = []
        event_count = 0
        auth_request_detected = False
        auth_url = None

        # Check if this is an auth response
        if is_auth_response and st.session_state.pending_auth_config:
            print(f"Sending auth response to agent", file=sys.stderr)

            # Format the auth response as a FunctionResponse
            function_response = {
                "role": "user",
                "parts": [{
                    "function_response": {
                        "name": "adk_request_credential",
                        "id": st.session_state.pending_auth_config['function_call_id'],
                        "response": st.session_state.pending_auth_config['auth_config']
                    }
                }]
            }

            # Send using async_stream_query with the formatted response
            events_async = st.session_state.remote_app.async_stream_query(
                user_id=st.session_state.user_id,
                session_id=st.session_state.session_id,
                message=function_response
            )
        else:
            # Regular message query
            print(f"Sending query: {message_content}", file=sys.stderr)
            events_async = st.session_state.remote_app.async_stream_query(
                user_id=st.session_state.user_id,
                session_id=st.session_state.session_id,
                message=message_content
            )

        # Process the event stream
        async for event in events_async:
            event_count += 1
            print(f"\n=== EVENT {event_count} ===", file=sys.stderr)
            print(f"Event: {event}", file=sys.stderr)

            # Check for authentication request in the event
            if isinstance(event, dict):
                # Check for function call requesting credentials
                parts = event.get('parts', [])
                for part in parts:
                    if isinstance(part, dict) and 'function_call' in part:
                        fc = part['function_call']
                        if fc.get('name') == 'adk_request_credential':
                            print("Authentication required by agent", file=sys.stderr)
                            auth_request_detected = True

                            # Extract auth config from function call args
                            args = fc.get('args', {})
                            auth_config = args.get('authConfig') or args.get('auth_config')
                            function_call_id = fc.get('id')

                            if auth_config:
                                # Extract OAuth URL and state
                                exc = auth_config.get('exchangedAuthCredential', {})
                                oauth2 = exc.get('oauth2', {})
                                auth_url = oauth2.get('authUri') or oauth2.get('auth_uri')
                                state = oauth2.get('state')

                                if auth_url and state:
                                    # Save auth config for OAuth callback
                                    storage_data = {
                                        'function_call_id': function_call_id,
                                        'auth_config': auth_config,
                                        'session_id': st.session_state.session_id,
                                        'user_id': st.session_state.user_id
                                    }
                                    save_auth_config(state, storage_data)

                                    return {
                                        "type": "auth_required",
                                        "auth_url": auth_url,
                                        "content": "Authentication required. Please click the link to authorize."
                                    }
                            break

                # Extract text content from the event
                parts = event.get('parts', [])
                for part in parts:
                    if isinstance(part, dict) and 'text' in part:
                        response_parts.append(part['text'])

        print(f"\n=== TOTAL EVENTS: {event_count} ===", file=sys.stderr)

        # Return the response
        if response_parts:
            return {
                "type": "text",
                "content": "\n\n".join(response_parts)
            }
        elif auth_request_detected:
            return {
                "type": "error",
                "content": "Authentication was requested but couldn't extract the authorization URL."
            }
        else:
            return {
                "type": "text",
                "content": "I received your message but couldn't generate a response."
            }

    except AttributeError as e:
        if "async_create_session" in str(e) or "async_stream_query" in str(e):
            return {
                "type": "error",
                "content": f"The deployed agent doesn't support the required methods. This might be because the agent wasn't deployed with the latest ADK version or the client library needs updating. Error: {str(e)}"
            }
        else:
            raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {
            "type": "error",
            "content": f"Error: {str(e)}"
        }


def display_oauth_message(auth_url):
    """Display OAuth authorization message."""
    st.warning("🔐 **Authorization Required**")
    st.markdown(f"""
    To access the Apollo GraphQL API, you need to authorize this application.

    **Click the link below to authorize:**

    [{auth_url}]({auth_url})

    After authorizing, you'll be redirected back here automatically.
    """)


# Main UI
st.title("🚀 Space Exploration Assistant")
st.caption("Connected to Deployed Agent Engine")

# Display connection status
if st.session_state.remote_app:
    st.success(f"✅ Connected to Agent Engine")
else:
    st.info("📡 Connecting to Agent Engine...")

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("type") == "auth_required":
            display_oauth_message(message.get("auth_url"))
        else:
            st.markdown(message["content"])

# Handle OAuth callback
query_params = st.query_params
if "code" in query_params and "state" in query_params:
    code = query_params["code"]
    state = query_params["state"]

    # Load the saved auth config
    stored_data = load_auth_config(state)

    if stored_data:
        # Restore session information
        st.session_state.session_id = stored_data['session_id']
        st.session_state.user_id = stored_data['user_id']

        # Update auth config with callback URL
        auth_config = stored_data['auth_config']
        callback_url = f"http://127.0.0.1:8501/?code={code}&state={state}"

        # Handle both camelCase and snake_case variations
        if 'exchangedAuthCredential' in auth_config:
            if 'oauth2' in auth_config['exchangedAuthCredential']:
                auth_config['exchangedAuthCredential']['oauth2']['authResponseUri'] = callback_url
        elif 'exchanged_auth_credential' in auth_config:
            if 'oauth2' in auth_config['exchanged_auth_credential']:
                auth_config['exchanged_auth_credential']['oauth2']['auth_response_uri'] = callback_url

        # Store the auth config for sending
        st.session_state.pending_auth_config = {
            'function_call_id': stored_data['function_call_id'],
            'auth_config': auth_config
        }
        st.session_state.oauth_ready = True

        print(f"OAuth callback processed", file=sys.stderr)

        # Clear query params and rerun
        st.query_params.clear()
        st.rerun()

# Send auth response if OAuth was completed
if st.session_state.get('oauth_ready'):
    st.info("✅ OAuth completed! Resuming agent invocation...")

    if st.session_state.pending_auth_config:
        # Send auth response to resume invocation
        with st.chat_message("assistant"):
            with st.spinner("Resuming with authentication..."):
                response = asyncio.run(query_agent(None, is_auth_response=True))

                if response["type"] == "text":
                    st.markdown(response["content"])
                elif response["type"] == "error":
                    st.error(response["content"])

                # Add to chat history
                st.session_state.messages.append({
                    "role": "assistant",
                    "type": response["type"],
                    "content": response["content"]
                })

        # Clear OAuth state
        st.session_state.oauth_ready = False
        st.session_state.pending_auth_config = None

# Chat input
if prompt := st.chat_input("Ask about space exploration..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Display user message
    with st.chat_message("user"):
        st.markdown(prompt)

    # Get agent response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = asyncio.run(query_agent(prompt))

            if response["type"] == "auth_required":
                display_oauth_message(response["auth_url"])
            elif response["type"] == "text":
                st.markdown(response["content"])
            elif response["type"] == "error":
                st.error(response["content"])

            # Add to chat history
            st.session_state.messages.append({
                "role": "assistant",
                **response
            })