"""
Knowledge Base Custom Transformation Lambda
Transforms bill documents into structured format for GraphRAG

This Lambda runs BEFORE chunking and creates the proper graph structure:
Congress → Congress_N → Bills → Metadata + Text

Input: Raw document from S3
Output: Structured document with entity markers for graph creation
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Transform documents for Knowledge Base GraphRAG
    
    Event structure from Knowledge Base:
    {
        "s3Uri": "s3://bucket/key",
        "s3Bucket": "bucket-name",
        "s3ObjectKey": "extracted/congress_6/hr_1.json",
        "metadata": {...}
    }
    """
    try:
        logger.info(f"Transformation event: {json.dumps(event)}")
        
        # Extract S3 metadata
        s3_object_key = event.get('s3ObjectKey', '')
        metadata = event.get('metadata', {})
        
        # Parse the document content (already in JSON format from collector)
        document_content = event.get('content', {})
        
        # If content is string, parse it
        if isinstance(document_content, str):
            try:
                document_content = json.loads(document_content)
            except:
                # If not JSON, treat as plain text
                document_content = {"bill_text": document_content}
        
        # Extract structured data
        entity_type = document_content.get('entity_type', 'bill')
        congress_number = document_content.get('congress_number', metadata.get('congress', 'unknown'))
        bill_type = document_content.get('bill_type', metadata.get('bill_type', 'unknown'))
        bill_number = document_content.get('bill_number', metadata.get('bill_number', 'unknown'))
        bill_id = document_content.get('bill_id', f"congress_{congress_number}_{bill_type}_{bill_number}")
        parent_congress_id = document_content.get('parent_congress_id', f"congress_{congress_number}")
        
        # Create transformed document with explicit entity markers
        # This structure tells Knowledge Base how to build the graph
        transformed_doc = {
            # Entity markers for graph node creation
            "entities": [
                {
                    "type": "Congress",
                    "id": parent_congress_id,
                    "properties": {
                        "congress_number": congress_number,
                        "name": f"Congress {congress_number}"
                    }
                },
                {
                    "type": "Bill",
                    "id": bill_id,
                    "properties": {
                        "bill_type": bill_type,
                        "bill_number": bill_number,
                        "congress": congress_number,
                        "title": document_content.get('title', 'N/A'),
                        "introduced_date": document_content.get('introduced_date', 'N/A'),
                        "latest_action": document_content.get('latest_action', 'N/A'),
                        "latest_action_date": document_content.get('latest_action_date', 'N/A')
                    }
                }
            ],
            # Relationships for graph edges
            "relationships": [
                {
                    "source": bill_id,
                    "target": parent_congress_id,
                    "type": "BELONGS_TO",
                    "properties": {
                        "relationship": "bill_to_congress"
                    }
                }
            ],
            # Document content for semantic search
            "document": {
                "id": bill_id,
                "type": entity_type,
                "congress": congress_number,
                "bill_type": bill_type,
                "bill_number": bill_number,
                "title": document_content.get('title', 'N/A'),
                "metadata": {
                    "congress_number": congress_number,
                    "bill_type": bill_type,
                    "bill_number": bill_number,
                    "introduced_date": document_content.get('introduced_date', 'N/A'),
                    "latest_action": document_content.get('latest_action', 'N/A')
                },
                "text": document_content.get('bill_text', '')
            }
        }
        
        # Return transformed document
        # Knowledge Base will use this to create:
        # - Congress nodes
        # - Bill nodes
        # - BELONGS_TO edges
        # - Searchable chunks from bill_text
        
        logger.info(f"Transformed document for bill: {bill_id}")
        logger.info(f"Created entities: Congress ({parent_congress_id}), Bill ({bill_id})")
        
        return {
            'statusCode': 200,
            'transformedDocument': transformed_doc
        }
        
    except Exception as e:
        logger.error(f"Transformation error: {str(e)}", exc_info=True)
        
        # Return original document on error (fallback)
        return {
            'statusCode': 200,
            'transformedDocument': event.get('content', {})
        }
