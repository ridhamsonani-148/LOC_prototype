# LOC_prototype

## GraphRAG with Amazon Bedrock Knowledge Bases

This project uses **Amazon Bedrock Knowledge Bases** for automatic entity extraction and relationship discovery from historical newspaper documents (1815-1820).

### Architecture

```
LOC API → Image Collector → PDF Converter → Bedrock Data Automation → Neptune
                                                                           ↓
                                                              Bedrock Knowledge Base
                                                              (Auto Entity Extraction)
                                                                           ↓
                                                                    Chat Interface
```

### Key Features

- **No Manual Entity Extraction**: Bedrock Knowledge Base automatically extracts entities (people, places, organizations, events) from documents
- **GraphRAG**: Combines graph database (Neptune) with retrieval-augmented generation
- **Simplified Pipeline**: Removed entity-extractor Lambda - entities are extracted automatically by Bedrock KB

### Setup Instructions (Fully Automated!)

1. **Deploy Infrastructure** (Creates everything including Bedrock Knowledge Base)
   ```bash
   cd backend
   ./deploy.sh
   ```
   
   This automatically creates:
   - ✅ VPC and Neptune cluster
   - ✅ Lambda functions
   - ✅ Step Functions pipeline
   - ✅ Bedrock Knowledge Base (connected to Neptune)
   - ✅ API Gateway for chat interface

2. **Run Pipeline to Load Documents**
   ```bash
   aws stepfunctions start-execution \
     --state-machine-arn <your-state-machine-arn> \
     --input '{"start_date": "1815-08-01", "end_date": "1815-08-31", "max_pages": 10}'
   ```
   
   Wait for pipeline to complete (check AWS Console → Step Functions)

3. **Sync Knowledge Base** (One-time after first data load)
   ```bash
   # Get Knowledge Base ID from CDK output
   KB_ID=$(aws cloudformation describe-stacks \
     --stack-name ChroniclingAmericaStack \
     --query 'Stacks[0].Outputs[?OutputKey==`KnowledgeBaseId`].OutputValue' \
     --output text)
   
   # Get Data Source ID
   DS_ID=$(aws cloudformation describe-stacks \
     --stack-name ChroniclingAmericaStack \
     --query 'Stacks[0].Outputs[?OutputKey==`KnowledgeBaseDataSourceId`].OutputValue' \
     --output text)
   
   # Start ingestion job (sync)
   aws bedrock-agent start-ingestion-job \
     --knowledge-base-id $KB_ID \
     --data-source-id $DS_ID
   ```
   
   Or sync via AWS Console:
   - Go to Amazon Bedrock → Knowledge Bases
   - Select your knowledge base
   - Click **Sync** button

4. **Test Chat Interface**
   ```bash
   curl -X POST <api-gateway-url>/chat \
     -H "Content-Type: application/json" \
     -d '{"question": "What events happened in Providence in 1815?"}'
   ```

That's it! No manual configuration needed.

### How It Works

1. **Document Loading**: Pipeline extracts text from newspaper images and stores in Neptune as `Document` vertices with `document_text` property
2. **Automatic Entity Extraction**: Bedrock Knowledge Base syncs from Neptune and automatically extracts:
   - Entities (people, places, organizations, events)
   - Relationships between entities
   - Semantic embeddings for search
3. **GraphRAG Queries**: Chat interface uses Bedrock KB's `retrieve_and_generate` API to:
   - Find relevant documents
   - Extract entities and relationships
   - Generate natural language answers

### Benefits

- ✅ **Simplified Pipeline**: No need for separate entity extraction Lambda
- ✅ **Better Accuracy**: Bedrock KB uses advanced NLP models for entity extraction
- ✅ **Automatic Updates**: Entities are re-extracted when documents change
- ✅ **Scalable**: Handles large document collections efficiently
- ✅ **Cost Effective**: Pay only for what you use

### References

- [Build GraphRAG applications using Amazon Bedrock Knowledge Bases](https://aws.amazon.com/blogs/machine-learning/build-graphrag-applications-using-amazon-bedrock-knowledge-bases/)
- [Amazon Bedrock Knowledge Bases Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)