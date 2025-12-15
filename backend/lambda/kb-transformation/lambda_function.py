"""
Knowledge Base Custom Transformation Lambda
Transforms bill documents and adds metadata to each chunk for precise filtering

This Lambda runs DURING chunking and adds structured metadata to each chunk:
- Extracts bill metadata from S3 object metadata
- Attaches metadata to every chunk for exact filtering
- Enables precise bill retrieval using metadata filters

Input: Document chunks from Knowledge Base
Output: Chunks with structured metadata attached
"""

import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Transform document chunks and add structured metadata
    
    Event structure from Knowledge Base:
    {
        "fileMetadata": {
            "x-amz-meta-bill_id": "congress_16_hr_113",
            "x-amz-meta-congress": "16", 
            "x-amz-meta-bill_type": "HR",
            "x-amz-meta-bill_number": "113",
            "x-amz-meta-title": "A Bill To regulate...",
            "x-amz-meta-introduced_date": "1820-03-22",
            "x-amz-meta-latest_action": "Read twice...",
            "x-amz-meta-latest_action_date": "1820-03-22"
        },
        "contentBatches": [
            {
                "contentBody": "BILL METADATA: Congress: 16...",
                "contentType": "TEXT"
            }
        ]
    }
    """
    try:
        logger.info(f"Transformation event received")
        logger.info(f"Event keys: {list(event.keys())}")
        
        # Extract file metadata from S3 object
        file_metadata = event.get('fileMetadata', {})
        content_batches = event.get('contentBatches', [])
        
        logger.info(f"File metadata keys: {list(file_metadata.keys())}")
        logger.info(f"Number of content batches: {len(content_batches)}")
        
        # Extract bill information from S3 metadata
        bill_id = file_metadata.get('x-amz-meta-bill_id', 'unknown')
        congress = file_metadata.get('x-amz-meta-congress', 'unknown')
        bill_type = file_metadata.get('x-amz-meta-bill_type', 'unknown') 
        bill_number = file_metadata.get('x-amz-meta-bill_number', 'unknown')
        title = file_metadata.get('x-amz-meta-title', 'N/A')
        introduced_date = file_metadata.get('x-amz-meta-introduced_date', 'N/A')
        latest_action = file_metadata.get('x-amz-meta-latest_action', 'N/A')
        latest_action_date = file_metadata.get('x-amz-meta-latest_action_date', 'N/A')
        
        logger.info(f"Extracted metadata - Bill ID: {bill_id}, Congress: {congress}, Type: {bill_type}, Number: {bill_number}")
        
        # Transform each content batch by adding structured metadata
        transformed_batches = []
        
        for i, batch in enumerate(content_batches):
            content_body = batch.get('contentBody', '')
            content_type = batch.get('contentType', 'TEXT')
            
            # Create transformed batch with metadata
            transformed_batch = {
                "contentBody": content_body,
                "contentType": content_type,
                "contentMetadata": {
                    # Core identifiers for filtering
                    "bill_id": bill_id,
                    "congress": congress,
                    "bill_type": bill_type.upper(),  # Normalize to uppercase
                    "bill_number": bill_number,
                    "entity_type": "bill",
                    
                    # Additional metadata for enriched responses
                    "title": title,
                    "introduced_date": introduced_date,
                    "latest_action": latest_action,
                    "latest_action_date": latest_action_date,
                    
                    # Chunk information
                    "chunk_index": i,
                    "total_chunks": len(content_batches)
                }
            }
            
            transformed_batches.append(transformed_batch)
            
        logger.info(f"Successfully transformed {len(transformed_batches)} content batches for bill {bill_id}")
        
        # Return transformed batches
        # Knowledge Base will store each chunk with its metadata
        # This enables precise filtering like: congress=16 AND bill_type=HR AND bill_number=113
        return {
            'contentBatches': transformed_batches
        }
        
    except Exception as e:
        logger.error(f"Transformation error: {str(e)}", exc_info=True)
        
        # Return original batches on error (fallback)
        return {
            'contentBatches': event.get('contentBatches', [])
        }
