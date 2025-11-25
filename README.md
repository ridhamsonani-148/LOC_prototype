# Chronicling America GraphRAG Pipeline

Complete AWS CDK infrastructure for automated historical newspaper and congressional bill data extraction with **GraphRAG using Amazon Bedrock Knowledge Bases**.

## 🚀 Quick Start

### Step 1: Deploy Infrastructure

```bash
cd backend
./deploy.sh
```

**Time:** ~20-25 minutes

**What gets deployed:**

- ✅ VPC & Neptune cluster
- ✅ 7 Lambda functions (Docker-based)
- ✅ S3 bucket with automatic document export to `kb-documents/`
- ✅ Step Functions pipeline
- ✅ API Gateway

### Step 2: Create Bedrock Knowledge Base (5 minutes - Manual)

After deployment, create the Knowledge Base in AWS Console:

1. Go to **Amazon Bedrock** → **Knowledge Bases** → **Create**
2. **Name**: `chronicling-america-kb`
3. **Data Source**: Amazon S3
4. **S3 URI**: Get from stack output `KBDocumentsPrefix`
5. **Embeddings**: Titan Text Embeddings V2
6. **Vector Store**: Quick create new (OpenSearch Serverless)
7. Click **Create** and wait ~10 minutes

Then update Lambda environment variables:
```bash
# Get KB ID and Data Source ID from Bedrock console
aws lambda update-function-configuration \
  --function-name chronicling-america-pipeline-kb-sync-trigger \
  --environment "Variables={KNOWLEDGE_BASE_ID=your-kb-id,DATA_SOURCE_ID=your-ds-id}"

aws lambda update-function-configuration \
  --function-name chronicling-america-pipeline-chat-handler \
  --environment "Variables={KNOWLEDGE_BASE_ID=your-kb-id,...}"
```

### Quick Test

```bash
# Test with 5 Congress bills (30 seconds)
python backend/test_backend.py --source congress --limit 5

# Test with 5 newspapers (5 minutes)
python backend/test_backend.py --source newspapers --max-pages 5
```

### Query the Knowledge Base

```bash
# Get chat endpoint
CHAT_URL=$(aws cloudformation describe-stacks \
  --stack-name ChroniclingAmericaStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ChatEndpoint`].OutputValue' \
  --output text)

# Query
curl -X POST $CHAT_URL \
  -H "Content-Type: application/json" \
  -d '{"question": "What bills were introduced about taxation?"}'
```

## 🎯 What is GraphRAG?

**GraphRAG** (Graph Retrieval-Augmented Generation) combines:

- **Graph Database** (Neptune) - Stores document relationships
- **Vector Search** (OpenSearch Serverless) - Semantic similarity
- **LLM** (Claude via Bedrock) - Natural language understanding

### Why This Approach?

- ✅ **Automatic Entity Extraction**: No manual NLP pipelines
- ✅ **Better Accuracy**: Bedrock uses advanced foundation models
- ✅ **Semantic Search**: Vector embeddings for intelligent retrieval
- ✅ **Scalable**: Handles thousands of documents efficiently
- ✅ **Cost Effective**: Pay only for what you use

## 📊 Architecture

```
Data Sources (LOC/Congress)
    ↓
Step Functions Pipeline
    ├─ Image Collector
    ├─ Image to PDF
    ├─ Bedrock Data Automation
    ├─ Neptune Loader
    ├─ Neptune Exporter → S3 (kb-documents/)
    └─ KB Sync Trigger
    ↓
Bedrock Knowledge Base (AUTO-CREATED!)
    ├─ OpenSearch Serverless (vectors)
    ├─ Titan Embeddings v2
    └─ Automatic entity extraction
    ↓
Chat Handler Lambda
    └─ Natural language queries
```

## 🔧 Prerequisites

### Required

- AWS Account with appropriate permissions
- AWS CLI installed and configured
- Node.js 18+ and npm
- Bedrock model access (Claude 3.5 Sonnet, Titan Embeddings v2)
- Docker (for Lambda container builds)

### Quick Setup

```bash
# Install AWS CLI
# https://aws.amazon.com/cli/

# Configure AWS credentials
aws configure

# Install Node.js
# https://nodejs.org/

