# Space Explorer Chatbot UI

A Streamlit chatbot interface for the Space Explorer Agent deployed on Google Cloud Agent Engine with MCP + OAuth integration.

## Features

- 🚀 Real-time chat with deployed Agent Engine agent
- 🔐 OAuth flow handling for MCP tool authentication
- 🎨 Clean, modern UI with chat history
- ⚡ Async agent queries
- 🛠️ MCP tool integration (space missions, launches, astronauts)

## Setup

### Prerequisites

1. Google Cloud authentication configured
2. Agent deployed to Agent Engine (see parent directory notebook)
3. Python 3.10+

### Installation

```bash
cd chatbot_ui
pip install -r requirements.txt
```

### Configuration

The app is pre-configured to connect to:
- **Project**: `jstrom-ae-staging-bugbash-01`
- **Region**: `europe-west3`
- **Agent Resource**: `projects/766576453207/locations/europe-west3/reasoningEngines/4658305311445090304`

To change the agent, update these values in `app.py`:
```python
PROJECT_ID = "your-project-id"
REGION = "your-region"
AGENT_ENGINE_RESOURCE_NAME = "your-agent-resource-name"
```

## Running the App

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`

## Usage

1. **Start chatting**: Type questions about space exploration in the input box
2. **OAuth flow**: If MCP tools require authentication, follow the authorization link
3. **Continue**: After authentication, continue asking questions

### Example Queries

- "What rocket launches are happening soon?"
- "Tell me about astronauts currently in space"
- "Show me information about Mars missions"
- "What's the status of the ISS?"

## Architecture

```
User → Streamlit UI → Agent Engine (deployed agent)
                            ↓
                       MCP Toolset → Apollo MCP Server
                            ↓              ↓
                       OAuth Flow    Space Devs API
```

## OAuth Flow

When the agent needs to call MCP tools:

1. Agent detects authentication required
2. UI displays OAuth authorization prompt
3. User clicks authorization URL
4. User authenticates with Auth0
5. Token stored in agent session
6. MCP tools become available

## Troubleshooting

**Connection Issues:**
- Verify `gcloud auth application-default login` is configured
- Check project ID and region match your deployment
- Ensure Agent Engine agent is running

**OAuth Issues:**
- Verify Auth0 credentials in agent environment variables
- Check redirect URIs in Auth0 console
- Ensure MCP server is accessible at `http://34.61.171.198:8000/mcp`

**Agent Not Responding:**
- Check Agent Engine logs in Cloud Console
- Verify agent was deployed with MCP toolset
- Test agent with cell 26 in the notebook first

## Development

### Project Structure

```
chatbot_ui/
├── app.py              # Main Streamlit application
├── requirements.txt    # Python dependencies
└── README.md          # This file
```

### Extending

To add features:

1. **Session persistence**: Store session_id in Streamlit session state
2. **Conversation history**: Save to database or file
3. **Multi-user support**: Add authentication and user management
4. **Advanced OAuth**: Implement token refresh and storage
5. **Tool visualization**: Display which MCP tools were called

## Notes

- This is a staging/development UI for the Agent Identity bugbash
- The agent uses OAuth for MCP tool authentication
- Full query API integration pending (currently shows mock responses)
- Production deployment would require additional security hardening
