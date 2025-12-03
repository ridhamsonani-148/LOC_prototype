"""
Chat Handler Lambda Function
Provides chat interface using Bedrock Knowledge Base with GraphRAG
Uses Neptune Analytics graph through Knowledge Base for entity extraction
"""

import json
import os
import boto3

bedrock_agent_runtime = boto3.client('bedrock-agent-runtime')

BEDROCK_MODEL_ID = os.environ.get('MODEL_ID', 'anthropic.claude-3-5-sonnet-20241022-v2:0')
KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID', '')

def lambda_handler(event, context):
    """
    Handle chat requests
    
    GET /health - Health check
    POST /chat - Chat query
    """
    print(f"Event: {json.dumps(event)}")
    
    http_method = event.get('httpMethod', 'POST')
    
    # Health check
    if http_method == 'GET':
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'status': 'healthy',
                'service': 'chronicling-america-chat',
                'knowledge_base_id': KNOWLEDGE_BASE_ID,
                'model_id': BEDROCK_MODEL_ID
            })
        }
    
    # Chat query
    try:
        body = json.loads(event.get('body', '{}'))
        question = body.get('question', '')
        
        if not question:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Question is required'})
            }
        
        print(f"Question: {question}")
        
        # Check if Knowledge Base is configured
        if not KNOWLEDGE_BASE_ID:
            print("ERROR: KNOWLEDGE_BASE_ID not set")
            return {
                'statusCode': 503,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Knowledge Base not configured yet. Please run the deployment pipeline first.'
                })
            }
        
        # Query Knowledge Base with GraphRAG
        response = query_knowledge_base(question)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'question': question,
                'answer': response['answer'],
                'sources': response.get('sources', []),
                'entities': response.get('entities', [])
            })
        }
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': str(e)})
        }


def query_knowledge_base(question: str) -> dict:
    """
    Query Bedrock Knowledge Base with GraphRAG
    Neptune Analytics graph provides automatic entity extraction and relationships
    """
    print(f"Querying Knowledge Base: {KNOWLEDGE_BASE_ID}")
    
    # AWS_REGION is automatically available in Lambda environment
    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    
    try:
        # Determine if MODEL_ID is an inference profile or foundation model
        # Inference profiles start with region or 'us.' or 'eu.' prefix
        if BEDROCK_MODEL_ID.startswith(('us.', 'eu.', 'global.')):
            # It's an inference profile ARN
            model_arn = f'arn:aws:bedrock:{aws_region}::inference-profile/{BEDROCK_MODEL_ID}'
        else:
            # It's a foundation model ID
            model_arn = f'arn:aws:bedrock:{aws_region}::foundation-model/{BEDROCK_MODEL_ID}'
        
        print(f"Using model ARN: {model_arn}")
        
        response = bedrock_agent_runtime.retrieve_and_generate(
            input={
                'text': question
            },
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': KNOWLEDGE_BASE_ID,
                    'modelArn': model_arn,
                    'retrievalConfiguration': {
                        'vectorSearchConfiguration': {
                            'numberOfResults': 10
                        }
                    }
                }
            }
        )
        
        # Extract answer and sources
        answer = response['output']['text']
        
        # Extract sources (documents that were retrieved)
        sources = []
        if 'citations' in response:
            for citation in response['citations']:
                for reference in citation.get('retrievedReferences', []):
                    sources.append({
                        'document_id': reference.get('location', {}).get('s3Location', {}).get('uri', ''),
                        'content': reference.get('content', {}).get('text', '')[:200] + '...'
                    })
        
        # Extract entities (if available in response metadata)
        entities = []
        if 'metadata' in response:
            entities = response['metadata'].get('entities', [])
        
        print(f"Answer generated with {len(sources)} sources")
        
        return {
            'answer': answer,
            'sources': sources,
            'entities': entities
        }
        
    except Exception as e:
        print(f"Error querying Knowledge Base: {e}")
        return {
            'answer': f"I encountered an error querying the knowledge base: {str(e)}",
            'sources': [],
            'entities': []
        }
