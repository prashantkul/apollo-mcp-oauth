"""Streamlit Chatbot UI for Space Explorer Agent with OAuth Handling - Simplified."""

import streamlit as st
import asyncio
from typing import Optional
import os
import sys
import json
import tempfile
from pathlib import Path

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
ACCESS_TOKEN = os.getenv(
    "ACCESS_TOKEN"
)  # Optional: use access token instead of gcloud auth

# Validate required environment variables
if not all([PROJECT_ID, REGION, AGENT_ENGINE_RESOURCE_NAME]):
    raise ValueError(
        "Missing required environment variables. "
        "Please set PROJECT_ID, REGION, and AGENT_ENGINE_RESOURCE_NAME in .env file"
    )

# Page config
st.set_page_config(page_title="Space Explorer Agent", page_icon="🚀", layout="wide")

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
    st.session_state.pending_auth_config = None
if "oauth_ready" not in st.session_state:
    st.session_state.oauth_ready = False
if "original_query" not in st.session_state:
    st.session_state.original_query = None


def get_temp_auth_file(state: str) -> Path:
    """Get path to temporary auth config file for a given state."""
    temp_dir = Path(tempfile.gettempdir()) / "streamlit_oauth"
    temp_dir.mkdir(exist_ok=True)
    return temp_dir / f"auth_{state}.json"


def save_auth_config(state: str, config: dict) -> None:
    """Save auth config to temporary file."""
    file_path = get_temp_auth_file(state)
    with open(file_path, "w") as f:
        json.dump(config, f)
    print(f"Saved auth config to {file_path}", file=sys.stderr)


def load_auth_config(state: str) -> Optional[dict]:
    """Load auth config from temporary file."""
    file_path = get_temp_auth_file(state)
    if file_path.exists():
        try:
            with open(file_path, "r") as f:
                config = json.load(f)
            print(f"Loaded auth config from {file_path}", file=sys.stderr)
            # Clean up the file after loading
            file_path.unlink()
            return config
        except Exception as e:
            print(f"Failed to load auth config: {e}", file=sys.stderr)
    return None


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
                        headers["authorization"] = f"Bearer {self.token}"

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

            # Get the deployed agent using agent_engines.get()
            from vertexai import agent_engines

            st.session_state.agent_client = agent_engines.get(
                AGENT_ENGINE_RESOURCE_NAME
            )

            return True
        except Exception as e:
            st.error(f"Failed to connect to Agent Engine: {e}")
            import traceback

            st.error(traceback.format_exc())
            return False
    return True


