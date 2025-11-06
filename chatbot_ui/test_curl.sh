#!/bin/bash

# Read access token from .env
ACCESS_TOKEN=$(grep ACCESS_TOKEN .env | cut -d'=' -f2)

# Test streamQuery endpoint
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
     -H "Content-Type: application/json" \
     https://europe-west3-aiplatform.googleapis.com/v1/projects/jstrom-ae-staging-bugbash-01/locations/europe-west3/reasoningEngines/4658305311445090304:streamQuery?alt=sse \
     -d '{
"class_method": "async_stream_query",
"input": {
    "user_id": "u_123",
    "session_id": "4857885913439920384",
    "message": "Hey, what is 2+2?"
}
}'
