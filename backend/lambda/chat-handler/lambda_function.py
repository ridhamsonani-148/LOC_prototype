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
    """Answer question using single Bedrock call - generates query and executes it"""
    
    prompt = f"""You are a Neptune graph database assistant for historical newspapers.

Question: {question}

Graph schema:
- Vertices: PERSON (name), LOCATION (name), ORGANIZATION (name), EVENT (name), DATE (date), DOCUMENT (document_id, source, publication_date)
- Edges: MENTIONED_IN, LOCATED_IN, WORKS_FOR, PARTICIPATED_IN
- Properties: id, name, confidence, document_id, source, publication_date

Task: Generate a Gremlin query to answer this question.

Examples:
Q: "Who are the people mentioned?"
A: g.V().hasLabel('PERSON').values('name').dedup().limit(20)

Q: "What locations are mentioned?"
A: g.V().hasLabel('LOCATION').values('name').dedup().limit(20)

Q: "What organizations are mentioned?"
A: g.V().hasLabel('ORGANIZATION').values('name').dedup().limit(20)

Q: "Find people in Providence"
A: g.V().hasLabel('PERSON').out('LOCATED_IN').has('name', containing('Providence')).in('LOCATED_IN').values('name').dedup()

Q: "What events are mentioned?"
A: g.V().hasLabel('EVENT').values('name').dedup().limit(20)

Q: "Show me documents from 1815"
A: g.V().hasLabel('DOCUMENT').has('publication_date', containing('1815')).valueMap()

Return ONLY the Gremlin query, no explanation or markdown."""
    
    # Get query from Bedrock
    query = invoke_bedrock_with_retry(prompt)
    
    # Clean up query
    query = query.replace('```', '').replace('gremlin', '').strip()
    
    print(f"Generated query: {query}")
    
    # Execute query on Neptune
    results = execute_neptune_query(query)
    
    print(f"Query returned {len(results)} results")
    
    # Format answer based on results
    answer = format_answer_from_results(question, results)
    
    return {
        'query': query,
        'answer': answer,
        'results': results
    }


def format_answer_from_results(question: str, results: list) -> str:
    """Format answer from query results without additional Bedrock call"""
    
    if not results:
        return "I couldn't find any information about that in the historical newspapers."
    
    # Determine result type and format accordingly
    question_lower = question.lower()
    
    # Handle different query types
    if 'who' in question_lower or 'people' in question_lower or 'person' in question_lower:
        if len(results) == 1:
            return f"I found one person mentioned: {results[0]}."
        else:
            names = ', '.join(str(r) for r in results[:10])
            more = f" and {len(results) - 10} more" if len(results) > 10 else ""
            return f"I found {len(results)} people mentioned in the historical newspapers: {names}{more}."
    
    elif 'where' in question_lower or 'location' in question_lower or 'place' in question_lower:
        if len(results) == 1:
            return f"The newspapers mention this location: {results[0]}."
        else:
            locations = ', '.join(str(r) for r in results[:10])
            more = f" and {len(results) - 10} more" if len(results) > 10 else ""
            return f"The newspapers mention {len(results)} locations: {locations}{more}."
    
    elif 'organization' in question_lower or 'company' in question_lower or 'business' in question_lower:
        if len(results) == 1:
            return f"I found this organization: {results[0]}."
        else:
            orgs = ', '.join(str(r) for r in results[:10])
            more = f" and {len(results) - 10} more" if len(results) > 10 else ""
            return f"I found {len(results)} organizations mentioned: {orgs}{more}."
    
    elif 'event' in question_lower or 'happen' in question_lower:
        if len(results) == 1:
            return f"The newspapers mention this event: {results[0]}."
        else:
            events = ', '.join(str(r) for r in results[:10])
            more = f" and {len(results) - 10} more" if len(results) > 10 else ""
            return f"The newspapers mention {len(results)} events: {events}{more}."
    
    elif 'document' in question_lower or 'newspaper' in question_lower or 'article' in question_lower:
        if isinstance(results[0], dict):
            # Handle document results with metadata
            doc_summaries = []
            for doc in results[:5]:
                source = doc.get('source', ['Unknown'])[0] if isinstance(doc.get('source'), list) else doc.get('source', 'Unknown')
                date = doc.get('publication_date', ['Unknown'])[0] if isinstance(doc.get('publication_date'), list) else doc.get('publication_date', 'Unknown')
                doc_summaries.append(f"{source} ({date})")
            
            more = f" and {len(results) - 5} more" if len(results) > 5 else ""
            return f"I found {len(results)} documents: {'; '.join(doc_summaries)}{more}."
        else:
            return f"I found {len(results)} documents in the database."
    
    else:
        # Generic response for other queries
        if len(results) <= 3:
            items = ', '.join(str(r) for r in results)
            return f"I found: {items}."
        else:
            items = ', '.join(str(r) for r in results[:10])
            more = f" and {len(results) - 10} more" if len(results) > 10 else ""
            return f"I found {len(results)} results: {items}{more}."


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