async def query_agent(user_message: str) -> dict:
    """Query the deployed agent using async_stream_query with proper message format."""
    import sys
    import uuid
    from google.genai import types

    try:
        # Initialize message_content to the default user text.
        message_content = user_message

        # Create or get session for this user
        if st.session_state.agent_session_id is None:
            print(
                f"Creating new session for user_id: {st.session_state.user_id}",
                file=sys.stderr,
            )
            session_response = await st.session_state.agent_client.async_create_session(
                user_id=st.session_state.user_id
            )
            st.session_state.agent_session_id = session_response["id"]
            print(
                f"Created session: {st.session_state.agent_session_id}", file=sys.stderr
            )

        # Initialize variables for the query execution block
        invocation_id = None
        function_call_id = None
        auth_config = None

        # Construct the message content
        if st.session_state.get("oauth_ready") and st.session_state.pending_auth_config:
            # Send auth response as a FunctionResponse following ADK format
            function_call_id = st.session_state.pending_auth_config["function_call_id"]
            auth_config = st.session_state.pending_auth_config["auth_config"]
            invocation_id = st.session_state.pending_auth_config.get(
                "invocation_id"
            )  # Use for async_stream_query

            # --- CORRECTION: MINIMAL PAYLOAD CONSTRUCTION ---
            auth_response_uri_value = auth_config["exchanged_auth_credential"][
                "oauth2"
            ]["auth_response_uri"]

            message_content = {
                "role": "user",
                "parts": [
                    {
                        "function_response": {
                            "name": "adk_request_credential",
                            "id": function_call_id,
                            "response": {
                                # 1. RESTORED FIELD (REQUIRED BY VALIDATOR)
                                "auth_scheme": auth_scheme,
                                # Use the 'credential_key' to identify the credential being updated
                                "credential_key": auth_config["credential_key"],
                                # Send only the key that was updated
                                "exchanged_auth_credential": {
                                    # 2. RESTORED FIELD (REQUIRED BY VALIDATOR)
                                    "auth_type": auth_type,
                                    "oauth2": {
                                        "auth_response_uri": auth_response_uri_value
                                    },
                                },
                            },
                        }
                    }
                ],
            }
            # --- END CORRECTION ---

            print(
                f"Sending auth response with function_call_id: {function_call_id}",
                file=sys.stderr,
            )
            print(f"Invocation ID (for Resume): {invocation_id}", file=sys.stderr)
            print(
                f"Auth config keys: {auth_config.keys() if isinstance(auth_config, dict) else 'not a dict'}",
                file=sys.stderr,
            )
            import json as debug_json

            print(
                f"Auth response content: {debug_json.dumps(message_content, indent=2, default=str)}",
                file=sys.stderr,
            )
            # Clear the OAuth state AFTER we use it
            st.session_state.oauth_ready = False
            st.session_state.pending_auth_config = None

        # Query with session using async_stream_query
        response_parts = []
        oauth_detected = False
        auth_url = None
        event_count = 0
        events_async = None  # Initialize events_async

        print(
            f"Running agent with user_id: {st.session_state.user_id}, session_id: {st.session_state.agent_session_id}",
            file=sys.stderr,
        )
        print(
            f"Message type: {type(message_content)}, is_dict: {isinstance(message_content, dict)}",
            file=sys.stderr,
        )

        # --- UNIFIED QUERY EXECUTION BLOCK ---
        # Check if we are sending the OAuth response (message_content will be a dict with "parts")
        if isinstance(message_content, dict) and "parts" in message_content:
            print(f"Sending OAuth response back to agent", file=sys.stderr)

            # Use the invocation_id extracted in the block above
            invocation_id_for_resume = invocation_id  # Already extracted in line 118

            if invocation_id_for_resume:
                print(
                    f"Original invocation_id: {invocation_id_for_resume}",
                    file=sys.stderr,
                )

            # Send the auth response as the message directly
            events_async = st.session_state.agent_client.async_stream_query(
                user_id=st.session_state.user_id,
                session_id=st.session_state.agent_session_id,
                message=message_content,  # Send the FunctionResponse dict (minimal payload)
            )
        else:
            # This is a regular user message (message_content is a string)
            events_async = st.session_state.agent_client.async_stream_query(
                user_id=st.session_state.user_id,
                session_id=st.session_state.agent_session_id,
                message=message_content,  # The string message
            )
        # --- END UNIFIED QUERY EXECUTION BLOCK ---

        async for event in events_async:
            event_count += 1
            # Debug: Log event details to stderr
            print(f"\n=== EVENT {event_count} ===", file=sys.stderr)
            print(f"Type: {type(event)}", file=sys.stderr)
            print(f"Event: {event}", file=sys.stderr)

            # Check for OAuth requirement and extract auth URL
            if isinstance(event, dict) and "actions" in event:
                actions = event["actions"]
                if isinstance(actions, dict) and "requested_auth_configs" in actions:
                    auth_configs = actions["requested_auth_configs"]
                    if isinstance(auth_configs, dict) and len(auth_configs) > 0:
                        # Get first auth config
                        first_key = next(iter(auth_configs))
                        auth_config = auth_configs[first_key]

                        # Extract auth_uri and state
                        if (
                            isinstance(auth_config, dict)
                            and "exchanged_auth_credential" in auth_config
                        ):
                            exchanged = auth_config["exchanged_auth_credential"]
                            if isinstance(exchanged, dict) and "oauth2" in exchanged:
                                oauth2 = exchanged["oauth2"]
                                if isinstance(oauth2, dict):
                                    if "auth_uri" in oauth2:
                                        auth_url = oauth2["auth_uri"]
                                        oauth_detected = True

                                    # Get state for storage
                                    state = oauth2.get("state")
                                    if state:
                                        # Store auth config and session info to file
                                        # IMPORTANT: Include invocation_id for Resume feature
                                        storage_data = {
                                            "function_call_id": first_key,
                                            "auth_config": auth_config,
                                            "agent_session_id": st.session_state.agent_session_id,
                                            "user_id": st.session_state.user_id,
                                            "invocation_id": event.get(
                                                "invocation_id"
                                            ),  # Store invocation_id from event
                                        }
                                        save_auth_config(state, storage_data)
                                        print(
                                            f"Stored auth config with state: {state}, invocation_id: {event.get('invocation_id')}",
                                            file=sys.stderr,
                                        )

            # Store the original query if OAuth is detected
            if oauth_detected and not st.session_state.original_query:
                st.session_state.original_query = user_message

            # Extract content from event
            extracted_text = None

            # Try dictionary access first
            if isinstance(event, dict):
                if "content" in event and isinstance(event["content"], dict):
                    if "parts" in event["content"]:
                        parts = event["content"]["parts"]
                        if isinstance(parts, list):
                            for part in parts:
                                if isinstance(part, dict) and "text" in part:
                                    extracted_text = part["text"]
                                    break
                elif "text" in event:
                    extracted_text = event["text"]
            # Try attribute access
            elif hasattr(event, "content"):
                content = event.content
                if hasattr(content, "parts"):
                    for part in content.parts:
                        if hasattr(part, "text"):
                            extracted_text = part.text
                            break
                elif isinstance(content, str):
                    extracted_text = content
            elif hasattr(event, "text"):
                extracted_text = event.text

            if extracted_text:
                print(f"Extracted text: {extracted_text}", file=sys.stderr)
                response_parts.append(extracted_text)

        print(f"\n=== TOTAL EVENTS: {event_count} ===", file=sys.stderr)

        # Combine response
        full_response = "\n".join(response_parts)

        if oauth_detected:
            return {
                "type": "oauth",
                "content": "Authentication required to access MCP tools.",
                "auth_url": auth_url,
                "requires_auth": True,
            }

        return {
            "type": "text",
            "content": full_response if full_response else "No response from agent.",
            "requires_auth": False,
        }

    except Exception as e:
        error_msg = str(e)

        # Check if it's an OAuth-related error
        if "auth" in error_msg.lower() or "oauth" in error_msg.lower():
            return {
                "type": "oauth",
                "content": f"Authentication required: {error_msg}",
                "auth_url": None,
                "requires_auth": True,
            }
        else:
            import traceback

            return {
                "type": "error",
                "content": f"Error: {error_msg}\n\nTraceback:\n{traceback.format_exc()}",
                "requires_auth": False,
            }


