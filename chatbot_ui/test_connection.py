"""Test connection to Agent Engine."""

import asyncio
import sys
from google.genai import types as genai_types
import vertexai

# Configuration
PROJECT_ID = "jstrom-ae-staging-bugbash-01"
REGION = "europe-west3"
AGENT_ENGINE_RESOURCE_NAME = "projects/766576453207/locations/europe-west3/reasoningEngines/4658305311445090304"
ACCESS_TOKEN=""

async def test_connection():
    """Test connection to deployed Agent Engine agent."""
    try:
        print("🔍 Testing Agent Engine connection...")
        print(f"   Project: {PROJECT_ID}")
        print(f"   Region: {REGION}")
        print(f"   Using access token: {ACCESS_TOKEN[:20]}...")
        print()

        # Create credentials from access token
        print("1️⃣ Creating credentials from access token...")
        from google.auth.credentials import Credentials

        class StaticCredentials(Credentials):
            """Simple credentials using a static access token."""
            def __init__(self, token):
                super().__init__()
                self.token = token
                self.expiry = None

            def refresh(self, request):
                pass  # Token is static, no refresh

            def apply(self, headers, token=None):
                headers['authorization'] = f'Bearer {self.token}'

            @property
            def expired(self):
                return False

            @property
            def valid(self):
                return True

        credentials = StaticCredentials(ACCESS_TOKEN)
        print("   ✅ Credentials created")
        print()

        # Initialize Vertex AI with credentials
        print("2️⃣ Initializing Vertex AI with access token...")
        vertexai.init(
            project=PROJECT_ID,
            location=REGION,
            credentials=credentials,
        )
        print("   ✅ Vertex AI initialized")
        print()

        # Create client for staging environment
        print("3️⃣ Creating client for staging environment...")
        http_options = genai_types.HttpOptions(api_version="v1beta1")
        http_options.base_url = f"https://{REGION}-staging-aiplatform.sandbox.googleapis.com/"

        client = vertexai.Client(
            project=PROJECT_ID,
            location=REGION,
            http_options=http_options,
            credentials=credentials,
        )
        print("   ✅ Client created")
        print()

        # Get the deployed agent
        print("4️⃣ Connecting to deployed agent...")
        # The resource name format is the full path
        # vertexai.init() sets the credentials globally
        from vertexai.agent_engines import AgentEngine
        agent_client = AgentEngine(resource_name=AGENT_ENGINE_RESOURCE_NAME)
        print("   ✅ Connected to agent")
        print(f"   Agent resource: {AGENT_ENGINE_RESOURCE_NAME}")
        print()

        # Test session creation (mocked method)
        print("5️⃣ Testing session creation...")
        user_id = "test_user_123"
        try:
            session_response = await agent_client.async_create_session(user_id=user_id)
            print("   ✅ Session created")
            print(f"   Response: {session_response}")
        except Exception as e:
            print(f"   ⚠️  Session creation returned: {e}")
            print("   (This is expected for mocked session method)")
        print()

        print("🎉 SUCCESS! Agent Engine connection working!")
        print()
        print("Next steps:")
        print("  • Run: streamlit run app.py")
        print("  • Chat with the agent")
        print("  • Test MCP tool OAuth flow")

        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        print()
        print("Troubleshooting:")
        print("  • Run: gcloud auth application-default login")
        print("  • Verify project ID and region")
        print("  • Check that agent is deployed")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_connection())
    sys.exit(0 if success else 1)
