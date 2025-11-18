"""
Entity Extractor Lambda Function
Extracts entities and relationships from extracted newspaper data
"""

import json
import os
import boto3
from datetime import datetime
from typing import List, Dict, Any

s3_client = boto3.client('s3')
bedrock_runtime = boto3.client('bedrock-runtime')

DATA_BUCKET = os.environ['DATA_BUCKET']
BEDROCK_MODEL_ID = os.environ['BEDROCK_MODEL_ID']

def lambda_handler(event, context):
    """
    Extract entities and relationships from newspaper data
    
    Event format:
    {
        "bucket": "bucket-name",
        "s3_key": "extracted/extraction_results_xxx.json",
        "results": [...]  # Optional: direct results
    }
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
                'error': error_msg,
                'event': event
            }
        
        print(f"Reading extracted data from s3://{bucket}/{s3_key}")
        response = s3_client.get_object(Bucket=bucket, Key=s3_key)
        data = json.loads(response['Body'].read().decode('utf-8'))
        
        print(f"Data type: {type(data)}")
        print(f"Data keys: {data.keys() if isinstance(data, dict) else 'not a dict'}")
        
        # Handle Bedrock Data Automation output format
        # The result.json contains extracted content in various formats
        if isinstance(data, dict):
            # Check for common Bedrock Data Automation output structures
            if 'content' in data:
                # Extract text content
                content = data['content']
                if isinstance(content, str):
                    results = [content]
                elif isinstance(content, list):
                    results = content
                else:
                    results = [data]
            elif 'text' in data:
                results = [data['text']]
            elif 'pages' in data:
                # Extract text from pages
                results = []
                for page in data.get('pages', []):
                    if isinstance(page, dict) and 'text' in page:
                        results.append(page['text'])
                    elif isinstance(page, str):
                        results.append(page)
            else:
                # Fallback: treat the whole dict as one result
                results = [data]
        elif isinstance(data, list):
            results = data
        else:
            # If it's a string, treat it as the extracted text
            results = [str(data)]
    
    print(f"Processing {len(results)} extraction results")
    print(f"First result type: {type(results[0]) if results else 'empty'}")
    if results:
        print(f"First result sample: {str(results[0])[:200]}")
    
    # Extract entities from each result
    knowledge_graphs = []
    for i, result in enumerate(results):
        print(f"Extracting entities from result {i+1}/{len(results)}")
        
        try:
            # Handle different data formats
            if isinstance(result, str):
                # If result is a string, it might be the text content directly
                text = result
                context = {'document_id': f'doc_{i}', 'source': 'bedrock_data_automation'}
            elif isinstance(result, dict):
                # Original format with extraction field
                extraction = result.get('extraction', {})
                text = build_text_from_extraction(extraction)
                context = result
            else:
                print(f"Unexpected result type: {type(result)}")
                continue
            
            # Skip empty text
            if not text or len(text.strip()) < 10:
                print(f"Skipping result {i+1}: text too short or empty")
                continue
            
            # Extract entities and relationships
            kg = extract_entities_and_relationships(text, context)
            
            knowledge_graphs.append(kg)
            
        except Exception as e:
            print(f"Error extracting entities from result {i+1}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Save knowledge graphs to S3
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_key = f"knowledge_graphs/kg_{timestamp}.json"
    
    s3_client.put_object(
        Bucket=DATA_BUCKET,
        Key=output_key,
        Body=json.dumps(knowledge_graphs, indent=2),
        ContentType='application/json'
    )
    
    print(f"Saved {len(knowledge_graphs)} knowledge graphs to s3://{DATA_BUCKET}/{output_key}")
    
    return {
        'statusCode': 200,
        'kg_count': len(knowledge_graphs),
        's3_key': output_key,
        'bucket': DATA_BUCKET,
        'knowledge_graphs': knowledge_graphs
    }


def build_text_from_extraction(extraction: dict) -> str:
    """Build text from extraction data"""
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


def extract_entities_and_relationships(text: str, context: dict) -> dict:
    """Extract entities and relationships using Bedrock"""
    
    prompt = f"""Analyze this historical newspaper content and extract entities and relationships.

Content:
{text}

Extract:
1. ENTITIES with types: PERSON, LOCATION, ORGANIZATION, EVENT, DATE
2. RELATIONSHIPS between entities

Return JSON:
{{
  "entities": [
    {{
      "id": "unique_id",
      "type": "PERSON|LOCATION|ORGANIZATION|EVENT|DATE",
      "name": "Entity name",
      "properties": {{}},
      "confidence": 0.9
    }}
  ],
  "relationships": [
    {{
      "id": "rel_id",
      "source": "entity_id",
      "target": "entity_id",
      "type": "MENTIONED_IN|LOCATED_IN|WORKS_FOR|PARTICIPATED_IN",
      "properties": {{}},
      "confidence": 0.9
    }}
  ]
}}

Return only valid JSON."""
    
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }
        ]
    }
    
    # Invoke Bedrock
    response = bedrock_runtime.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(request_body)
    )
    
    response_body = json.loads(response['body'].read())
    content = response_body['content'][0]['text']
    
    # Parse JSON
    try:
        start = content.find('{')
        end = content.rfind('}') + 1
        if start >= 0 and end > start:
            json_str = content[start:end]
            kg_data = json.loads(json_str)
            
            # Add metadata
            return {
                'document_id': context.get('page_id', 'unknown'),
                'source': context.get('title', ''),
                'publication_date': context.get('date', ''),
                'entities': kg_data.get('entities', []),
                'relationships': kg_data.get('relationships', []),
                'processed_at': datetime.now().isoformat(),
                'metadata': {
                    'extraction_method': 'bedrock_claude',
                    'model_id': BEDROCK_MODEL_ID
                }
            }
        else:
            return create_empty_kg(context)
    except Exception as e:
        print(f"Error parsing entity extraction: {e}")
        return create_empty_kg(context)


def create_empty_kg(context: dict) -> dict:
    """Create empty knowledge graph"""
    return {
        'document_id': context.get('page_id', 'unknown'),
        'source': context.get('title', ''),
        'publication_date': context.get('date', ''),
        'entities': [],
        'relationships': [],
        'processed_at': datetime.now().isoformat(),
        'metadata': {}
    }
