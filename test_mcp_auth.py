import requests
import json
import uuid
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- 1. CONFIGURATION: FROM ENVIRONMENT VARIABLES ---

# --- From Auth0 Application Settings ---
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
CLIENT_ID = os.getenv("AUTH0_CLIENT_ID")
CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET")

# --- From Auth0 API Settings ---
API_AUDIENCE = os.getenv("AUTH0_API_AUDIENCE", "http://34.61.171.198:8000/mcp")

# --- Your local MCP Server ---
MCP_SERVER_URL = "http://34.61.171.198:8000/mcp"

# Validate required environment variables
if not all([AUTH0_DOMAIN, CLIENT_ID, CLIENT_SECRET]):
    print("ERROR: Missing required environment variables!")
    print("Please set AUTH0_DOMAIN, AUTH0_CLIENT_ID, and AUTH0_CLIENT_SECRET in .env file")
    exit(1)

# --- 2. STEP 1: GET THE ACCESS TOKEN FROM AUTH0 ---

token_payload = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "audience": API_AUDIENCE,
    "grant_type": "client_credentials",
}
token_url = f"https://{AUTH0_DOMAIN}/oauth/token"

print(f"Requesting token from {token_url} for audience: {API_AUDIENCE}...")

try:
    token_response = requests.post(token_url, data=token_payload)
    token_data = token_response.json()

    if "access_token" not in token_data:
        print("\n--- TOKEN REQUEST FAILED ---")
        print(json.dumps(token_data, indent=2))
        exit()

    ACCESS_TOKEN = token_data["access_token"]
    print("Successfully retrieved new access token!")

except Exception as e:
    print(f"\nError getting token: {e}")
    exit()

# --- 3. STEP 2: CALL YOUR MCP SERVER WITH THE NEW TOKEN ---

mcp_headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

# Change the payload to the "initialize" method, as the server requested.
mcp_payload = {
    "jsonrpc": "2.0",
    "method": "initialize",  # <-- The method the server is expecting
    "params": {
        "protocolVersion": "2024-11-05",  # <-- camelCase, correct version
        "capabilities": {},  # <-- Required capabilities object
        "clientInfo": {
            "name": "test-mcp-client",
            "version": "1.0.0"
        }
    },
    "id": str(uuid.uuid4()),  # A unique ID for this request
}

print(f"\nAttempting to POST to {MCP_SERVER_URL} with new 'initialize' payload...")
print(f"Payload:\n{json.dumps(mcp_payload, indent=2)}")

try:
    response = requests.post(
        MCP_SERVER_URL, headers=mcp_headers, data=json.dumps(mcp_payload)
    )

    # --- 4. PRINT THE RESULTS ---
    print(f"\nStatus Code: {response.status_code}")

    print("\n--- Response Headers ---")
    print(response.headers)

    print("\n--- Response Body ---")
    try:
        print(json.dumps(response.json(), indent=2))
    except requests.exceptions.JSONDecodeError:
        print(response.text)

except Exception as e:
    print(f"\nAn unexpected error occurred: {e}")
