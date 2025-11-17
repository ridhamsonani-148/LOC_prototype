#!/bin/bash

# Quick API Test Script
# Tests the Chat API endpoint

set -e

echo "========================================="
echo "Testing Chat API"
echo "========================================="
echo ""

# Get API URL from stack
STACK_NAME="ChroniclingAmericaStack"

API_URL=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`ChatEndpoint`].OutputValue' \
  --output text 2>/dev/null || echo "")

if [ -z "$API_URL" ]; then
  echo "❌ API URL not found. Please provide it as argument:"
  echo "Usage: $0 <API_URL>"
  echo ""
  echo "Example:"
  echo "$0 https://abc123.execute-api.us-west-2.amazonaws.com/prod/chat"
  exit 1
fi

echo "API URL: $API_URL"
echo ""

# Test 1: Health Check
echo "Test 1: Health Check"
echo "--------------------"
HEALTH_URL="${API_URL%/chat}"
echo "GET $HEALTH_URL/health"
echo ""

curl -s -X GET "$HEALTH_URL/health" | jq '.' 2>/dev/null || curl -s -X GET "$HEALTH_URL/health"
echo ""
echo ""

# Test 2: Simple Question
echo "Test 2: Simple Question"
echo "----------------------"
QUESTION='{"question": "What newspapers are in the database?"}'
echo "POST $API_URL"
echo "Body: $QUESTION"
echo ""

curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d "$QUESTION" | jq '.' 2>/dev/null || curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d "$QUESTION"
echo ""
echo ""

# Test 3: Entity Question
echo "Test 3: Entity Question"
echo "----------------------"
QUESTION='{"question": "Who are the people mentioned in the newspapers?"}'
echo "POST $API_URL"
echo "Body: $QUESTION"
echo ""

curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d "$QUESTION" | jq '.' 2>/dev/null || curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d "$QUESTION"
echo ""
echo ""

# Test 4: Location Question
echo "Test 4: Location Question"
echo "------------------------"
QUESTION='{"question": "What locations are mentioned?"}'
echo "POST $API_URL"
echo "Body: $QUESTION"
echo ""

curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d "$QUESTION" | jq '.' 2>/dev/null || curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d "$QUESTION"
echo ""
echo ""

echo "========================================="
echo "✅ API Tests Complete"
echo "========================================="
echo ""
echo "Open the web UI to chat interactively:"
echo "file://$(pwd)/frontend/index.html"
echo ""