# Install AWS CDK
npm install -g aws-cdk@2.161.1
```

## 📋 What Gets Deployed

### Infrastructure

- **VPC**: 2 AZs with public, private, and isolated subnets
- **Neptune**: Graph database cluster (db.t3.medium)
- **S3 Bucket**: Data storage with `kb-documents/` prefix
- **OpenSearch Serverless**: Vector store for embeddings
- **Bedrock Knowledge Base**: Auto-created with S3 data source

### Lambda Functions (7 total)

1. **image-collector**: Fetches from LOC/Congress APIs
2. **image-to-pdf**: Converts images to PDF
3. **bedrock-data-automation**: Extracts text using Bedrock
4. **neptune-loader**: Stores documents in Neptune
5. **neptune-exporter**: Exports docs to S3 for KB
6. **kb-sync-trigger**: Triggers KB ingestion
7. **chat-handler**: Queries KB for answers

### Step Functions Pipeline

Fully automated orchestration:

```
collect → pdf → extract → neptune → export → sync-kb → DONE!
```

## 📖 Usage Examples

### Start Pipeline - Newspapers

```bash
STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
  --stack-name ChroniclingAmericaStack \
  --query 'Stacks[0].Outputs[?OutputKey==`StateMachineArn`].OutputValue' \
  --output text)

aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{
    "source": "newspapers",
    "start_date": "1815-08-01",
    "end_date": "1815-08-31",
    "max_pages": 10
  }'
```

### Start Pipeline - Congressional Bills

```bash
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{
    "source": "congress",
    "congress": 118,
    "bill_type": "hr",
    "limit": 10
  }'
```

### Monitor KB Sync Status

```bash
KB_ID=$(aws cloudformation describe-stacks \
  --stack-name ChroniclingAmericaStack \
  --query 'Stacks[0].Outputs[?OutputKey==`KnowledgeBaseId`].OutputValue' \
  --output text)

DS_ID=$(aws cloudformation describe-stacks \
  --stack-name ChroniclingAmericaStack \
  --query 'Stacks[0].Outputs[?OutputKey==`DataSourceId`].OutputValue' \
  --output text)

aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id $KB_ID \
  --data-source-id $DS_ID
```

## 💰 Cost Estimation

### Monthly Costs (100 documents)

| Service                | Cost            | Notes                  |
| ---------------------- | --------------- | ---------------------- |
| OpenSearch Serverless  | ~$175           | Minimum 2 OCUs         |
| Neptune (db.t3.medium) | ~$73            | 24/7 operation         |
| Lambda (7 functions)   | ~$0.50          | All pipeline steps     |
| Bedrock (embeddings)   | ~$0.50          | One-time per document  |
| Bedrock (queries)      | ~$0.10          | Per 1000 queries       |
| S3 Storage             | ~$0.10          | All data               |
| VPC (NAT Gateway)      | ~$32            | Network connectivity   |
| **Total**              | **~$281/month** | **First month: ~$282** |

### Per Query Costs

- Bedrock Embeddings: ~$0.0001/query
- Bedrock LLM (Claude Sonnet): ~$0.003/query
- **Total**: ~$0.003/query

### Cost Optimization Tips

1. **Stop Neptune when not in use** → Save $73/month
2. **Use smaller Neptune instance** (db.t3.small) → Save 50%
3. **Batch processing** → Reduce Lambda invocations
4. **Monitor OpenSearch OCUs** → Adjust based on usage

## 🔍 Monitoring

### CloudWatch Logs

```bash
# View Lambda logs
aws logs tail /aws/lambda/chronicling-america-pipeline-kb-sync-trigger --follow

# View Step Functions logs
aws logs tail /aws/stepfunctions/chronicling-america-pipeline --follow
```

### Check Stack Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name ChroniclingAmericaStack \
  --query 'Stacks[0].Outputs'
```

**Key Outputs:**

- `KBDocumentsPrefix`: S3 prefix where documents are exported (use for KB setup)
- `ChatEndpoint`: API endpoint for queries
- `NeptuneEndpoint`: Neptune cluster endpoint
- `StateMachineArn`: Step Functions pipeline ARN
- `DataBucketName`: S3 bucket name

