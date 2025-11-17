# Architecture Diagram

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         AWS Cloud                                        │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │                    Step Functions State Machine                 │   │
│  │                                                                  │   │
│  │  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   │   │
│  │  │  Image   │ → │   Data   │ → │  Entity  │ → │ Neptune  │   │   │
│  │  │Collector │   │Extractor │   │Extractor │   │  Loader  │   │   │
│  │  └──────────┘   └──────────┘   └──────────┘   └──────────┘   │   │
│  │       ↓              ↓              ↓              ↓           │   │
│  └───────┼──────────────┼──────────────┼──────────────┼───────────┘   │
│          │              │              │              │                │
│          ↓              ↓              ↓              ↓                │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                        S3 Bucket                              │   │
│  │  ┌─────────┐  ┌──────────┐  ┌────────────────┐              │   │
│  │  │ images/ │  │extracted/│  │knowledge_graphs/│              │   │
│  │  └─────────┘  └──────────┘  └────────────────┘              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    VPC (2 AZs)                                │   │
│  │                                                                │   │
│  │  ┌─────────────────┐         ┌─────────────────┐            │   │
│  │  │ Private Subnet  │         │ Isolated Subnet │            │   │
│  │  │                 │         │                 │            │   │
│  │  │  ┌──────────┐  │         │  ┌──────────┐  │            │   │
│  │  │  │ Lambda   │  │         │  │ Neptune  │  │            │   │
│  │  │  │Functions │  │         │  │ Cluster  │  │            │   │
│  │  │  └──────────┘  │         │  └──────────┘  │            │   │
│  │  └─────────────────┘         └─────────────────┘            │   │
│  │                                                                │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    API Gateway                                │   │
│  │                                                                │   │
│  │  POST /chat  ──→  Chat Handler Lambda  ──→  Neptune          │   │
│  │  GET /health ──→  Chat Handler Lambda                         │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Amazon Bedrock                             │   │
│  │              (Claude 3.5 Sonnet v2)                           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
         ↑                                              ↓
         │                                              │
    ┌────────┐                                    ┌─────────┐
    │  User  │                                    │Frontend │
    │(CLI/API)│                                   │  (Web)  │
    └────────┘                                    └─────────┘