def display_oauth_message(auth_url: Optional[str] = None):
    """Display OAuth authentication instructions."""
    st.warning("🔐 **OAuth Authentication Required**")

    if auth_url:
        st.markdown(
            """
        The Space Explorer Agent needs authentication to access MCP tools.

        **To authenticate:**
        1. Click the authorization button below
        2. Sign in with your Auth0 credentials
        3. You'll be redirected back here automatically
        4. Send any message to retry your request
        """
        )

        # Use Streamlit's native link button
        st.link_button("🔗 Authorize Access", auth_url, use_container_width=False)

        st.info(
            "💡 Once authenticated, the agent can access space mission data, rocket launches, and astronaut information."
        )
    else:
        st.error(
            "Authentication is required but no authorization URL was provided by the agent. Please check the agent logs."
        )


def handle_oauth_callback():
    """Handle OAuth callback from Auth0."""
    query_params = st.query_params

    if "code" in query_params and "state" in query_params:
        code = query_params["code"]
        state = query_params["state"]

        print(
            f"OAuth callback received - code: {code[:10]}..., state: {state}",
            file=sys.stderr,
        )

        # Load the saved auth config using state as key
        stored_data = load_auth_config(state)

        if stored_data:
            # Restore session information
            st.session_state.agent_session_id = stored_data["agent_session_id"]
            st.session_state.user_id = stored_data["user_id"]

            # Update auth config with callback URL
            auth_config = stored_data["auth_config"]
            callback_url = f"http://127.0.0.1:8501/?code={code}&state={state}"

            # CRITICAL: Update the stored auth_config with the response URI
            if (
                "exchanged_auth_credential" in auth_config
                and "oauth2" in auth_config["exchanged_auth_credential"]
            ):
                auth_config["exchanged_auth_credential"]["oauth2"][
                    "auth_response_uri"
                ] = callback_url

            # Store the updated auth config and metadata
            st.session_state.pending_auth_config = {
                "function_call_id": stored_data["function_call_id"],
                "auth_config": auth_config,
                "invocation_id": stored_data.get("invocation_id"),
            }
            st.session_state.oauth_ready = True

            print(f"OAuth callback processed successfully", file=sys.stderr)
            print(f"Code: {code[:10]}..., State: {state}", file=sys.stderr)
            print(f"Invocation ID: {stored_data.get('invocation_id')}", file=sys.stderr)

            # Clear query params
            st.query_params.clear()
            st.rerun()
        else:
            st.error("Session expired or auth config not found. Please start over.")
            if st.button("Clear and Start Over"):
                st.query_params.clear()
                st.rerun()

        return True

    return False