## 🐛 Troubleshooting

### OpenSearch Serverless Takes Long

**Expected:** 10-15 minutes for provisioning  
**Solution:** Normal, wait patiently

### KB Sync Fails

**Cause:** OpenSearch collection not ready  
**Solution:** Wait 5 minutes, retry pipeline

### No Query Results

**Cause:** Ingestion not complete  
**Solution:** Check ingestion status, wait for COMPLETE

### Lambda Timeout

**Cause:** Large dataset  
**Solution:** Normal, ingestion continues in background

### Build Error: `CfnCollection` not found

**Cause:** Using wrong CDK construct  
**Solution:** Use `opensearchserverless.CfnCollection` (already fixed in latest code)

## 📁 Project Structure

```
backend/
├── bin/
│   └── chronicling-america-cdk.ts          # CDK app entry
├── lib/
│   └── chronicling-america-stack.ts        # Infrastructure stack
├── lambda/
│   ├── image-collector/                    # Fetch from APIs
│   ├── image-to-pdf/                       # Convert images
│   ├── bedrock-data-automation/            # Extract text
│   ├── neptune-loader/                     # Load to Neptune
│   ├── neptune-exporter/                   # Export to S3
│   ├── kb-sync-trigger/                    # Trigger KB sync
│   └── chat-handler/                       # Chat API
├── deploy.sh                               # Automated deployment
├── test_backend.py                         # Test script
└── README.md                               # This file
```

## 🧹 Cleanup

```bash
# Destroy all resources
cd backend
cdk destroy ChroniclingAmericaStack --force

# Delete S3 bucket (retained by default)
BUCKET=$(aws cloudformation describe-stacks \
  --stack-name ChroniclingAmericaStack \
  --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

aws s3 rb s3://$BUCKET --force
```

## 🎓 How It Works

### 1. Data Collection

- Fetches newspaper images from Chronicling America API
- OR fetches congressional bills from Congress.gov API
- Saves raw data to S3

### 2. Text Extraction

- Converts images to PDF (newspapers only)
- Extracts text using Bedrock Data Automation
- Saves extracted text to S3

### 3. Document Storage

- Loads documents to Neptune as vertices
- Stores full text in `document_text` property
- Adds metadata (title, date, source)

### 4. S3 Export for KB

- Queries all Document vertices from Neptune
- Exports to S3 in Bedrock KB format (`kb-documents/`)
- Each document includes: id, title, content, metadata

### 5. Knowledge Base Sync

- Automatically triggers after S3 export
- Bedrock KB reads from S3 and:
  - Chunks documents (1000 tokens, 20% overlap)
  - Extracts entities automatically
  - Creates relationships automatically
  - Generates vector embeddings
  - Stores in OpenSearch Serverless

### 6. Intelligent Queries

- Receives natural language questions via API
- KB performs semantic search using embeddings
- Traverses entity relationships
- Generates context-aware answers with citations

## 🎯 Success Criteria

- ✅ CDK deployment completes without errors
- ✅ All stack outputs present (KB ID, DS ID, OSS ARN)
- ✅ OpenSearch Serverless collection active
- ✅ Bedrock Knowledge Base created
- ✅ S3 Data Source configured
- ✅ Lambda env vars auto-populated
- ✅ Pipeline runs successfully
- ✅ Documents exported to S3
- ✅ KB sync triggered automatically
- ✅ Ingestion job completes
- ✅ Chat queries return relevant results

## 📚 Additional Resources

- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [Amazon Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
- [Amazon Neptune Documentation](https://docs.aws.amazon.com/neptune/)
- [OpenSearch Serverless Documentation](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html)
- [Build GraphRAG with Bedrock Knowledge Bases](https://aws.amazon.com/blogs/machine-learning/build-graphrag-applications-using-amazon-bedrock-knowledge-bases/)

## 📝 License

This project is provided as-is for educational and research purposes.

## 🎉 Summary

**Your fully automated GraphRAG pipeline:**

- ✅ Zero manual console steps
- ✅ Everything defined in code
- ✅ One command deployment
- ✅ Automatic entity extraction
- ✅ Relationship discovery
- ✅ Semantic search enabled

**Start extracting historical insights!** 🚀
