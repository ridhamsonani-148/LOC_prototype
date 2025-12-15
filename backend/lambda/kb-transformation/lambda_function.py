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
    
    Actual event structure from Knowledge Base:
    {
        "version": "1.0",
        "bucketName": "congress-bills-data-541064517181-us-east-1",
        "knowledgeBaseId": "ULNF0JAYER",
        "dataSourceId": "MM7S6XODMN", 
        "ingestionJobId": "...",
        "priorTask": "...",
        "inputFiles": [...]
    }
    """
    try:
        logger.info(f"Transformation event received")
        logger.info(f"Event keys: {list(event.keys())}")
        logger.info(f"Full event: {json.dumps(event, indent=2)}")
        
        # The actual event structure is different - let's handle what we get
        bucket_name = event.get('bucketName', '')
        input_files = event.get('inputFiles', [])
        
        logger.info(f"Bucket: {bucket_name}")
        logger.info(f"Input files: {len(input_files)}")
        
        # For now, return the event as-is since we need to understand the actual structure
        # This will help us see what Knowledge Base is actually sending
        logger.info("Returning event as-is for debugging")
        
        return event
        
    except Exception as e:
        logger.error(f"Transformation error: {str(e)}", exc_info=True)
        
        # Return original event on error (fallback)
        return event
