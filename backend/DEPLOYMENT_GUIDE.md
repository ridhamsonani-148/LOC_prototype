# Chronicling America Pipeline - Deployment Guide

Complete guide for deploying the historical newspaper data extraction pipeline to AWS.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Deployment Methods](#deployment-methods)
4. [Architecture Overview](#architecture-overview)
5. [Pipeline Execution](#pipeline-execution)
6. [Monitoring](#monitoring)
7. [Troubleshooting](#troubleshooting)
8. [Cost Estimation](#cost-estimation)

## Prerequisites

### AWS Account Setup

1. **AWS Account** with appropriate permissions
2. **AWS CLI** installed and configured
   ```bash
   aws configure
   ```
3. **Bedrock Model Access**
   - Go to AWS Console → Bedrock → Model access
   - Request access to Claude 3.5 Sonnet v2
   - Wait for approval (usually instant)

### Local Development Tools

- **Node.js 18+** and npm
- **AWS CDK CLI**
  ```bash
  npm install -g aws-cdk@2.161.1
  ```
- **Docker** (for building Lambda container images)
- **Git** for cloning the repository

### IAM Permissions Required

Your AWS user/role needs:
- CloudFormation full access
- Lambda full access
- S3 full access
- EC2 (for VPC)
- Neptune full access
- Bedrock InvokeModel
- IAM role creation
- API Gateway
- Step Functions
- CloudWatch Logs

## Quick Start

### Option 1: Automated Deployment (Recommended)

```bash
cd backend
chmod +x deploy.sh
./deploy.sh
```

Follow the prompts:
- **GitHub URL**: Your forked repository URL
- **Project Name**: `chronicling-america-pipeline` (or custom)
- **AWS Region**: `us-west-2` (or your preferred region)
- **Action**: `deploy`

The script will:
1. Create IAM role for CodeBuild
2. Create CodeBuild project
3. Start automated deployment
4. Deploy all infrastructure via CDK

**Deployment time**: ~20-30 minutes

### Option 2: Manual CDK Deployment

```bash
cd backend

# Install dependencies
npm install

# Bootstrap CDK (first time only)
cdk bootstrap

# Deploy the stack
cdk deploy ChroniclingAmericaStack \
  --context projectName=chronicling-america-pipeline \
  --context dataBucketName=my-data-bucket \
  --context bedrockModelId=anthropic.claude-3-5-sonnet-20241022-v2:0
```

## Deployment Methods

### Method 1: AWS CodeBuild (Automated)

**Best for**: Production deployments, CI/CD pipelines

```bash
./deploy.sh
```

**Advantages**:
- Fully automated
- Consistent environment
- Build logs in CloudWatch
- No local Docker required

**Process**:
1. Creates CodeBuild project
2. Clones repository
3. Builds Docker images
4. Deploys CDK stack
5. Outputs deployment info

### Method 2: AWS CloudShell

**Best for**: Quick deployments without local setup

1. Open AWS CloudShell in AWS Console
2. Clone repository:
   ```bash
   git clone https://github.com/YOUR-USERNAME/YOUR-REPO.git
   cd YOUR-REPO/backend
   ```
3. Run deployment:
   ```bash
   chmod +x deploy.sh
   ./deploy.sh
   ```

### Method 3: Local CDK Deployment

**Best for**: Development, testing, customization

```bash
cd backend
npm install
npm run build
cdk deploy --all
```

## Architecture Overview

### Components Deployed

1. **S3 Bucket** (`${project}-data-${account}-${region}`)
   - Stores images, extracted data, knowledge graphs
   - Lifecycle policy: 90-day retention

2. **VPC** (2 AZs)
   - Public subnets (NAT Gateway)
   - Private subnets (Lambda functions)
   - Isolated subnets (Neptune)

3. **Neptune Cluster**
   - Instance type: db.t3.medium
   - Storage: Encrypted
   - Port: 8182

4. **Lambda Functions** (Docker-based)
   - Image Collector (15 min timeout, 1GB memory)
   - Data Extractor (15 min timeout, 2GB memory)
   - Entity Extractor (15 min timeout, 2GB memory)
   - Neptune Loader (15 min timeout, 1GB memory)
   - Chat Handler (30 sec timeout, 1GB memory)

5. **Step Functions State Machine**
   - Orchestrates pipeline workflow
   - 2-hour timeout
   - CloudWatch Logs enabled

6. **API Gateway**
   - REST API for chat interface
   - CORS enabled
   - Endpoints: `/chat` (POST), `/health` (GET)

### Data Flow

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
   ↓ Extracts entities/relationships with Bedrock
   ↓ Saves to S3: knowledge_graphs/

4. Neptune Loader Lambda
   ↓ Reads knowledge graphs
   ↓ Loads into Neptune via Gremlin

5. Chat Handler Lambda
   ↓ Receives questions via API Gateway
   ↓ Queries Neptune
   ↓ Generates answers with Bedrock
```

## Pipeline Execution

### Start Pipeline

After deployment, get the State Machine ARN from outputs:

```bash
# From CDK outputs
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

### Input Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `start_date` | Start date for newspaper search | `"1815-08-01"` |
| `end_date` | End date for newspaper search | `"1815-08-31"` |
| `max_pages` | Maximum API pages to fetch | `10` |

### Monitor Execution

1. **Step Functions Console**
   - Go to AWS Console → Step Functions
   - Select state machine
   - View execution graph and logs

2. **CloudWatch Logs**
   - Log groups: `/aws/lambda/${project}-*`
   - View Lambda execution logs

3. **S3 Bucket**
   - Check `images/`, `extracted/`, `knowledge_graphs/` folders
   - Verify data is being created

## Monitoring

### CloudWatch Dashboards

Create custom dashboard:
```bash
aws cloudwatch put-dashboard \
  --dashboard-name chronicling-america-pipeline \
  --dashboard-body file://dashboard.json
```

### Key Metrics

- **Lambda Invocations**: Count of function executions
- **Lambda Duration**: Execution time
- **Lambda Errors**: Failed invocations
- **Step Functions Executions**: Pipeline runs
- **Neptune Connections**: Active connections
- **API Gateway Requests**: Chat API usage

### Alarms

Set up alarms for:
- Lambda errors > 5 in 5 minutes
- Step Functions failed executions
- Neptune CPU > 80%
- API Gateway 5xx errors

## Troubleshooting

### Common Issues

#### 1. Lambda Timeout

**Error**: Task timed out after 15 minutes

**Solution**: 
- Reduce `max_pages` in input
- Process in smaller batches
- Increase Lambda timeout in CDK stack

#### 2. Bedrock Access Denied

**Error**: AccessDeniedException when invoking model

**Solution**:
- Enable model access in Bedrock console
- Check IAM permissions for `bedrock:InvokeModel`
- Verify model ID is correct

#### 3. Neptune Connection Failed

**Error**: Cannot connect to Neptune

**Solution**:
- Verify Lambda is in correct VPC
- Check security group rules
- Ensure Neptune is in same VPC
- Wait for Neptune cluster to be available

#### 4. Docker Build Failed

**Error**: Cannot build Lambda Docker image

**Solution**:
- Ensure Docker is running
- Check Dockerfile syntax
- Verify requirements.txt dependencies
- Enable privileged mode in CodeBuild

#### 5. S3 Access Denied

**Error**: Access denied when writing to S3

**Solution**:
- Check Lambda execution role permissions
- Verify bucket name is correct
- Ensure bucket exists in same region

### Debug Commands

```bash
# Check Lambda logs
aws logs tail /aws/lambda/chronicling-america-pipeline-image-collector --follow

# Check Step Functions execution
aws stepfunctions describe-execution \
  --execution-arn <EXECUTION_ARN>

# Check Neptune status
aws neptune describe-db-clusters \
  --db-cluster-identifier chronicling-america-pipeline-neptune-cluster

# Test API Gateway
curl -X POST https://YOUR-API-ID.execute-api.us-west-2.amazonaws.com/prod/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"Who are the people mentioned?"}'
```

## Cost Estimation

### Monthly Costs (100 newspapers/month)

| Service | Usage | Cost |
|---------|-------|------|
| **Lambda** | 5 functions × 20 invocations | ~$0.50 |
| **Bedrock** | 100 images + 100 entity extractions | ~$2.40 |
| **Neptune** | db.t3.medium, 730 hours | ~$73.00 |
| **S3** | 1GB storage, 1000 requests | ~$0.05 |
| **Step Functions** | 20 executions | ~$0.50 |
| **API Gateway** | 1000 requests | ~$0.01 |
| **VPC** | NAT Gateway, 730 hours | ~$32.00 |
| **CloudWatch** | Logs, 1GB | ~$0.50 |
| **Total** | | **~$109/month** |

### Cost Optimization

1. **Use Neptune Serverless** (when available)
   - Pay per query instead of per hour
   - Estimated savings: 50-70%

2. **Stop Neptune when not in use**
   ```bash
   aws neptune stop-db-cluster \
     --db-cluster-identifier chronicling-america-pipeline-neptune-cluster
   ```

3. **Use cheaper Bedrock model**
   - Claude 3 Haiku: 90% cheaper
   - Trade-off: Lower accuracy

4. **Reduce Lambda memory**
   - Test with 512MB instead of 2GB
   - Adjust based on performance

5. **Use S3 Intelligent-Tiering**
   - Automatically moves data to cheaper storage

## Next Steps

1. **Test the Pipeline**
   ```bash
   # Start with small dataset
   aws stepfunctions start-execution \
     --state-machine-arn $STATE_MACHINE_ARN \
     --input '{"start_date":"1815-08-01","end_date":"1815-08-01","max_pages":1}'
   ```

2. **Query Neptune**
   ```bash
   curl -X POST $CHAT_ENDPOINT \
     -H 'Content-Type: application/json' \
     -d '{"question":"What newspapers are in the database?"}'
   ```

3. **Build Frontend**
   - Create React app
   - Connect to API Gateway
   - Display chat interface

4. **Customize Extraction**
   - Modify Lambda function prompts
   - Add custom entity types
   - Adjust confidence thresholds

5. **Scale Up**
   - Process larger date ranges
   - Increase `max_pages`
   - Add more Lambda concurrency

## Support

For issues:
1. Check CloudWatch Logs
2. Review Step Functions execution graph
3. Verify IAM permissions
4. Test individual Lambda functions
5. Check AWS service quotas

## Cleanup

To destroy all resources:

```bash
./deploy.sh
# Choose "destroy" when prompted

# Or manually:
cdk destroy ChroniclingAmericaStack --force
```

**Note**: S3 bucket is retained by default. Delete manually if needed:
```bash
aws s3 rb s3://YOUR-BUCKET-NAME --force
```

---

**Deployment complete!** 🎉

Monitor your pipeline in the AWS Console and start extracting historical newspaper data.
