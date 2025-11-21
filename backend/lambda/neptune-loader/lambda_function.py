"""
Neptune Loader Lambda Function
Loads documents into Amazon Neptune for GraphRAG with Bedrock Knowledge Bases
Stores full document text for automatic entity extraction by Bedrock KB
"""

import json
import os
import boto3
from gremlin_python.driver import client, serializer
from gremlin_python.driver.protocol import GremlinServerError
from datetime import datetime

s3_client = boto3.client('s3')

DATA_BUCKET = os.environ['DATA_BUCKET']
NEPTUNE_ENDPOINT = os.environ['NEPTUNE_ENDPOINT']
NEPTUNE_PORT = os.environ.get('NEPTUNE_PORT', '8182')

def lambda_handler(event, context):
    """
    Load documents into Neptune for GraphRAG
    
    Event format:
    {
        "bucket": "bucket-name",
        "s3_key": "extracted/extraction_results_xxx.json",
        "results": [...]  # Optional: direct extraction results
    }
    
    Creates Document vertices with full text content.
    Bedrock Knowledge Base will automatically extract entities and relationships.
    """
    print(f"Event: {json.dumps(event)}")
    
    # Get extraction results
    if 'results' in event and event['results']:
        results = event['results']
    else:
        s3_key = event.get('s3_key')
        bucket = event.get('bucket', DATA_BUCKET)
        
        if not s3_key:
            error_msg = f"Missing s3_key in event. Event keys: {list(event.keys())}"
            print(f"ERROR: {error_msg}")
            return {
                'statusCode': 400,
                'error': error_msg
            }
        
        print(f"Reading extracted data from s3://{bucket}/{s3_key}")
        response = s3_client.get_object(Bucket=bucket, Key=s3_key)
        data = json.loads(response['Body'].read().decode('utf-8'))
        
        # Handle different data formats
        if isinstance(data, dict):
            results = []
            
            # Extract text from Bedrock Data Automation format
            if 'document' in data and isinstance(data['document'], dict):
                doc = data['document']
                if 'text' in doc:
                    results.append({
                        'text': doc['text'],
                        'metadata': data.get('metadata', {})
                    })
            
            # Extract text from pages
            if 'pages' in data and isinstance(data['pages'], list):
                for i, page in enumerate(data['pages']):
                    if isinstance(page, dict) and 'text' in page:
                        results.append({
                            'text': page['text'],
                            'page_number': i + 1,
                            'metadata': data.get('metadata', {})
                        })
            
            # Extract from text_lines
            if not results and 'text_lines' in data and isinstance(data['text_lines'], list):
                text_parts = [line.get('text', line) if isinstance(line, dict) else str(line) 
                             for line in data['text_lines']]
                if text_parts:
                    results.append({
                        'text': '\n'.join(text_parts),
                        'metadata': data.get('metadata', {})
                    })
            
            # Fallback to original format
            if not results and isinstance(data, list):
                results = data
            elif not results:
                results = [data]
                
        elif isinstance(data, list):
            results = data
        else:
            results = [{'text': str(data)}]
    
    print(f"Loading {len(results)} documents to Neptune")
    
    # Connect to Neptune
    neptune_client = connect_to_neptune()
    
    # Load each document
    documents_loaded = 0
    
    for i, result in enumerate(results):
        print(f"Loading document {i+1}/{len(results)}")
        
        try:
            # Extract text and metadata
            if isinstance(result, str):
                text = result
                metadata = {}
            elif isinstance(result, dict):
                text = result.get('text', '')
                if not text and 'extraction' in result:
                    text = build_text_from_extraction(result['extraction'])
                metadata = {
                    'page_id': result.get('page_id', f'doc_{i}'),
                    'title': result.get('title', ''),
                    'date': result.get('date', ''),
                    'page_number': result.get('page_number', 1)
                }
                metadata.update(result.get('metadata', {}))
            else:
                print(f"Unexpected result type: {type(result)}")
                continue
            
            # Skip empty text
            if not text or len(text.strip()) < 10:
                print(f"Skipping document {i+1}: text too short or empty")
                continue
            
            # Load document to Neptune
            load_document(neptune_client, text, metadata, i)
            documents_loaded += 1
            
        except Exception as e:
            print(f"Error loading document {i+1}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Close connection
    neptune_client.close()
    
    print(f"Loaded {documents_loaded} documents to Neptune")
    
    return {
        'statusCode': 200,
        'documents_loaded': documents_loaded,
        'message': 'Documents loaded. Configure Bedrock Knowledge Base to extract entities.'
    }


def connect_to_neptune():
    """Connect to Neptune cluster"""
    connection_url = f'wss://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/gremlin'
    print(f"Connecting to Neptune: {connection_url}")
    
    neptune_client = client.Client(
        connection_url,
        'g',
        message_serializer=serializer.GraphSONSerializersV2d0()
    )
    
    # Test connection
    neptune_client.submit('g.V().limit(1)').all().result()
    print("✅ Connected to Neptune")
    
    return neptune_client


def load_document(neptune_client, text: str, metadata: dict, index: int):
    """
    Load a document as a vertex in Neptune
    Bedrock Knowledge Base will extract entities and relationships from the text
    """
    doc_id = metadata.get('page_id', f'document_{index}')
    
    # Truncate text if too long (Neptune property limit is 32KB)
    # Store full text in chunks if needed
    max_text_length = 30000  # Leave some room for encoding
    text_chunks = []
    
    if len(text) > max_text_length:
        # Split into chunks
        for i in range(0, len(text), max_text_length):
            text_chunks.append(text[i:i + max_text_length])
        print(f"Document text split into {len(text_chunks)} chunks")
    else:
        text_chunks = [text]
    
    # Create main document vertex
    query = f"g.addV('Document')"
    query += f".property('id', '{escape_string(doc_id)}')"
    query += f".property('document_text', '{escape_string(text_chunks[0])}')"  # First chunk
    query += f".property('text_length', {len(text)})"
    query += f".property('chunk_count', {len(text_chunks)})"
    query += f".property('loaded_at', '{datetime.now().isoformat()}')"
    
    # Add metadata properties
    if metadata.get('title'):
        query += f".property('title', '{escape_string(metadata['title'])}')"
    if metadata.get('date'):
        query += f".property('publication_date', '{escape_string(metadata['date'])}')"
    if metadata.get('page_number'):
        query += f".property('page_number', {metadata['page_number']})"
    
    try:
        neptune_client.submit(query).all().result()
        print(f"✅ Created Document vertex: {doc_id}")
    except GremlinServerError as e:
        if 'already exists' in str(e).lower():
            print(f"Document {doc_id} already exists, updating...")
            # Update existing document
            update_query = f"g.V().has('id', '{escape_string(doc_id)}')"
            update_query += f".property('document_text', '{escape_string(text_chunks[0])}')"
            update_query += f".property('text_length', {len(text)})"
            update_query += f".property('updated_at', '{datetime.now().isoformat()}')"
            neptune_client.submit(update_query).all().result()
        else:
            raise e
    
    # Create additional chunk vertices if needed
    for i, chunk in enumerate(text_chunks[1:], start=1):
        chunk_id = f"{doc_id}_chunk_{i}"
        chunk_query = f"g.addV('DocumentChunk')"
        chunk_query += f".property('id', '{escape_string(chunk_id)}')"
        chunk_query += f".property('document_text', '{escape_string(chunk)}')"
        chunk_query += f".property('chunk_index', {i})"
        chunk_query += f".property('parent_document', '{escape_string(doc_id)}')"
        
        try:
            neptune_client.submit(chunk_query).all().result()
            
            # Create edge from document to chunk
            edge_query = f"g.V().has('id', '{escape_string(doc_id)}').as('doc')"
            edge_query += f".V().has('id', '{escape_string(chunk_id)}').as('chunk')"
            edge_query += f".addE('HAS_CHUNK').from('doc').to('chunk')"
            edge_query += f".property('chunk_index', {i})"
            neptune_client.submit(edge_query).all().result()
            
            print(f"✅ Created chunk {i}/{len(text_chunks)-1}")
        except GremlinServerError as e:
            if 'already exists' not in str(e).lower():
                print(f"Error creating chunk {i}: {e}")


def build_text_from_extraction(extraction: dict) -> str:
    """Build text from extraction data (fallback for old format)"""
    parts = []
    
    if extraction.get('newspaper_name'):
        parts.append(f"Newspaper: {extraction['newspaper_name']}")
    
    if extraction.get('publication_date'):
        parts.append(f"Date: {extraction['publication_date']}")
    
    if extraction.get('headlines'):
        parts.append("Headlines: " + ", ".join(extraction['headlines']))
    
    if extraction.get('articles'):
        for article in extraction['articles']:
            if article.get('headline'):
                parts.append(f"Article: {article['headline']}")
            if article.get('summary'):
                parts.append(article['summary'])
    
    return "\n".join(parts)


def escape_string(s: str) -> str:
    """Escape special characters for Gremlin"""
    return str(s).replace("'", "\\'").replace('"', '\\"').replace('\n', ' ').replace('\r', '')
