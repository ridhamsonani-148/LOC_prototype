# Deployment Guide - Fully Automated GraphRAG Pipeline

## Overview

This guide shows how to deploy the complete end-to-end pipeline with **automatic Bedrock Knowledge Base creation**. No manual configuration needed!

## Prerequisites

- AWS Account with appropriate permissions
- AWS CLI configured
- Node.js 20+ installed
- Docker installed (for Lambda container images)

## One-Command Deployment

```bash
cd backend
./deploy.sh
```

That's it! This single command:
1. ✅ Installs dependencies
2. ✅ Builds TypeScript code
3. ✅ Builds Docker images for Lambda functions
4. ✅ Creates VPC and Neptune cluster
5. ✅ Creates all Lambda functions
6. ✅ Creates Step Functions pipeline
7. ✅ **Creates OpenSearch Serverless collection**
8. ✅ **Creates Bedrock Knowledge Base automatically**
9. ✅ **Configures S3 Data Source for KB**
10. ✅ Creates API Gateway
11. ✅ Sets up all IAM roles and permissions

## What Gets Created

### Infrastructure
- **VPC**: 2 AZs with public, private, and isolated subnets
- **Neptune**: Graph database cluster with 1 instance (db.t3.medium)
- **S3 Bucket**: For storing images, PDFs, and extracted data

### Lambda Functions
1. **image-collector**: Fetches newspaper images from LOC API
2. **image-to-pdf**: Converts images to PDF format
3. **bedrock-data-automation**: Extracts text using Bedrock
4. **neptune-loader**: Loads documents to Neptune
5. **chat-handler**: Handles chat queries via Bedrock KB

### Bedrock Knowledge Base (Automatic!)
- **Name**: `chronicling-america-pipeline-graphrag-kb`
- **Type**: Vector with OpenSearch Serverless storage
- **Embeddings**: Amazon Titan Embed Text v2
- **Data Source**: S3 (`kb-documents/` prefix)
- **Configuration**:
  - Chunking: Fixed size (1000 tokens, 20% overlap)
  - Auto-extracts entities and relationships (GraphRAG)
  - Serverless vector store

### API Gateway
- **Endpoint**: `/chat` (POST) - Chat interface
- **Endpoint**: `/health` (GET) - Health check

## Post-Deployment Steps

### 1. Get Stack Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name ChroniclingAmericaStack \
  --query 'Stacks[0].Outputs'
```

**Key Outputs:**
- `StateMachineArn`: Step Functions ARN
- `KnowledgeBaseId`: Bedrock KB ID (auto-created!)
- `DataSourceId`: Data source ID (auto-created!)
- `OpenSearchCollectionArn`: OpenSearch Serverless collection ARN
- `ChatEndpoint`: API endpoint for chat
- `NeptuneEndpoint`: Neptune cluster endpoint

### 2. Run Pipeline to Load Documents

```bash
# Get State Machine ARN
STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
  --stack-name ChroniclingAmericaStack \
  --query 'Stacks[0].Outputs[?OutputKey==`StateMachineArn`].OutputValue' \
  --output text)

# Start execution
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{
    "start_date": "1815-08-01",
    "end_date": "1815-08-31",
    "max_pages": 10
  }'
```

**Monitor Progress:**
- AWS Console → Step Functions → Select execution
- Watch each step complete: Image Collection → PDF Conversion → Text Extraction → Neptune Loading

### 3. Sync Knowledge Base (Trigger Entity Extraction)

After documents are loaded to Neptune, sync the Knowledge Base to extract entities:

```bash
# Get Knowledge Base and Data Source IDs
KB_ID=$(aws cloudformation describe-stacks \
  --stack-name ChroniclingAmericaStack \
  --query 'Stacks[0].Outputs[?OutputKey==`KnowledgeBaseId`].OutputValue' \
  --output text)

DS_ID=$(aws cloudformation describe-stacks \
  --stack-name ChroniclingAmericaStack \
  --query 'Stacks[0].Outputs[?OutputKey==`KnowledgeBaseDataSourceId`].OutputValue' \
  --output text)

# Start ingestion job (entity extraction)
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id $KB_ID \
  --data-source-id $DS_ID
```

**Monitor Sync:**
```bash
# Check ingestion job status
aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id $KB_ID \
  --data-source-id $DS_ID
