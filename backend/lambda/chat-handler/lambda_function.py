"""
Chat Handler Lambda Function
Provides chat interface for querying Neptune knowledge graph
"""

import json
import os
import time
import boto3
from botocore.exceptions import ClientError
from gremlin_python.driver import client, serializer
from gremlin_python.driver.protocol import GremlinServerError

bedrock_runtime = boto3.client('bedrock-runtime')

NEPTUNE_ENDPOINT = os.environ['NEPTUNE_ENDPOINT']
NEPTUNE_PORT = os.environ.get('NEPTUNE_PORT', '8182')
BEDROCK_MODEL_ID = os.environ['BEDROCK_MODEL_ID']

# Global Neptune client (reused across invocations)
neptune_client = None

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
        
        # Generate Gremlin query from question
        gremlin_query = generate_gremlin_query(question)
        print(f"Generated query: {gremlin_query}")
        
        # Execute query on Neptune
        results = execute_neptune_query(gremlin_query)
        print(f"Query results: {len(results)} items")
        
        # Generate natural language response
        answer = generate_answer(question, results)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'question': question,
                'answer': answer,
                'query': gremlin_query,
                'result_count': len(results)
            })
        }
        
    except Exception as e:
        print(f"Error: {e}")
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


def generate_gremlin_query(question: str) -> str:
    """Generate Gremlin query from natural language question"""
    
    prompt = f"""Convert this question into a Gremlin query for a Neptune graph database.

Question: {question}

Graph schema:
- Vertices: PERSON, LOCATION, ORGANIZATION, EVENT, DATE, DOCUMENT
- Edges: MENTIONED_IN, LOCATED_IN, WORKS_FOR, PARTICIPATED_IN
- Properties: id, name, confidence

Return only the Gremlin query, no explanation.

Examples:
Q: "Who are the people mentioned?"
A: g.V().hasLabel('PERSON').values('name').dedup().limit(10)

Q: "What locations are mentioned?"
A: g.V().hasLabel('LOCATION').values('name').dedup().limit(10)

Q: "Find people in Providence"
A: g.V().hasLabel('PERSON').out('LOCATED_IN').has('name', containing('Providence')).in('LOCATED_IN').values('name').dedup()

Now generate query for: {question}"""
    
    query = invoke_bedrock_with_retry(prompt)
    
    # Clean up query
    query = query.replace('```', '').replace('gremlin', '').strip()
    
    return query


def execute_neptune_query(query: str) -> list:
    """Execute Gremlin query on Neptune"""
    global neptune_client
    
    # Connect if not already connected
    if neptune_client is None:
        connection_url = f'wss://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/gremlin'
        print(f"Connecting to Neptune: {connection_url}")
        
        neptune_client = client.Client(
            connection_url,
            'g',
            message_serializer=serializer.GraphSONSerializersV2d0()
        )
    
    # Execute query
    try:
        result = neptune_client.submit(query).all().result()
        return result
    except GremlinServerError as e:
        print(f"Gremlin error: {e}")
        return []


def generate_answer(question: str, results: list) -> str:
    """Generate natural language answer from query results"""
    
    if not results:
        return "I couldn't find any information about that in the historical newspapers."
    
    # Format results
    results_text = "\n".join([str(r) for r in results[:20]])  # Limit to 20 results
    
    prompt = f"""Based on these query results from historical newspapers, answer the question.

Question: {question}

Results:
{results_text}

Provide a clear, concise answer in 2-3 sentences."""
    
    answer = invoke_bedrock_with_retry(prompt)
    
    return answer