```

## Detailed Data Flow

### Pipeline Execution Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. Image Collection                                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  User Input                                                          │
│  {                                                                   │
│    "start_date": "1815-08-01",                                      │
│    "end_date": "1815-08-31",                                        │
│    "max_pages": 10                                                  │
│  }                                                                   │
│         ↓                                                            │
│  Step Functions triggers Image Collector Lambda                     │
│         ↓                                                            │
│  Lambda calls Chronicling America API                               │
│  https://chroniclingamerica.loc.gov/search/pages/results/           │
│         ↓                                                            │
│  Fetches newspaper page metadata                                    │
│  - Page ID                                                           │
│  - Title                                                             │
│  - Date                                                              │
│  - Image URL                                                         │
│         ↓                                                            │
│  Deduplicates results                                               │
│         ↓                                                            │
│  Saves to S3: images/image_list_TIMESTAMP.json                      │
│         ↓                                                            │
│  Returns: {                                                          │
│    "image_count": 50,                                               │
│    "s3_key": "images/image_list_20250117_120000.json",             │
│    "images": [...]                                                  │
│  }                                                                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ 2. Data Extraction                                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Input from previous step                                            │
│  {                                                                   │
│    "s3_key": "images/image_list_20250117_120000.json",             │
│    "images": [...]                                                  │
│  }                                                                   │
│         ↓                                                            │
│  Data Extractor Lambda triggered                                    │
│         ↓                                                            │
│  For each image:                                                     │
│    1. Download image from URL                                        │
│    2. Resize to max 2048x2048                                       │
│    3. Convert to JPEG                                               │
│    4. Encode to base64                                              │
│         ↓                                                            │
│    5. Call Bedrock with image + prompt                              │
│       Model: Claude 3.5 Sonnet v2                                   │
│       Prompt: "Extract newspaper data..."                           │
│         ↓                                                            │
│    6. Parse JSON response                                           │
│       {                                                              │
│         "newspaper_name": "...",                                    │
│         "publication_date": "...",                                  │
│         "headlines": [...],                                         │
│         "articles": [...],                                          │
│         "people_mentioned": [...],                                  │
│         "locations_mentioned": [...]                                │
│       }                                                              │
│         ↓                                                            │
│  Saves to S3: extracted/extraction_results_TIMESTAMP.json           │
│         ↓                                                            │
│  Returns: {                                                          │
│    "processed_count": 50,                                           │
│    "s3_key": "extracted/extraction_results_20250117_120500.json",  │
│    "results": [...]                                                 │
│  }                                                                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ 3. Entity Extraction                                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Input from previous step                                            │
│  {                                                                   │
│    "s3_key": "extracted/extraction_results_20250117_120500.json",  │
│    "results": [...]                                                 │
│  }                                                                   │
│         ↓                                                            │
│  Entity Extractor Lambda triggered                                  │
│         ↓                                                            │
│  For each extraction result:                                         │
│    1. Build text from extraction data                               │
│    2. Call Bedrock with text + entity extraction prompt             │
│       Model: Claude 3.5 Sonnet v2                                   │
│       Prompt: "Extract entities and relationships..."               │
│         ↓                                                            │
│    3. Parse JSON response                                           │
│       {                                                              │
│         "entities": [                                               │
│           {                                                          │
│             "id": "person_1",                                       │
│             "type": "PERSON",                                       │
│             "name": "John Smith",                                   │
│             "confidence": 0.95                                      │
│           }                                                          │
│         ],                                                           │
│         "relationships": [                                          │
│           {                                                          │
│             "source": "person_1",                                   │
│             "target": "location_1",                                 │
│             "type": "LOCATED_IN",                                   │
│             "confidence": 0.90                                      │
│           }                                                          │
│         ]                                                            │
│       }                                                              │
│         ↓                                                            │
│  Saves to S3: knowledge_graphs/kg_TIMESTAMP.json                    │
│         ↓                                                            │
│  Returns: {                                                          │
│    "kg_count": 50,                                                  │
│    "s3_key": "knowledge_graphs/kg_20250117_121000.json",           │
│    "knowledge_graphs": [...]                                        │
│  }                                                                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ 4. Neptune Loading                                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Input from previous step                                            │
│  {                                                                   │
│    "s3_key": "knowledge_graphs/kg_20250117_121000.json",           │
│    "knowledge_graphs": [...]                                        │
│  }                                                                   │
│         ↓                                                            │
│  Neptune Loader Lambda triggered (in VPC)                           │
│         ↓                                                            │
│  Connect to Neptune via WebSocket                                   │
│  wss://neptune-endpoint:8182/gremlin                                │
│         ↓                                                            │
│  For each knowledge graph:                                           │
│    For each entity:                                                  │
│      1. Generate Gremlin query                                       │
│         g.addV('PERSON')                                            │
│          .property('id', 'person_1')                                │
│          .property('name', 'John Smith')                            │
│          .property('confidence', 0.95)                              │
│         ↓                                                            │
│      2. Execute query on Neptune                                     │
│         ↓                                                            │
│    For each relationship:                                            │
│      1. Generate Gremlin query                                       │
│         g.V().has('id', 'person_1').as('src')                       │
│          .V().has('id', 'location_1').as('tgt')                     │
│          .addE('LOCATED_IN').from('src').to('tgt')                  │
│          .property('confidence', 0.90)                              │
│         ↓                                                            │
│      2. Execute query on Neptune                                     │
│         ↓                                                            │
│  Returns: {                                                          │
│    "entities_loaded": 250,                                          │
│    "relationships_loaded": 180,                                     │
│    "kg_count": 50                                                   │
│  }                                                                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Chat API Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│ Chat Query Flow                                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  User sends question                                                 │
│  POST /chat                                                          │
│  {                                                                   │
│    "question": "Who are the people mentioned in Providence?"        │
│  }                                                                   │
│         ↓                                                            │
│  API Gateway receives request                                        │
│         ↓                                                            │
│  Chat Handler Lambda triggered (in VPC)                             │
│         ↓                                                            │
│  1. Generate Gremlin query using Bedrock                            │
│     Prompt: "Convert question to Gremlin query..."                  │
│     Response: "g.V().hasLabel('PERSON')                             │
│                 .out('LOCATED_IN')                                  │
│                 .has('name', containing('Providence'))              │
│                 .in('LOCATED_IN')                                   │
│                 .values('name').dedup()"                            │
│         ↓                                                            │
│  2. Execute query on Neptune                                         │
│     Connect: wss://neptune-endpoint:8182/gremlin                    │
│     Execute: [generated query]                                       │
│     Results: ["John Smith", "Mary Johnson", ...]                    │
│         ↓                                                            │
│  3. Generate natural language answer using Bedrock                  │
│     Prompt: "Based on these results, answer the question..."        │
│     Response: "I found several people mentioned in Providence:      │
│                John Smith, Mary Johnson, and Thomas Brown.          │
│                They were mentioned in newspapers from 1815."        │
│         ↓                                                            │
│  4. Return response                                                  │
│     {                                                                │
│       "question": "Who are the people mentioned in Providence?",    │
│       "answer": "I found several people...",                        │
│       "query": "g.V().hasLabel('PERSON')...",                       │
│       "result_count": 3                                             │
│     }                                                                │
│         ↓                                                            │
│  API Gateway returns to user                                         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Network Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                              VPC                                     │
│                         10.0.0.0/16                                  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │ Availability Zone A                                         │   │
│  │                                                              │   │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────┐ │   │
│  │  │ Public Subnet    │  │ Private Subnet   │  │ Isolated │ │   │
│  │  │ 10.0.0.0/24      │  │ 10.0.2.0/24      │  │ Subnet   │ │   │
│  │  │                  │  │                  │  │10.0.4.0/28│ │   │
│  │  │ ┌──────────────┐ │  │ ┌──────────────┐ │  │┌────────┐│ │   │
│  │  │ │ NAT Gateway  │ │  │ │   Lambda     │ │  ││Neptune ││ │   │
│  │  │ │              │ │  │ │  Functions   │ │  ││Instance││ │   │
│  │  │ └──────────────┘ │  │ └──────────────┘ │  │└────────┘│ │   │
│  │  └──────────────────┘  └──────────────────┘  └──────────┘ │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │ Availability Zone B                                         │   │
│  │                                                              │   │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────┐ │   │
│  │  │ Public Subnet    │  │ Private Subnet   │  │ Isolated │ │   │
│  │  │ 10.0.1.0/24      │  │ 10.0.3.0/24      │  │ Subnet   │ │   │
│  │  │                  │  │                  │  │10.0.5.0/28│ │   │
│  │  │                  │  │ ┌──────────────┐ │  │┌────────┐│ │   │
│  │  │                  │  │ │   Lambda     │ │  ││Neptune ││ │   │
│  │  │                  │  │ │  Functions   │ │  ││Instance││ │   │
│  │  │                  │  │ └──────────────┘ │  │└────────┘│ │   │
│  │  └──────────────────┘  └──────────────────┘  └──────────┘ │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │ Security Group: Neptune                                     │   │
│  │ Inbound: Port 8182 from Lambda Security Group              │   │
│  │ Outbound: All                                               │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Interactions

```
┌──────────────┐
│   User/CLI   │
└──────┬───────┘
       │
       │ 1. Start Execution
       ↓
