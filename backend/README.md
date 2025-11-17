# Chronicling America Historical Newspaper Pipeline - Backend

Complete AWS CDK infrastructure for automated historical newspaper data extraction and knowledge graph generation.

## 🚀 Quick Start

### One-Command Deployment

```bash
cd backend
chmod +x deploy.sh quick-start.sh test-deployment.sh
./deploy.sh
```

**That's it!** The script will:
1. ✅ Create IAM roles
2. ✅ Set up CodeBuild project
3. ✅ Build Docker images
4. ✅ Deploy all infrastructure
5. ✅ Output API endpoints

**Deployment time**: ~20-30 minutes

### Test Deployment

```bash
./test-deployment.sh
```

## 📋 What Gets Deployed

### Infrastructure Components

- **5 Lambda Functions** (Docker-based, no manual layers!)
  - Image Collector
  - Data Extractor (Bedrock)
  - Entity Extractor (Bedrock)
  - Neptune Loader
  - Chat Handler

- **Step Functions** - Pipeline orchestration
- **Neptune Cluster** - Graph database
- **VPC** - Network isolation
- **S3 Bucket** - Data storage
- **API Gateway** - REST API for chat

### Architecture Flow

```
1. Image Collector Lambda
   ↓ Fetches from Chronicling America API
   ↓ Saves to S3: images/

2. Data Extractor Lambda
   ↓ Downloads images
   ↓ Extracts data with Bedrock
   ↓ Saves to S3: extracted/

3. Entity Extractor Lambda
   ↓ Reads extracted data
   ↓ Extracts entities/relationships
   ↓ Saves to S3: knowledge_graphs/

4. Neptune Loader Lambda
   ↓ Reads knowledge graphs
   ↓ Loads into Neptune

5. Chat Handler Lambda (API Gateway)
   ↓ Receives questions
   ↓ Queries Neptune
   ↓ Returns answers
```

## 🎯 Key Features

### ✅ Docker-Based Lambda Functions
- **No manual layer creation required**
- Dependencies automatically managed
- Consistent runtime environment
- Easy to update and maintain

### ✅ Automated Deployment
- One-command deployment via CodeBuild
- No local Docker required
- Builds in AWS environment
- Consistent across teams

### ✅ Complete Pipeline
- Step Functions orchestration
- Error handling and retries
- CloudWatch logging
- S3 data persistence

### ✅ Chat API
- Natural language queries
- Bedrock-powered responses
- CORS enabled
- Health check endpoint

## 📖 Documentation

- **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** - Complete deployment instructions
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Technical details
- **[README.md](README.md)** - This file

## 🔧 Prerequisites

### Required
- AWS Account with appropriate permissions
- AWS CLI installed and configured
- Node.js 18+ and npm
- Bedrock model access (Claude 3.5 Sonnet)

### Optional
- Docker (for local development)
- Git (for version control)

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

# Verify setup
./quick-start.sh
```

## 🚀 Deployment Options

### Option 1: Automated (Recommended)

```bash
./deploy.sh
```

**Best for**: Production, CI/CD, teams

### Option 2: Manual CDK

```bash
npm install
npm run build
cdk deploy --all
```

**Best for**: Development, customization

### Option 3: AWS CloudShell

```bash
# Open CloudShell in AWS Console
git clone YOUR-REPO-URL
cd YOUR-REPO/backend
./deploy.sh
```

**Best for**: No local setup required

## 📊 Usage Examples

### Start Pipeline

```bash
aws stepfunctions start-execution \
  --state-machine-arn <ARN_FROM_OUTPUTS> \
  --input '{
    "start_date": "1815-08-01",
    "end_date": "1815-08-31",
    "max_pages": 10
  }'
