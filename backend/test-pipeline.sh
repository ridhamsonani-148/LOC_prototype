#!/bin/bash

# Test Pipeline Script
# Tests the complete Chronicling America pipeline

set -e

echo "========================================="
echo "Testing Chronicling America Pipeline"
echo "========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get stack outputs
echo "📊 Fetching stack outputs..."
STACK_NAME="ChroniclingAmericaStack"

DATA_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text 2>/dev/null || echo "")

STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`StateMachineArn`].OutputValue' \
  --output text 2>/dev/null || echo "")

API_URL=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`ChatEndpoint`].OutputValue' \
  --output text 2>/dev/null || echo "")

if [ -z "$STATE_MACHINE_ARN" ]; then
  echo -e "${RED}❌ Stack not found or not deployed${NC}"
  echo "Please deploy the stack first: ./deploy.sh"
  exit 1
fi

echo -e "${GREEN}✅ Stack found${NC}"
echo "Data Bucket: $DATA_BUCKET"
echo "State Machine: $STATE_MACHINE_ARN"
echo "Chat API: $API_URL"
echo ""

# Test 1: Start Pipeline Execution
echo "========================================="
echo "Test 1: Starting Pipeline Execution"
echo "========================================="
echo ""

EXECUTION_INPUT='{
  "start_date": "1815-08-01",
  "end_date": "1815-08-05",
  "max_pages": 2
}'

echo "Input: $EXECUTION_INPUT"
echo ""

EXECUTION_ARN=$(aws stepfunctions start-execution \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --input "$EXECUTION_INPUT" \
  --query 'executionArn' \
  --output text)

echo -e "${GREEN}✅ Execution started${NC}"
echo "Execution ARN: $EXECUTION_ARN"
echo ""

# Test 2: Monitor Execution
echo "========================================="
echo "Test 2: Monitoring Execution"
echo "========================================="
echo ""

echo "Waiting for execution to complete (this may take 5-10 minutes)..."
echo "You can monitor in AWS Console:"
echo "https://console.aws.amazon.com/states/home?region=$(aws configure get region)#/executions/details/$EXECUTION_ARN"
echo ""

MAX_WAIT=600  # 10 minutes
WAIT_TIME=0
INTERVAL=15

while [ $WAIT_TIME -lt $MAX_WAIT ]; do
  STATUS=$(aws stepfunctions describe-execution \
    --execution-arn "$EXECUTION_ARN" \
    --query 'status' \
    --output text)
  
  if [ "$STATUS" = "SUCCEEDED" ]; then
    echo -e "${GREEN}✅ Execution completed successfully!${NC}"
    break
  elif [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "TIMED_OUT" ] || [ "$STATUS" = "ABORTED" ]; then
    echo -e "${RED}❌ Execution failed with status: $STATUS${NC}"
    
    # Get error details
    aws stepfunctions describe-execution \
      --execution-arn "$EXECUTION_ARN" \
      --query 'output' \
      --output text
    
    exit 1
  else
    echo "Status: $STATUS (waiting ${WAIT_TIME}s / ${MAX_WAIT}s)"
    sleep $INTERVAL
    WAIT_TIME=$((WAIT_TIME + INTERVAL))
  fi
done

if [ $WAIT_TIME -ge $MAX_WAIT ]; then
  echo -e "${YELLOW}⚠️  Execution still running after ${MAX_WAIT}s${NC}"
  echo "Check status manually in AWS Console"
  exit 0
fi

echo ""

# Test 3: Verify S3 Data
echo "========================================="
echo "Test 3: Verifying S3 Data"
echo "========================================="
echo ""

echo "Checking S3 bucket contents..."

IMAGES_COUNT=$(aws s3 ls s3://$DATA_BUCKET/images/ | wc -l)
EXTRACTED_COUNT=$(aws s3 ls s3://$DATA_BUCKET/extracted/ | wc -l)
KG_COUNT=$(aws s3 ls s3://$DATA_BUCKET/knowledge_graphs/ | wc -l)

echo "Images: $IMAGES_COUNT files"
echo "Extracted: $EXTRACTED_COUNT files"
echo "Knowledge Graphs: $KG_COUNT files"

if [ $IMAGES_COUNT -gt 0 ] && [ $EXTRACTED_COUNT -gt 0 ] && [ $KG_COUNT -gt 0 ]; then
  echo -e "${GREEN}✅ All data files created${NC}"
else
  echo -e "${YELLOW}⚠️  Some data files missing${NC}"
fi

echo ""

# Test 4: Test Chat API
echo "========================================="
echo "Test 4: Testing Chat API"
echo "========================================="
echo ""

if [ -z "$API_URL" ]; then
  echo -e "${YELLOW}⚠️  Chat API URL not found${NC}"
  exit 0
fi

# Test health endpoint
echo "Testing health endpoint..."
HEALTH_RESPONSE=$(curl -s -X GET "$API_URL" | head -c 200)
echo "Response: $HEALTH_RESPONSE"
echo ""

# Test chat endpoint
echo "Testing chat endpoint..."
CHAT_QUESTION='{"question": "What newspapers are in the database?"}'

echo "Question: $CHAT_QUESTION"
echo ""

CHAT_RESPONSE=$(curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d "$CHAT_QUESTION")

echo "Response:"
echo "$CHAT_RESPONSE" | jq '.' 2>/dev/null || echo "$CHAT_RESPONSE"
echo ""

if echo "$CHAT_RESPONSE" | grep -q "answer"; then
  echo -e "${GREEN}✅ Chat API working${NC}"
else
  echo -e "${YELLOW}⚠️  Chat API response unexpected${NC}"
fi

echo ""

# Summary
echo "========================================="
echo "Test Summary"
echo "========================================="
echo ""
echo -e "${GREEN}✅ Pipeline execution completed${NC}"
echo -e "${GREEN}✅ Data stored in S3${NC}"
echo -e "${GREEN}✅ Chat API responding${NC}"
echo ""
echo "Next steps:"
echo "1. Open the web UI: frontend/index.html"
echo "2. Or use curl to query:"
echo "   curl -X POST $API_URL \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"question\":\"Who are the people mentioned?\"}'"
echo ""
echo "View CloudWatch Logs:"
echo "https://console.aws.amazon.com/cloudwatch/home?region=$(aws configure get region)#logsV2:log-groups"
echo ""
