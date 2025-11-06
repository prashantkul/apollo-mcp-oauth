"""
Streamlit UI for Space Exploration Agent using ADK Runner directly
This version uses the ADK Runner for proper invocation resumption support
"""

import streamlit as st
import asyncio
import os
import json
import sys
from pathlib import Path
from typing import AsyncGenerator, Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import ADK components
try:
    from google.adk import runners
    from google.adk.agents import Agent
    from google.genai import types
    from google.adk.sessions import InMemorySessionService
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.auth.auth_tool import AuthToolArguments, AuthConfig
    from google.adk.flows.llm_flows.functions import REQUEST_EUC_FUNCTION_CALL_NAME
    print("ADK imports successful", file=sys.stderr)
except ImportError as e:
    st.error(f"Failed to import ADK components: {e}")
    st.stop()

# Import the space agent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from space_agent.agent import root_agent
    print(f"Agent import successful: {root_agent}", file=sys.stderr)
    if root_agent is None:
        st.error("root_agent is None - check agent.py")
        st.stop()
except ImportError as e:
    st.error(f"Failed to import agent: {e}")
    st.stop()

# Page config
st.set_page_config(
    page_title="Space Exploration Assistant (ADK Runner)",
    page_icon="🚀",
    layout="wide"
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "runner" not in st.session_state:
    st.session_state.runner = None
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


def get_auth_request_function_call(event):
    """Extract auth request function call from event."""
    if hasattr(event, 'content') and event.content and hasattr(event.content, 'parts'):
        for part in event.content.parts:
            if hasattr(part, 'function_call') and part.function_call:
                fc = part.function_call
                if hasattr(fc, 'name') and fc.name == REQUEST_EUC_FUNCTION_CALL_NAME:
                    return fc
    return None


def get_auth_config(function_call) -> Optional[Dict[str, Any]]:
    """Extract AuthConfig from the auth request function call."""
    if function_call and hasattr(function_call, 'args'):
        args = function_call.args
        # Handle both dict and object cases
        if isinstance(args, dict):
            return args.get('authConfig') or args.get('auth_config')
        elif hasattr(args, 'authConfig'):
            return args.authConfig
        elif hasattr(args, 'auth_config'):
            return args.auth_config
    return None


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


async def initialize_runner():
    """Initialize the ADK Runner with session and artifact services."""
    if st.session_state.runner is None:
        print("Initializing ADK Runner...", file=sys.stderr)

        # Create in-memory services
        session_service = InMemorySessionService()
        artifact_service = InMemoryArtifactService()

        # Create a session using the session service (async call)
        session = await session_service.create_session(
            app_name="space_explorer",
            user_id=st.session_state.user_id,
            state={}
        )

        # Create the runner with the agent
        st.session_state.runner = runners.Runner(
            app_name="space_explorer",
            agent=root_agent,
            session_service=session_service,
            artifact_service=artifact_service
        )

        # Store in session state
        st.session_state.session_service = session_service
        st.session_state.artifact_service = artifact_service
        st.session_state.session_id = session.id

        print(f"Runner initialized with session: {session.id}", file=sys.stderr)


async def query_agent(message_content, is_auth_response=False) -> dict:
    """Send a query to the agent using ADK Runner following official pattern."""
    try:
        # Initialize runner if needed
        await initialize_runner()

        # Check if this is an auth response (resuming a paused invocation)
        if is_auth_response and st.session_state.paused_invocation_id:
            print(f"Resuming invocation {st.session_state.paused_invocation_id} with auth response", file=sys.stderr)

            # Create the auth content as per ADK format
            auth_content = types.Content(**message_content)

            # Resume the invocation with the auth response (no await - returns AsyncGenerator)
            events_async = st.session_state.runner.run_async(
                user_id=st.session_state.user_id,
                session_id=st.session_state.session_id,
                invocation_id=st.session_state.paused_invocation_id,
                new_message=auth_content
            )

            # Clear the paused invocation ID after use
            st.session_state.paused_invocation_id = None

        else:
            # Regular message - start new invocation
            print(f"Starting new invocation with message", file=sys.stderr)

            # Create the message content
            if isinstance(message_content, str):
                user_content = types.Content(
                    role="user",
                    parts=[types.Part(text=message_content)]
                )
            else:
                user_content = types.Content(**message_content) if isinstance(message_content, dict) else message_content

            # Run the agent (no await - returns AsyncGenerator)
            events_async = st.session_state.runner.run_async(
                user_id=st.session_state.user_id,
                session_id=st.session_state.session_id,
                new_message=user_content
            )

        # Process events following the ADK documentation pattern
        response_parts = []
        event_count = 0
        auth_request_function_call_id = None
        auth_config = None

        try:
            async for event in events_async:
                event_count += 1
                print(f"\n=== EVENT {event_count} ===", file=sys.stderr)
                print(f"Event: {event}", file=sys.stderr)

                # Check for auth request using the helper function
                if auth_request_function_call := get_auth_request_function_call(event):
                    print("--> Authentication required by agent.", file=sys.stderr)

                    # Store the ID needed to respond later
                    auth_request_function_call_id = auth_request_function_call.id
                    if not auth_request_function_call_id:
                        raise ValueError(f'Cannot get function call id from function call: {auth_request_function_call}')

                    # Get the AuthConfig containing the auth_uri etc.
                    auth_config = get_auth_config(auth_request_function_call)

                    # Store invocation ID for resumption
                    if hasattr(event, 'invocation_id'):
                        st.session_state.paused_invocation_id = event.invocation_id
                        print(f"Stored invocation_id: {event.invocation_id}", file=sys.stderr)

                    # Extract OAuth URL and state from auth_config
                    if auth_config:
                        print(f"Auth config type: {type(auth_config)}", file=sys.stderr)
                        print(f"Auth config: {auth_config}", file=sys.stderr)

                        auth_url = None
                        state = None

                        # Handle dict format (which is what we're seeing in the logs)
                        if isinstance(auth_config, dict):
                            exc = auth_config.get('exchangedAuthCredential') or auth_config.get('exchanged_auth_credential', {})
                            if exc and isinstance(exc, dict):
                                oauth2 = exc.get('oauth2', {})
                                if oauth2 and isinstance(oauth2, dict):
                                    auth_url = oauth2.get('authUri') or oauth2.get('auth_uri')
                                    state = oauth2.get('state')
                        # Handle object format
                        elif hasattr(auth_config, 'exchanged_auth_credential') or hasattr(auth_config, 'exchangedAuthCredential'):
                            exc = getattr(auth_config, 'exchangedAuthCredential', None) or getattr(auth_config, 'exchanged_auth_credential', None)
                            if exc:
                                if hasattr(exc, 'oauth2'):
                                    oauth2 = exc.oauth2
                                    auth_url = getattr(oauth2, 'authUri', None) or getattr(oauth2, 'auth_uri', None)
                                    state = getattr(oauth2, 'state', None)

                        print(f"Extracted auth_url: {auth_url}, state: {state}", file=sys.stderr)

                        if auth_url and state:
                            # Save auth config for OAuth callback
                            # Convert to dict if it's an object, handling non-serializable types
                            import json

                            def make_serializable(obj):
                                """Convert non-serializable objects to serializable formats."""
                                if isinstance(obj, dict):
                                    return {k: make_serializable(v) for k, v in obj.items()}
                                elif isinstance(obj, (list, tuple)):
                                    return [make_serializable(item) for item in obj]
                                elif hasattr(obj, 'model_dump'):
                                    return make_serializable(obj.model_dump())
                                elif hasattr(obj, '__dict__'):
                                    return make_serializable(vars(obj))
                                elif hasattr(obj, 'value'):  # For enums
                                    return obj.value
                                elif hasattr(obj, '__str__') and not isinstance(obj, (str, int, float, bool, type(None))):
                                    return str(obj)
                                else:
                                    return obj

                            auth_config_serializable = make_serializable(auth_config)

                            storage_data = {
                                'function_call_id': auth_request_function_call_id,
                                'auth_config': auth_config_serializable,
                                'session_id': st.session_state.session_id,
                                'user_id': st.session_state.user_id,
                                'invocation_id': st.session_state.paused_invocation_id
                            }
                            save_auth_config(state, storage_data)

                            return {
                                "type": "auth_required",
                                "auth_url": auth_url,
                                "content": "Authentication required. Please click the link to authorize."
                            }

                    break  # Stop processing events for now, need user interaction

                # Extract text content from regular events
                if hasattr(event, 'content'):
                    content = event.content
                    if hasattr(content, 'parts'):
                        for part in content.parts:
                            if hasattr(part, 'text'):
                                response_parts.append(part.text)
        finally:
            # Ensure the async generator is properly closed
            if hasattr(events_async, 'aclose'):
                try:
                    await events_async.aclose()
                except Exception as close_error:
                    print(f"Warning: Error closing async generator: {close_error}", file=sys.stderr)

        print(f"\n=== TOTAL EVENTS: {event_count} ===", file=sys.stderr)

        # Return combined response
        if response_parts:
            return {
                "type": "text",
                "content": "\n\n".join(response_parts)
            }
        elif auth_request_function_call_id:
            # Auth was requested but we couldn't get the URL
            return {
                "type": "error",
                "content": "Authentication was requested but couldn't extract the authorization URL."
            }
        else:
            return {
                "type": "text",
                "content": "I received your message but couldn't generate a response."
            }

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
st.caption("Using ADK Runner with OAuth Support")

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
        st.session_state.paused_invocation_id = stored_data.get('invocation_id')

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

        print(f"OAuth callback processed. Invocation ID: {st.session_state.paused_invocation_id}", file=sys.stderr)

        # Clear query params and rerun
        st.query_params.clear()
        st.rerun()

# Send auth response if OAuth was completed
if st.session_state.get('oauth_ready'):
    st.info("✅ OAuth completed! Resuming agent invocation...")

    if st.session_state.pending_auth_config:
        # Build the FunctionResponse
        auth_message = {
            "role": "user",
            "parts": [{
                "function_response": {
                    "name": "adk_request_credential",
                    "id": st.session_state.pending_auth_config['function_call_id'],
                    "response": st.session_state.pending_auth_config['auth_config']
                }
            }]
        }

        # Send auth response to resume invocation
        with st.chat_message("assistant"):
            with st.spinner("Resuming with authentication..."):
                # Use asyncio.run which properly handles event loop creation and cleanup
                response = asyncio.run(query_agent(auth_message, is_auth_response=True))

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
            # Use asyncio.run which properly handles event loop creation and cleanup
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