```

## Project Structure

```
backend/
├── bin/
│   └── chronicling-america-cdk.ts    # CDK app entry point
├── lib/
│   └── chronicling-america-stack.ts  # Main stack definition
├── lambda/
│   ├── image-collector/              # Fetch images from LOC API
│   ├── data-extractor/               # Extract data with Bedrock
│   ├── entity-extractor/             # Extract entities/relationships
│   ├── neptune-loader/               # Load data into Neptune
│   └── chat-handler/                 # Chat UI backend
├── deploy.sh                         # Automated deployment script
├── buildspec.yml                     # CodeBuild configuration
├── cdk.json                          # CDK configuration
├── package.json                      # Node.js dependencies
└── README.md                         # This file
```

## Lambda Functions

All Lambda functions use Docker containers for automatic dependency management:

1. **Image Collector**: Fetches newspaper images from Chronicling America API
2. **Data Extractor**: Uses Bedrock to extract structured data from images
3. **Entity Extractor**: Extracts entities and relationships using Claude
4. **Neptune Loader**: Loads knowledge graphs into Neptune
5. **Chat Handler**: Provides chat interface for querying the knowledge graph

## Environment Variables

Set in CDK stack:
- `DATA_BUCKET`: S3 bucket for pipeline data
- `BEDROCK_MODEL_ID`: Bedrock model ID (default: Claude 3.5 Sonnet)
- `NEPTUNE_ENDPOINT`: Neptune cluster endpoint
- `NEPTUNE_PORT`: Neptune port (default: 8182)

## Cost Estimation

- **Lambda**: ~$0.20 per 1000 invocations
- **Bedrock**: ~$0.012 per image (Claude 3.5 Sonnet)
- **Neptune**: ~$0.10/hour (db.t3.medium)
- **S3**: ~$0.023/GB/month
- **Step Functions**: ~$0.025 per 1000 state transitions

**Total for 100 newspapers**: ~$2-5

## Monitoring

- CloudWatch Logs: `/aws/lambda/<function-name>`
- Step Functions: AWS Console → Step Functions
- Neptune: CloudWatch metrics for cluster

## Troubleshooting

### Lambda timeout
- Increase timeout in CDK stack (default: 15 minutes)

### Bedrock access denied
- Enable model access in Bedrock console
- Check IAM permissions

### Neptune connection failed
- Verify VPC configuration
- Check security group rules

## Next Steps

1. Deploy the stack
2. Start a pipeline execution
3. Monitor in Step Functions console
4. Query Neptune via chat UI
5. Customize extraction prompts in Lambda code

## Support

For issues, check CloudWatch logs or create an issue in the repository.


### Query Chat API

```bash
curl -X POST https://YOUR-API-ID.execute-api.us-west-2.amazonaws.com/prod/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "Who are the people mentioned in the newspapers?"
  }'
```

### Check Health

```bash
curl https://YOUR-API-ID.execute-api.us-west-2.amazonaws.com/prod/health
```

## 💰 Cost Estimation

### Monthly Costs (100 newspapers)

| Service | Cost |
|---------|------|
| Lambda | $0.50 |
| Bedrock | $2.40 |
| Neptune | $73.00 |
| S3 | $0.05 |
| Step Functions | $0.50 |
| API Gateway | $0.01 |
| VPC (NAT Gateway) | $32.00 |
| CloudWatch | $0.50 |
| **Total** | **~$109/month** |

### 💡 Cost Optimization Tips

1. **Stop Neptune when not in use** → Save $73/month
2. **Use Claude Haiku instead of Sonnet** → Save 90% on Bedrock
3. **Reduce Lambda memory** → Save 20-30%
4. **Use S3 Intelligent-Tiering** → Automatic cost optimization

## 🔍 Monitoring

### CloudWatch Logs

```bash
# View Lambda logs
aws logs tail /aws/lambda/chronicling-america-pipeline-image-collector --follow

# View Step Functions logs
aws logs tail /aws/stepfunctions/chronicling-america-pipeline --follow
```

### Step Functions Console

Monitor pipeline execution:
- https://console.aws.amazon.com/states/home

### Neptune Metrics

View in CloudWatch:
- CPU utilization
- Memory usage
- Connection count

## 🐛 Troubleshooting

### Common Issues

#### Lambda Timeout
**Error**: Task timed out after 15 minutes

**Solution**: Reduce `max_pages` or increase timeout in CDK stack

#### Bedrock Access Denied
**Error**: AccessDeniedException

**Solution**: Enable model access in Bedrock console

#### Neptune Connection Failed
**Error**: Cannot connect to Neptune

**Solution**: 
- Verify Lambda is in VPC
- Check security group rules
- Wait for Neptune to be available

#### Docker Build Failed
**Error**: Cannot build image

**Solution**:
- Ensure Docker is running (local)
- Enable privileged mode in CodeBuild
- Check Dockerfile syntax

### Debug Commands

```bash
# Check stack status
aws cloudformation describe-stacks --stack-name ChroniclingAmericaStack