```

Or use AWS Console:
- Go to Amazon Bedrock → Knowledge Bases
- Select your knowledge base
- Click "Sync" button
- Wait for completion (usually 5-15 minutes)

### 4. Test the System

```bash
# Get API endpoint
API_URL=$(aws cloudformation describe-stacks \
  --stack-name ChroniclingAmericaStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ChatEndpoint`].OutputValue' \
  --output text)

# Test health check
curl $API_URL/../health

# Test chat query
curl -X POST $API_URL \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What people were mentioned in Providence newspapers in 1815?"
  }'
```

**Expected Response:**
```json
{
  "question": "What people were mentioned in Providence newspapers in 1815?",
  "answer": "Based on the historical newspapers from 1815, several people were mentioned in Providence...",
  "sources": [
    {
      "document_id": "...",
      "content": "..."
    }
  ],
  "entities": [
    {
      "type": "PERSON",
      "name": "John Smith",
      "confidence": 0.95
    }
  ]
}
```

## Verification Steps

### Check Neptune Documents

```bash
# Connect to Neptune (requires VPN or bastion host)
# Or use Neptune Workbench in AWS Console

# Query to check documents
g.V().hasLabel('Document').count()
g.V().hasLabel('Document').limit(1).valueMap(true)
```

### Check Knowledge Base Status

```bash
# Get Knowledge Base details
aws bedrock-agent get-knowledge-base \
  --knowledge-base-id $KB_ID

# Check data source status
aws bedrock-agent get-data-source \
  --knowledge-base-id $KB_ID \
  --data-source-id $DS_ID
```

### Check Lambda Logs

```bash
# Chat handler logs
aws logs tail /aws/lambda/chronicling-america-pipeline-chat-handler --follow

# Neptune loader logs
aws logs tail /aws/lambda/chronicling-america-pipeline-neptune-loader --follow
```

## Troubleshooting

### Knowledge Base Not Created

**Check CloudFormation:**
```bash
aws cloudformation describe-stack-events \
  --stack-name ChroniclingAmericaStack \
  --query 'StackEvents[?ResourceType==`AWS::Bedrock::KnowledgeBase`]'
```

**Common Issues:**
- Bedrock service not available in region (use us-east-1 or us-west-2)
- IAM permissions missing for Bedrock
- VPC configuration issues

### Chat Returns Empty Results

**Possible Causes:**
1. Knowledge Base not synced yet
2. No documents in Neptune
3. Wrong vertex label or text field

**Fix:**
```bash
# Re-sync Knowledge Base
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id $KB_ID \
  --data-source-id $DS_ID

# Check Neptune documents
# Use Neptune Workbench or query from Lambda
```

### Pipeline Fails

**Check Step Functions:**
- AWS Console → Step Functions → Select execution
- Look for failed step
- Check Lambda logs for that step

**Common Issues:**
- Lambda timeout (increase in CDK)
- Memory limit (increase in CDK)
- Bedrock throttling (add retry logic)

## Cost Estimation

### Monthly Costs (Approximate)

**For 1000 documents:**
- Neptune db.t3.medium: ~$100/month
- Lambda executions: ~$5/month
- Bedrock Knowledge Base: ~$10/month
- Bedrock model invocations: ~$20/month
- S3 storage: ~$1/month
- **Total: ~$136/month**

**For 10,000 documents:**
- Neptune db.t3.medium: ~$100/month
- Lambda executions: ~$15/month
- Bedrock Knowledge Base: ~$50/month
- Bedrock model invocations: ~$100/month
- S3 storage: ~$5/month
- **Total: ~$270/month**

## Cleanup

To delete all resources:

```bash
cd backend
cdk destroy
```

**Note:** S3 bucket is retained by default. Delete manually if needed:
```bash
aws s3 rb s3://chronicling-america-pipeline-data-<account>-<region> --force
```

## Next Steps

1. **Scale Up**: Increase `max_pages` in pipeline input
2. **Add More Data**: Run pipeline with different date ranges
3. **Customize Entities**: Modify Knowledge Base entity types
4. **Build UI**: Create web interface using the chat API
5. **Add Analytics**: Query Neptune for insights

## Support

- [AWS Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
- [Neptune Documentation](https://docs.aws.amazon.com/neptune/)
- [CDK Documentation](https://docs.aws.amazon.com/cdk/)