┌──────────────────────┐
│  Step Functions      │
│  State Machine       │
└──────┬───────────────┘
       │
       │ 2. Invoke Lambda
       ↓
┌──────────────────────┐      ┌──────────────────────┐
│ Image Collector      │─────→│ Chronicling America  │
│ Lambda               │←─────│ API                  │
└──────┬───────────────┘      └──────────────────────┘
       │
       │ 3. Save to S3
       ↓
┌──────────────────────┐
│  S3 Bucket           │
│  images/             │
└──────┬───────────────┘
       │
       │ 4. Trigger Next
       ↓
┌──────────────────────┐      ┌──────────────────────┐
│ Data Extractor       │─────→│ Amazon Bedrock       │
│ Lambda               │←─────│ (Claude 3.5 Sonnet)  │
└──────┬───────────────┘      └──────────────────────┘
       │
       │ 5. Save to S3
       ↓
┌──────────────────────┐
│  S3 Bucket           │
│  extracted/          │
└──────┬───────────────┘
       │
       │ 6. Trigger Next
       ↓
┌──────────────────────┐      ┌──────────────────────┐
│ Entity Extractor     │─────→│ Amazon Bedrock       │
│ Lambda               │←─────│ (Claude 3.5 Sonnet)  │
└──────┬───────────────┘      └──────────────────────┘
       │
       │ 7. Save to S3
       ↓
┌──────────────────────┐
│  S3 Bucket           │
│  knowledge_graphs/   │
└──────┬───────────────┘
       │
       │ 8. Trigger Next
       ↓
┌──────────────────────┐      ┌──────────────────────┐
│ Neptune Loader       │─────→│ Amazon Neptune       │
│ Lambda (in VPC)      │←─────│ Graph Database       │
└──────────────────────┘      └──────────────────────┘


┌──────────────┐
│  Frontend    │
└──────┬───────┘
       │
       │ 9. POST /chat
       ↓
┌──────────────────────┐
│  API Gateway         │
└──────┬───────────────┘
       │
       │ 10. Invoke Lambda
       ↓