# Check Lambda function
aws lambda get-function --function-name chronicling-america-pipeline-image-collector

# Check Neptune cluster
aws neptune describe-db-clusters

# Test API Gateway
curl -X GET https://YOUR-API-ID.execute-api.us-west-2.amazonaws.com/prod/health
```

## 📁 Project Structure

```
backend/
├── bin/
│   └── chronicling-america-cdk.ts          # CDK app entry
├── lib/
│   └── chronicling-america-stack.ts        # Infrastructure stack
├── lambda/
│   ├── image-collector/                    # Fetch images
│   ├── data-extractor/                     # Extract with Bedrock
│   ├── entity-extractor/                   # Extract entities
│   ├── neptune-loader/                     # Load to Neptune
│   └── chat-handler/                       # Chat API
├── deploy.sh                               # Automated deployment
├── buildspec.yml                           # CodeBuild config
├── quick-start.sh                          # Setup verification
├── test-deployment.sh                      # Test script
├── package.json                            # Dependencies
├── tsconfig.json                           # TypeScript config
├── cdk.json                                # CDK config
├── README.md                               # This file
├── DEPLOYMENT_GUIDE.md                     # Detailed guide
└── IMPLEMENTATION_SUMMARY.md               # Technical details
```

## 🔄 Pipeline Steps

### 1. Image Collection
- Fetches newspaper images from Chronicling America API
- Filters by date range
- Deduplicates results
- Saves to S3

### 2. Data Extraction
- Downloads images from URLs
- Resizes for Bedrock
- Extracts structured data using Claude
- Saves JSON to S3

### 3. Entity Extraction
- Reads extracted data
- Identifies entities (people, places, organizations)
- Extracts relationships
- Creates knowledge graph

### 4. Neptune Loading
- Connects to Neptune cluster
- Creates vertices (entities)
- Creates edges (relationships)
- Handles duplicates

### 5. Chat Interface
- Receives natural language questions
- Generates Gremlin queries
- Executes on Neptune
- Returns formatted answers

## 🎨 Customization

### Modify Extraction Prompts

Edit `lambda/data-extractor/lambda_function.py`:

```python
extraction_prompt = """
Your custom prompt here...
"""
```

### Add Custom Entity Types

Edit `lambda/entity-extractor/lambda_function.py`:

```python
# Add to entity types
"CUSTOM_TYPE": "Your custom entity type"
```

### Adjust Lambda Settings

Edit `lib/chronicling-america-stack.ts`:

```typescript
timeout: cdk.Duration.minutes(20),  // Increase timeout
memorySize: 3008,                   // Increase memory
```

## 🧹 Cleanup

### Destroy All Resources

```bash
./deploy.sh
# Choose "destroy" when prompted
```

### Manual Cleanup

```bash
cdk destroy ChroniclingAmericaStack --force

# Delete S3 bucket (retained by default)
aws s3 rb s3://YOUR-BUCKET-NAME --force
```

## 📚 Additional Resources

- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [AWS Lambda Documentation](https://docs.aws.amazon.com/lambda/)
- [Amazon Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
- [Amazon Neptune Documentation](https://docs.aws.amazon.com/neptune/)
- [Chronicling America API](https://chroniclingamerica.loc.gov/about/api/)

## 🤝 Support

For issues:
1. Check [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
2. Review CloudWatch Logs
3. Run `./test-deployment.sh`
4. Check AWS service quotas
5. Verify IAM permissions

## 📝 License

This project is provided as-is for educational and research purposes.

## 🎉 Success!

After deployment, you'll have:
- ✅ Complete data extraction pipeline
- ✅ Graph database with historical data
- ✅ Chat API for querying
- ✅ Automated orchestration
- ✅ Monitoring and logging

**Start extracting historical insights!** 🚀
