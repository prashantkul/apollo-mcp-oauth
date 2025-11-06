#!/usr/bin/env python3
"""Test MCP protocol with modified auth middleware.

Tests:
1. Anonymous initialize (should work)
2. Anonymous initialized notification (should work)
3. Anonymous tools/list (should work)
4. Authenticated tool call (should require auth)
"""

import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

MCP_URL = "http://127.0.0.1:8000/mcp"
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
CLIENT_ID = os.getenv("AUTH0_CLIENT_ID")
CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET")
API_AUDIENCE = os.getenv("AUTH0_API_AUDIENCE", "http://127.0.0.1:8000/mcp")


def get_auth0_token():
    """Get Auth0 access token using client credentials."""
    token_url = f"https://{AUTH0_DOMAIN}/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "audience": API_AUDIENCE,
        "grant_type": "client_credentials",
    }
    response = requests.post(token_url, data=payload, timeout=10)
    response.raise_for_status()
    return response.json()["access_token"]


def test_initialize():
    """Test initialize without auth (should work)."""
    print("\n1. Testing initialize (no auth)...")
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",  # Both required for Streamable HTTP
    }

    try:
        response = requests.post(MCP_URL, json=payload, headers=headers, timeout=10, stream=True)
        print(f"   Status: {response.status_code}")

        # Read SSE response
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = json.loads(line[6:])
                    print(f"   Response: {json.dumps(data, indent=2)}")
                    break

        return response.status_code == 200
    except Exception as e:
        print(f"   ERROR: {e}")
        return False


def test_initialized():
    """Test initialized notification without auth (should work)."""
    print("\n2. Testing initialized notification (no auth)...")
    payload = {"jsonrpc": "2.0", "method": "notifications/initialized"}

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    try:
        response = requests.post(MCP_URL, json=payload, headers=headers, timeout=10, stream=True)
        print(f"   Status: {response.status_code}")
        if response.text:
            print(f"   Response: {response.text}")
        else:
            print("   Response: (empty - expected for notification)")
        return response.status_code == 200
    except Exception as e:
        print(f"   ERROR: {e}")
        return False


def test_tools_list():
    """Test tools/list without auth (should work)."""
    print("\n3. Testing tools/list (no auth)...")
    payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    try:
        response = requests.post(MCP_URL, json=payload, headers=headers, timeout=10, stream=True)
        print(f"   Status: {response.status_code}")

        # Read SSE response
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = json.loads(line[6:])
                    print(f"   Response: {json.dumps(data, indent=2)[:500]}...")
                    if "result" in data and "tools" in data["result"]:
                        print(f"   Found {len(data['result']['tools'])} tools")
                    break

        return response.status_code == 200
    except Exception as e:
        print(f"   ERROR: {e}")
        return False


def test_tools_call_without_auth():
    """Test tools/call without auth (should fail with 401)."""
    print("\n4. Testing tools/call WITHOUT auth (should fail)...")
    payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "some-tool", "arguments": {}},
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    try:
        response = requests.post(MCP_URL, json=payload, headers=headers, timeout=10)
        print(f"   Status: {response.status_code}")
        if response.status_code == 401:
            print("   ✓ Correctly rejected (401 Unauthorized)")
            print(f"   WWW-Authenticate header: {response.headers.get('www-authenticate')}")
            return True
        else:
            print(f"   ✗ Expected 401, got {response.status_code}")
            return False
    except Exception as e:
        print(f"   ERROR: {e}")
        return False


def test_tools_call_with_auth():
    """Test tools/call with auth (should work if tool exists)."""
    print("\n5. Testing tools/call WITH auth (should work)...")

    # Get auth token
    try:
        token = get_auth0_token()
        print(f"   Got auth token: {token[:20]}...")
    except Exception as e:
        print(f"   ERROR getting token: {e}")
        return False

    payload = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "some-tool", "arguments": {}},
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}",
    }

    try:
        response = requests.post(MCP_URL, json=payload, headers=headers, timeout=10, stream=True)
        print(f"   Status: {response.status_code}")

        # Read SSE response
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = json.loads(line[6:])
                    print(f"   Response: {json.dumps(data, indent=2)[:500]}...")
                    break

        if response.status_code == 200:
            print("   ✓ Auth accepted (tool execution may fail if tool doesn't exist)")
            return True
        elif response.status_code == 401:
            print("   ✗ Auth rejected (token validation failed)")
            return False
        else:
            print(f"   Note: Status {response.status_code} (auth worked, other error)")
            return True
    except Exception as e:
        print(f"   ERROR: {e}")
        return False


def main():
    print("=" * 60)
    print("MCP Protocol Authentication Test")
    print("=" * 60)

    results = {
        "initialize (no auth)": test_initialize(),
        "initialized (no auth)": test_initialized(),
        "tools/list (no auth)": test_tools_list(),
        "tools/call without auth": test_tools_call_without_auth(),
        "tools/call with auth": test_tools_call_with_auth(),
    }

    print("\n" + "=" * 60)
    print("Test Results:")
    print("=" * 60)
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} - {test_name}")

    print("=" * 60)
    all_passed = all(results.values())
    if all_passed:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed")

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
