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
        # The result.json has structure: {metadata, document, pages, elements, text_lines, text_words}
        if isinstance(data, dict):
            results = []
            
            # Log structure for debugging
            if 'document' in data:
                print(f"Document field type: {type(data['document'])}")
                if isinstance(data['document'], dict):
                    print(f"Document keys: {data['document'].keys()}")
            if 'pages' in data:
                print(f"Pages field type: {type(data['pages'])}, length: {len(data['pages']) if isinstance(data['pages'], list) else 'N/A'}")
                if isinstance(data['pages'], list) and len(data['pages']) > 0:
                    print(f"First page type: {type(data['pages'][0])}")
                    if isinstance(data['pages'][0], dict):
                        print(f"First page keys: {data['pages'][0].keys()}")
            
            # Extract text from document field
            if 'document' in data and isinstance(data['document'], dict):
                doc = data['document']
                if 'text' in doc:
                    results.append(doc['text'])
                    print(f"Extracted text from document field: {len(doc['text'])} chars")
            
            # Extract text from pages
            if 'pages' in data and isinstance(data['pages'], list) and len(data['pages']) > 0:
                for i, page in enumerate(data['pages']):
                    if isinstance(page, dict):
                        if 'text' in page:
                            results.append(page['text'])
                            print(f"Extracted text from page {i}: {len(page['text'])} chars")
                        elif 'content' in page:
                            results.append(page['content'])
                            print(f"Extracted content from page {i}: {len(page['content'])} chars")
                print(f"Total pages processed: {len(data['pages'])}, texts extracted: {len([r for r in results])}")
            
            # Extract text from text_lines
            if not results and 'text_lines' in data and isinstance(data['text_lines'], list):
                text_parts = []
                for line in data['text_lines']:
                    if isinstance(line, dict) and 'text' in line:
                        text_parts.append(line['text'])
                    elif isinstance(line, str):
                        text_parts.append(line)
                if text_parts:
                    combined_text = '\n'.join(text_parts)
                    results.append(combined_text)
                    print(f"Extracted text from {len(text_parts)} text_lines: {len(combined_text)} chars")
            
            # Extract text from text_words as last resort
            if not results and 'text_words' in data and isinstance(data['text_words'], list):
                text_parts = []
                for word in data['text_words']:
                    if isinstance(word, dict) and 'text' in word:
                        text_parts.append(word['text'])
                    elif isinstance(word, str):
                        text_parts.append(word)
                if text_parts:
                    combined_text = ' '.join(text_parts)
                    results.append(combined_text)
                    print(f"Extracted text from {len(text_parts)} text_words: {len(combined_text)} chars")
            
            # If still no results, try other common fields
            if not results:
                if 'content' in data:
                    results = [data['content']] if isinstance(data['content'], str) else data['content']
                elif 'text' in data:
                    results = [data['text']]
                else:
                    # Last resort: treat whole dict as one result
                    results = [data]
                    print("No text fields found, using entire data structure")
                    
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
    
    # Claude 3.5 Sonnet has 200K token input limit (~800K chars)
    # No need to truncate unless text is extremely large
    if len(text) > 700000:
        print(f"Text extremely long ({len(text)} chars), truncating to 700,000 chars")
        text = text[:700000] + "\n\n[Text truncated due to length...]"
    
    prompt = f"""Analyze this historical newspaper content (1815-1820) and extract ALL entities and relationships comprehensively.

Content:
{text}

Extract EVERYTHING mentioned:

ENTITY TYPES (extract ALL):
- PERSON: Names of people (politicians, military, citizens, authors)
- LOCATION: Places (cities, states, countries, buildings, streets, ports)
- ORGANIZATION: Groups (businesses, government bodies, military units, societies, newspapers)
- EVENT: Happenings (battles, meetings, elections, arrivals, departures, deaths, births)
- NEWSPAPER: Publication details (title, date, location, publisher)
- ARTICLE: Article metadata (headline, summary, topic)
- ADVERTISEMENT: Products/services advertised (product, company, price, description)
- SHIP: Vessel names and types
- COMMODITY: Goods mentioned (cotton, tobacco, flour, etc.)
- PRICE: Monetary values and prices
- DATE: Specific dates and time periods
- OCCUPATION: Jobs and professions mentioned
- MILITARY_UNIT: Army/Navy units
- GOVERNMENT_POSITION: Political offices and titles

RELATIONSHIP TYPES (extract ALL connections):
- MENTIONED_IN: Entity appears in article/newspaper
- LOCATED_IN: Entity is in a location
- WORKS_FOR: Person works for organization
- PARTICIPATED_IN: Person involved in event
- PUBLISHED_BY: Article published by newspaper
- ADVERTISED_IN: Product advertised in newspaper
- TRAVELED_TO: Person/ship traveled to location
- HOLDS_POSITION: Person holds government/military position
- COMMANDS: Military officer commands unit
- TRADED: Commodity traded at location
- PRICED_AT: Commodity has price
- RELATED_TO: General relationship between entities
- OCCURRED_IN: Event happened in location
- OCCURRED_ON: Event happened on date

Return comprehensive JSON with ALL entities and relationships found:
{{
  "entities": [
    {{
      "id": "unique_id",
      "type": "PERSON|LOCATION|ORGANIZATION|EVENT|NEWSPAPER|ARTICLE|ADVERTISEMENT|SHIP|COMMODITY|PRICE|DATE|OCCUPATION|MILITARY_UNIT|GOVERNMENT_POSITION",
      "name": "Entity name",
      "properties": {{
        "context": "surrounding text",
        "additional_info": "any relevant details"
      }},
      "confidence": 0.9
    }}
  ],
  "relationships": [
    {{
      "id": "rel_id",
      "source": "entity_id",
      "target": "entity_id",
      "type": "MENTIONED_IN|LOCATED_IN|WORKS_FOR|PARTICIPATED_IN|PUBLISHED_BY|ADVERTISED_IN|TRAVELED_TO|HOLDS_POSITION|COMMANDS|TRADED|PRICED_AT|RELATED_TO|OCCURRED_IN|OCCURRED_ON",
      "properties": {{
        "context": "how they're related"
      }},
      "confidence": 0.9
    }}
  ]
}}

Be thorough - extract EVERY entity and relationship you can find. Return only valid JSON."""
    
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 8192,  # Maximum output tokens for Claude 3.5 Sonnet
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
            
            try:
                kg_data = json.loads(json_str)
            except json.JSONDecodeError as json_err:
                print(f"JSON decode error: {json_err}")
                print(f"Attempting to fix truncated JSON...")
                
                # Try to fix common issues with truncated JSON
                # Add closing brackets if missing
                if not json_str.rstrip().endswith('}'):
                    json_str = json_str.rstrip().rstrip(',') + ']}}' 
                
                try:
                    kg_data = json.loads(json_str)
                    print("Successfully recovered from truncated JSON")
                except:
                    print("Could not recover JSON, returning empty knowledge graph")
                    print(f"Problematic JSON (last 500 chars): {json_str[-500:]}")
                    return create_empty_kg(context)
            
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
                    'model_id': BEDROCK_MODEL_ID,
                    'text_length': len(text)
                }
            }
        else:
            print("No JSON found in response")
            return create_empty_kg(context)
    except Exception as e:
        print(f"Error parsing entity extraction: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
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