┌──────────────────────┐      ┌──────────────────────┐
│ Chat Handler         │─────→│ Amazon Bedrock       │
│ Lambda (in VPC)      │←─────│ (Query Generation)   │
└──────┬───────────────┘      └──────────────────────┘
       │
       │ 11. Execute Query
       ↓
┌──────────────────────┐
│ Amazon Neptune       │
│ Graph Database       │
└──────┬───────────────┘
       │
       │ 12. Return Results
       ↓
┌──────────────────────┐      ┌──────────────────────┐
│ Chat Handler         │─────→│ Amazon Bedrock       │
│ Lambda               │←─────│ (Answer Generation)  │
└──────┬───────────────┘      └──────────────────────┘
       │
       │ 13. Return Answer
       ↓
┌──────────────────────┐
│  API Gateway         │
└──────┬───────────────┘
       │
       │ 14. Response
       ↓
┌──────────────┐
│  Frontend    │
└──────────────┘
```

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Developer Machine                            │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  ./deploy.sh                                                │   │
│  └────────────┬───────────────────────────────────────────────┘   │
│               │                                                      │
└───────────────┼──────────────────────────────────────────────────────┘
                │
                │ 1. Create CodeBuild Project
                ↓
┌─────────────────────────────────────────────────────────────────────┐
│                         AWS CodeBuild                                │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  buildspec.yml                                              │   │
│  │                                                              │   │
│  │  1. Install Node.js 20                                      │   │
│  │  2. Install AWS CDK                                         │   │
│  │  3. npm install                                             │   │
│  │  4. npm run build (TypeScript → JavaScript)                │   │
│  │  5. cdk bootstrap                                           │   │
│  │  6. cdk deploy                                              │   │
│  └────────────┬───────────────────────────────────────────────┘   │
│               │                                                      │
└───────────────┼──────────────────────────────────────────────────────┘
                │
                │ 2. Deploy CloudFormation Stack
                ↓
┌─────────────────────────────────────────────────────────────────────┐
│                      AWS CloudFormation                              │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  ChroniclingAmericaStack                                    │   │
│  │                                                              │   │
│  │  1. Create VPC                                              │   │
│  │  2. Create Security Groups                                  │   │
│  │  3. Create Neptune Cluster                                  │   │
│  │  4. Build Docker Images                                     │   │
│  │  5. Push to ECR                                             │   │
│  │  6. Create Lambda Functions                                 │   │
│  │  7. Create Step Functions                                   │   │
│  │  8. Create API Gateway                                      │   │
│  │  9. Create S3 Bucket                                        │   │
│  │  10. Create IAM Roles                                       │   │
│  └────────────┬───────────────────────────────────────────────┘   │
│               │                                                      │
└───────────────┼──────────────────────────────────────────────────────┘
                │
                │ 3. Output Stack Outputs
                ↓
┌─────────────────────────────────────────────────────────────────────┐
│                         Stack Outputs                                │
│                                                                      │
│  - DataBucketName                                                   │
│  - StateMachineArn                                                  │
│  - NeptuneEndpoint                                                  │
│  - APIGatewayURL                                                    │
│  - ChatEndpoint                                                     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Monitoring Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Amazon CloudWatch                               │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Log Groups                                                 │   │
│  │                                                              │   │
│  │  /aws/lambda/chronicling-america-pipeline-image-collector  │   │
│  │  /aws/lambda/chronicling-america-pipeline-data-extractor   │   │
│  │  /aws/lambda/chronicling-america-pipeline-entity-extractor │   │
│  │  /aws/lambda/chronicling-america-pipeline-neptune-loader   │   │
│  │  /aws/lambda/chronicling-america-pipeline-chat-handler     │   │
│  │  /aws/stepfunctions/chronicling-america-pipeline           │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Metrics                                                    │   │
│  │                                                              │   │
│  │  - Lambda Invocations                                       │   │
│  │  - Lambda Duration                                          │   │
│  │  - Lambda Errors                                            │   │
│  │  - Step Functions Executions                                │   │
│  │  - API Gateway Requests                                     │   │
│  │  - Neptune CPU/Memory                                       │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Alarms                                                     │   │
│  │                                                              │   │
│  │  - Lambda Errors > 5 in 5 minutes                           │   │
│  │  - Step Functions Failed Executions                         │   │
│  │  - Neptune CPU > 80%                                        │   │
│  │  - API Gateway 5xx Errors                                   │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

This architecture provides a complete, scalable, and maintainable solution for extracting and analyzing historical newspaper data using AWS services.