def main():
    """Main Streamlit app."""

    # Check if this is an OAuth callback
    if handle_oauth_callback():
        return

    # Header
    st.title("🚀 Space Explorer Agent")
    st.markdown("Ask me about space missions, rocket launches, or astronauts!")

    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuration")
        st.text_input(
            "User ID",
            value=st.session_state.user_id,
            key="user_id_input",
            disabled=True,
        )

        st.markdown("---")
        st.markdown("### 📊 Status")

        if initialize_agent_client():
            st.success("✅ Connected to Agent Engine")
            st.code(f"Region: {REGION}", language="text")
        else:
            st.error("❌ Not connected")

        st.markdown("---")
        st.markdown("### 🛠️ MCP Tools")
        st.markdown(
            """
        - Space launches
        - Astronaut data
        - Celestial bodies
        - Mission information
        """
        )

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

    # Show message if OAuth was completed and automatically send auth response
    if st.session_state.get("oauth_ready"):
        st.info("✅ OAuth completed! Sending authentication to agent...")

        if st.session_state.get("pending_auth_config"):

            # Send the auth response (query_agent logic will detect oauth_ready and send the minimal payload)
            with st.chat_message("assistant"):
                with st.spinner("Processing authentication..."):
                    # Pass a placeholder string; query_agent will ignore it and build the auth response
                    response = asyncio.run(query_agent("Continue conversation."))

                    if response["type"] == "text":
                        st.markdown(response["content"])
                    elif response["type"] == "error":
                        st.error(response["content"])
                    elif response["type"] == "oauth":
                        # Should not happen on callback response, but handles case if agent requests auth again
                        display_oauth_message(response.get("auth_url"))

                    # Add to chat history
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "type": response["type"],
                            "content": response["content"],
                        }
                    )
        else:
            st.error("Auth configuration not found. Please try again.")

    # Chat input
    if prompt := st.chat_input("Ask about space exploration..."):
        # Add user message
        st.session_state.messages.append(
            {"role": "user", "type": "text", "content": prompt}
        )

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
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "type": response["type"],
                        "content": response["content"],
                        "auth_url": response.get("auth_url"),
                    }
                )


if __name__ == "__main__":
    main()
