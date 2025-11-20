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
        
        # Generate query and answer in single Bedrock call
        response = answer_question_single_call(question)
        
        gremlin_query = response['query']
        answer = response['answer']
        results = response['results']
        
        print(f"Generated query: {gremlin_query}")
        print(f"Query results: {len(results)} items")
        
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


def answer_question_single_call(question: str) -> dict:
    """Answer question using Claude - generates query and executes it"""
    
    prompt = f"""You are a Neptune graph database expert for historical newspapers (1815-1820).

User Question: {question}

Graph Schema:
Vertices (Nodes):
- PERSON: name, confidence, context
- LOCATION: name, confidence, type (city/state/country)
- ORGANIZATION: name, confidence, type (business/government/military)
- EVENT: name, date, description, confidence
- NEWSPAPER: title, publication_date, location, publisher
- ARTICLE: headline, summary, date, newspaper_id
- ADVERTISEMENT: product, company, price, date

Edges (Relationships):
- MENTIONED_IN: Person/Location/Org → Article/Newspaper
- LOCATED_IN: Person/Org/Event → Location
- WORKS_FOR: Person → Organization
- PARTICIPATED_IN: Person → Event
- PUBLISHED_BY: Article → Newspaper
- ADVERTISED_IN: Advertisement → Newspaper
- RELATED_TO: Any → Any (general relationship)

Common Query Patterns:

1. List entities:
   g.V().hasLabel('PERSON').values('name').dedup().limit(50)

2. Find relationships:
   g.V().hasLabel('PERSON').has('name', 'George Washington').out('MENTIONED_IN').values('title')

3. Filter by property:
   g.V().hasLabel('NEWSPAPER').has('publication_date', containing('1815')).valueMap()

4. Count entities:
   g.V().hasLabel('LOCATION').count()

5. Complex traversal:
   g.V().hasLabel('PERSON').out('LOCATED_IN').has('name', containing('Providence')).in('LOCATED_IN').values('name').dedup()

6. Get full details:
   g.V().hasLabel('EVENT').valueMap(true).limit(10)

7. Find connections:
   g.V().has('name', 'Aaron Burr').both().values('name').dedup()

Now generate a Gremlin query for: {question}

Return ONLY the Gremlin query, no explanation, no markdown, no code blocks."""
    
    # Get query from Bedrock
    query = invoke_bedrock_with_retry(prompt)
    
    # Clean up query
    query = query.replace('```', '').replace('gremlin', '').replace('```python', '').strip()
    
    print(f"Generated query: {query}")
    
    # Execute query on Neptune
    results = execute_neptune_query(query)
    
    print(f"Query returned {len(results)} results")
    
    # Format answer based on results using Claude
    answer = format_answer_from_results(question, results)
    
    return {
        'query': query,
        'answer': answer,
        'results': results
    }


def format_answer_from_results(question: str, results: list) -> str:
    """Format answer from query results using Claude - NO hardcoded conditions"""
    
    if not results:
        return "I couldn't find any information about that in the historical newspapers."
    
    # Let Claude format the answer naturally based on the question and results
    # Limit results to avoid token limits
    results_sample = results[:50] if len(results) > 50 else results
    
    prompt = f"""You are a helpful assistant answering questions about historical newspapers from 1815-1820.

User Question: {question}

Query Results: {json.dumps(results_sample, indent=2)}

Total Results: {len(results)}

Instructions:
1. Answer the user's question naturally and conversationally
2. Use the query results to provide specific information
3. If there are many results, summarize the key findings
4. Be concise but informative
5. Don't mention "query results" or technical details
6. If results are empty or unclear, say you couldn't find that information

Provide a natural, helpful answer:"""
    
    return invoke_bedrock_with_retry(prompt)


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



