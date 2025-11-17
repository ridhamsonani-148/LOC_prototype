# Chronicling America - Frontend Chat UI

Simple web interface to chat with your historical newspaper knowledge graph.

## Quick Start

### 1. Deploy Backend First
```bash
cd backend
./deploy.sh
```

### 2. Get Your API URL
After deployment, copy the `ChatEndpoint` URL from the output.

### 3. Open the Web UI
Simply open `index.html` in your browser:
- **Windows**: Double-click `index.html`
- **Mac/Linux**: `open index.html`
- **Or**: Drag the file into your browser

### 4. Configure API
Paste your API endpoint URL in the configuration field at the top.

### 5. Start Chatting!
Ask questions like:
- "What newspapers are in the database?"
- "Who are the people mentioned?"
- "What locations are mentioned?"
- "Tell me about events in August 1815"

## Features

✅ **No server required** - Pure HTML/CSS/JavaScript  
✅ **Auto-saves API URL** - Remembers your endpoint  
✅ **Suggestion chips** - Quick question templates  
✅ **Beautiful UI** - Modern, responsive design  
✅ **Real-time status** - Connection indicator  
✅ **Error handling** - Clear error messages  

## Testing Backend

Before using the UI, test your backend:

```bash
# Test complete pipeline
cd backend
python test_backend.py

# Or use bash script
./test-pipeline.sh

# Quick API test
./test-api.sh
```

## Troubleshooting

### API Not Responding
- Check your API URL is correct
- Verify backend is deployed: `aws cloudformation describe-stacks --stack-name ChroniclingAmericaStack`
- Check Lambda logs in CloudWatch

### No Data
- Run the pipeline first: `python test_backend.py`
- Wait for Step Functions execution to complete (~10 minutes)

### CORS Errors
- API Gateway CORS is configured in CDK
- If issues persist, check API Gateway settings in AWS Console

## Architecture

```
Browser → API Gateway → Lambda (Chat Handler) → Neptune → Response
```

The chat handler:
1. Converts your question to Gremlin query (using Bedrock)
2. Queries Neptune graph database
3. Generates natural language answer (using Bedrock)
4. Returns formatted response

## Customization

Edit `index.html` to customize:
- Colors and styling (CSS section)
- Suggestion questions
- Message formatting
- API request/response handling
