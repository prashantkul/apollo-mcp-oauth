"""Test async_stream_query directly."""

import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

import vertexai
from google.auth.credentials import Credentials
from google.genai import types as genai_types

PROJECT_ID = os.getenv("PROJECT_ID")
REGION = os.getenv("REGION")
AGENT_ENGINE_RESOURCE_NAME = os.getenv("AGENT_ENGINE_RESOURCE_NAME")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

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

async def test_query():
    """Test querying the agent."""
    print("Initializing...")
    credentials = StaticCredentials(ACCESS_TOKEN)

    vertexai.init(
        project=PROJECT_ID,
        location=REGION,
        credentials=credentials,
    )

    from vertexai.agent_engines import AgentEngine
    agent_client = AgentEngine(resource_name=AGENT_ENGINE_RESOURCE_NAME)

    print("Available methods:")
    for attr in dir(agent_client):
        if not attr.startswith('_') and callable(getattr(agent_client, attr)):
            print(f"  - {attr}")
    print()

    user_id = "test_user_456"
    print(f"\nQuerying agent with user_id: {user_id}, message: 'hello'")
    print("=" * 50)

    # Try direct query without session creation
    print("\n--- Testing async_stream_query (no session) ---")
    event_count = 0
    try:
        async for event in agent_client.async_stream_query(
            user_id=user_id,
            message="hello",
        ):
            event_count += 1
            print(f"\n=== EVENT {event_count} ===")
            print(f"Type: {type(event)}")
            print(f"Event: {event}")
            print(f"Attributes: {[a for a in dir(event) if not a.startswith('_')]}")
            print()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n=== TOTAL EVENTS: {event_count} ===")

if __name__ == "__main__":
    asyncio.run(test_query())
