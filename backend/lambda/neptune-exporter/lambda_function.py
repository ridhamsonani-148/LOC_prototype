"""
Neptune to S3 Exporter Lambda
Exports Neptune documents to S3 for Bedrock Knowledge Base ingestion
"""
import json
import os
import boto3
from gremlin_python.driver import client
from gremlin_python.driver import serializer

s3 = boto3.client('s3')

NEPTUNE_ENDPOINT = os.environ['NEPTUNE_ENDPOINT']
NEPTUNE_PORT = os.environ['NEPTUNE_PORT']
DATA_BUCKET = os.environ['DATA_BUCKET']


def lambda_handler(event, context):
    """
    Export Neptune documents to S3 in format suitable for Bedrock KB
    
    Input: Result from neptune-loader
    Output: S3 prefix where documents were exported
    """
    print(f"Event: {json.dumps(event)}")
    
    try:
        # Connect to Neptune
        neptune_client = connect_to_neptune()
        
        # Query all documents
        query = "g.V().hasLabel('Document').valueMap(true)"
        print(f"Executing query: {query}")
        
        results = neptune_client.submit(query).all().result()
        print(f"Found {len(results)} documents in Neptune")
        
        if len(results) == 0:
            return {
                'statusCode': 200,
                'documents_exported': 0,
                's3_prefix': f's3://{DATA_BUCKET}/kb-documents/',
                'message': 'No documents to export'
            }
        
        # Export each document to S3
        exported_count = 0
        s3_prefix = 'kb-documents/'
        
        for idx, doc in enumerate(results):
            try:
                # Extract document data
                doc_id = doc.get('id', [f'doc-{idx}'])[0] if 'id' in doc else f'doc-{idx}'
                doc_text = doc.get('document_text', [''])[0] if 'document_text' in doc else ''
                title = doc.get('title', ['Untitled'])[0] if 'title' in doc else 'Untitled'
                
                if not doc_text:
                    print(f"Skipping document {doc_id} - no text content")
                    continue
                
                # Create document in Bedrock KB format
                kb_document = {
                    'id': str(doc_id),
                    'title': title,
                    'content': doc_text,
                    'metadata': {}
                }
                
                # Add metadata fields
                for key in ['publication_date', 'page_number', 'source', 'loaded_at']:
                    if key in doc and doc[key]:
                        kb_document['metadata'][key] = str(doc[key][0])
                
                # Save to S3 as JSON
                s3_key = f'{s3_prefix}{doc_id}.json'
                s3.put_object(
                    Bucket=DATA_BUCKET,
                    Key=s3_key,
                    Body=json.dumps(kb_document, indent=2),
                    ContentType='application/json'
                )
                
                exported_count += 1
                
                if exported_count % 10 == 0:
                    print(f"Exported {exported_count} documents...")
                    
            except Exception as e:
                print(f"Error exporting document {idx}: {e}")
                continue
        
        print(f"✅ Successfully exported {exported_count} documents to S3")
        
        return {
            'statusCode': 200,
            'documents_exported': exported_count,
            's3_prefix': f's3://{DATA_BUCKET}/{s3_prefix}',
            's3_bucket': DATA_BUCKET,
            's3_key_prefix': s3_prefix,
            'message': f'Exported {exported_count} documents to S3'
        }
        
    except Exception as e:
        print(f"❌ Error exporting documents: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'error': str(e),
            'message': 'Failed to export documents from Neptune'
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
