"""
Chat Handler Lambda Function
Provides chat interface using Bedrock Knowledge Base with GraphRAG
Queries documents stored in Neptune with automatic entity extraction
"""

import json
import os
import time
import boto3
from botocore.exceptions import ClientError

bedrock_runtime = boto3.client('bedrock-runtime')
bedrock_agent_runtime = boto3.client('bedrock-agent-runtime')

# Neptune Analytics is accessed through Knowledge Base, not directly
NEPTUNE_ENDPOINT = os.environ.get('NEPTUNE_ENDPOINT', 'N/A')  # Not used with KB
NEPTUNE_PORT = os.environ.get('NEPTUNE_PORT', '8182')
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'anthropic.claude-3-5-sonnet-20241022-v2:0')
KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID', '')  # Set this after creating KB

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
                'neptune_endpoint': NEPTUNE_ENDPOINT
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
        
        # Use Bedrock Knowledge Base for GraphRAG
        if KNOWLEDGE_BASE_ID:
            response = query_knowledge_base(question)
        else:
            # KB not configured yet
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


def invoke_bedrock_with_retry(prompt: str, max_retries: int = 5) -> str:
    """Invoke Bedrock with exponential backoff retry logic"""
    
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 500,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }
        ]
    }
    
    for attempt in range(max_retries):
        try:
            response = bedrock_runtime.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=json.dumps(request_body)
            )
            
            response_body = json.loads(response['body'].read())
            return response_body['content'][0]['text'].strip()
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            
            if error_code == 'ThrottlingException':
                if attempt < max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                    wait_time = 2 ** attempt
                    print(f"Throttled, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                    time.sleep(wait_time)
                    continue
                else:
                    raise Exception("Too many requests. Please wait a moment and try again.")
            else:
                # For other errors, raise immediately
                raise
    
    raise Exception("Max retries exceeded")


def query_knowledge_base(question: str) -> dict:
    """
    Query Bedrock Knowledge Base with GraphRAG
    Automatically extracts entities and relationships from documents
    """
    print(f"Querying Knowledge Base: {KNOWLEDGE_BASE_ID}")
    
    # AWS_REGION is automatically available in Lambda environment
    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    
    try:
        response = bedrock_agent_runtime.retrieve_and_generate(
            input={
                'text': question
            },
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': KNOWLEDGE_BASE_ID,
                    'modelArn': f'arn:aws:bedrock:{aws_region}::foundation-model/{BEDROCK_MODEL_ID}',
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
        # Fallback to direct answer
        return {
            'answer': f"I encountered an error querying the knowledge base: {str(e)}",
            'sources': [],
            'entities': []
        }


def answer_question_direct_neptune(question: str) -> dict:
    """
    Fallback: Direct Neptune query without Knowledge Base
    Used when KNOWLEDGE_BASE_ID is not configured
    """
    from gremlin_python.driver import client, serializer
    
    # Connect to Neptune
    connection_url = f'wss://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/gremlin'
    print(f"Connecting to Neptune: {connection_url}")
    
    neptune_client = client.Client(
        connection_url,
        'g',
        message_serializer=serializer.GraphSONSerializersV2d0()
    )
    
    # Simple query to get documents
    query = "g.V().hasLabel('Document').limit(10).valueMap(true)"
    
    try:
        results = neptune_client.submit(query).all().result()
        
        # Format results for answer
        documents = []
        for result in results:
            if isinstance(result, dict):
                doc_text = result.get('document_text', [''])[0] if 'document_text' in result else ''
                documents.append(doc_text[:500])  # First 500 chars
        
        # Use Claude to answer based on documents
        if documents:
            prompt = f"""Based on these historical newspaper documents from 1815-1820:

{chr(10).join(documents)}

Answer this question: {question}

Provide a helpful, concise answer based on the documents."""
            
            answer = invoke_bedrock_with_retry(prompt)
        else:
            answer = "No documents found in the database. Please run the pipeline to load documents first."
        
        neptune_client.close()
        
        return {
            'answer': answer,
            'sources': [{'document_id': f'doc_{i}', 'content': doc[:200]} for i, doc in enumerate(documents)],
            'entities': []
        }
        
    except Exception as e:
        print(f"Error querying Neptune: {e}")
        return {
            'answer': f"Error querying database: {str(e)}",
            'sources': [],
            'entities': []
        }



