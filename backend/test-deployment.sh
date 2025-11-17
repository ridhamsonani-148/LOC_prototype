#!/usr/bin/env bash
set -euo pipefail

echo "========================================="
echo "Testing Chronicling America Deployment"
echo "========================================="
echo ""

# Get stack name
STACK_NAME=${1:-ChroniclingAmericaStack}

echo "Checking stack: $STACK_NAME"
echo ""

# Check if stack exists
if ! aws cloudformation describe-stacks --stack-name $STACK_NAME &> /dev/null; then
    echo "❌ Stack not found: $STACK_NAME"
    echo "Please deploy the stack first: ./deploy.sh"
    exit 1
fi

echo "✅ Stack exists"
echo ""

# Get outputs
echo "Fetching stack outputs..."
DATA_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`StateMachineArn`].OutputValue' \
  --output text)

NEPTUNE_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`NeptuneEndpoint`].OutputValue' \
  --output text)

API_URL=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`APIGatewayURL`].OutputValue' \
  --output text)

CHAT_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`ChatEndpoint`].OutputValue' \
  --output text)

echo "✅ Outputs retrieved"
echo ""

# Test S3 bucket
echo "Testing S3 bucket..."
if aws s3 ls s3://$DATA_BUCKET &> /dev/null; then
    echo "✅ S3 bucket accessible: $DATA_BUCKET"
else
    echo "❌ S3 bucket not accessible: $DATA_BUCKET"
fi
echo ""

# Test Neptune
echo "Testing Neptune cluster..."
NEPTUNE_STATUS=$(aws neptune describe-db-clusters \
  --query 'DBClusters[0].Status' \
  --output text 2>/dev/null || echo "unknown")

if [ "$NEPTUNE_STATUS" = "available" ]; then
    echo "✅ Neptune cluster available: $NEPTUNE_ENDPOINT"
else
    echo "⚠️  Neptune cluster status: $NEPTUNE_STATUS"
fi
echo ""

# Test API Gateway health endpoint
echo "Testing API Gateway health endpoint..."
HEALTH_RESPONSE=$(curl -s -w "%{http_code}" -o /tmp/health_response.txt "${API_URL}health" || echo "000")

if [ "$HEALTH_RESPONSE" = "200" ]; then
    echo "✅ API Gateway health check passed"
    cat /tmp/health_response.txt | jq '.' 2>/dev/null || cat /tmp/health_response.txt
else
    echo "⚠️  API Gateway health check returned: $HEALTH_RESPONSE"
fi
echo ""

# Test Lambda functions
echo "Testing Lambda functions..."
FUNCTIONS=(
    "image-collector"
    "data-extractor"
    "entity-extractor"
    "neptune-loader"
    "chat-handler"
)

for func in "${FUNCTIONS[@]}"; do
    FUNCTION_NAME=$(aws lambda list-functions \
      --query "Functions[?contains(FunctionName, '$func')].FunctionName" \
      --output text)
    
    if [ -n "$FUNCTION_NAME" ]; then
        echo "✅ Lambda function exists: $FUNCTION_NAME"
    else
        echo "❌ Lambda function not found: $func"
    fi
done
echo ""

# Summary
echo "========================================="
echo "Deployment Test Summary"
echo "========================================="
echo ""
echo "Stack Name: $STACK_NAME"
echo "Data Bucket: $DATA_BUCKET"
echo "State Machine: $STATE_MACHINE_ARN"
echo "Neptune Endpoint: $NEPTUNE_ENDPOINT"
echo "API Gateway URL: $API_URL"
echo "Chat Endpoint: $CHAT_ENDPOINT"
echo ""
echo "========================================="
echo "Next Steps"
echo "========================================="
echo ""
echo "1. Start a test pipeline execution:"
echo "   aws stepfunctions start-execution \\"
echo "     --state-machine-arn $STATE_MACHINE_ARN \\"
echo "     --input '{\"start_date\":\"1815-08-01\",\"end_date\":\"1815-08-01\",\"max_pages\":1}'"
echo ""
echo "2. Test the chat API:"
echo "   curl -X POST $CHAT_ENDPOINT \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"question\":\"What newspapers are available?\"}'"
echo ""
echo "3. Monitor execution:"
echo "   - Step Functions: https://console.aws.amazon.com/states/home"
echo "   - CloudWatch Logs: https://console.aws.amazon.com/cloudwatch/home"
echo ""

exit 0
