"""
Amazon Bedrock Data Automation Lambda
Extracts structured data from newspaper PDFs using Bedrock Data Automation
Includes entity extraction, relationship analysis, and content understanding
"""

import json
import os
import boto3
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

# Initialize AWS clients
s3_client = boto3.client('s3')
bedrock_da = boto3.client('bedrock-agent')
bedrock_da_runtime = boto3.client('bedrock-agent-runtime')

# Environment variables
DATA_BUCKET = os.environ['DATA_BUCKET']
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
AWS_ACCOUNT_ID = os.environ.get('AWS_ACCOUNT_ID')
PROJECT_NAME = os.environ.get('DATA_AUTOMATION_PROJECT_NAME', 'chronicling-america-extraction')

def lambda_handler(event, context):
    """
    Process PDF with Bedrock Data Automation
    
    Input:
    {
        "pdf_key": "pdfs/newspaper_20231117_120000.pdf",
        "pdf_s3_uri": "s3://bucket/pdfs/newspaper_20231117_120000.pdf",
        "bucket": "bucket-name",
        "page_count": 10
    }
    """
    print(f"Event: {json.dumps(event)}")
    
    pdf_s3_uri = event.get('pdf_s3_uri')
    pdf_key = event.get('pdf_key')
    bucket = event.get('bucket', DATA_BUCKET)
    
    if not pdf_s3_uri:
        return {
            'statusCode': 400,
            'error': 'No PDF S3 URI provided'
        }
    
    print(f"Processing PDF: {pdf_s3_uri}")
    
    # Step 1: Ensure Data Automation Project exists
    project_arn = ensure_data_automation_project()
    
    # Step 2: Invoke Data Automation
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    output_prefix = f"data_automation_output/{timestamp}"
    output_s3_uri = f"s3://{bucket}/{output_prefix}/"
    
    print(f"Output will be saved to: {output_s3_uri}")
    
    invocation_arn = invoke_data_automation(
        pdf_s3_uri,
        output_s3_uri,
        project_arn
    )
    
    # Step 3: Wait for completion (with timeout for Lambda)
    max_wait = 600  # 10 minutes max
    result = wait_for_completion(invocation_arn, max_wait)
    
    # Step 4: Download and parse results
    extracted_data = None
    entity_data = None
    extracted_key = None
    
    if result['status'] == 'Success':
        try:
            extracted_data = download_results(output_s3_uri)
            
            # Extract entities and relationships
            entity_data = extract_entities_and_relationships(extracted_data)
            
        except Exception as e:
            print(f"Warning: Could not download/process results: {e}")
    
    # Step 5: Save extracted data to S3
    if extracted_data:
        extracted_key = f"extracted/{timestamp}_bedrock_da.json"
        
        # Prepare comprehensive output
        output_data = {
            'document_id': f"bedrock_da_{timestamp}",
            'source_pdf': pdf_key,
            'invocation_arn': invocation_arn,
            'status': result['status'],
            'output_s3_uri': output_s3_uri,
            'processed_at': datetime.utcnow().isoformat(),
            'processing_time_ms': result.get('processingTimeMillis', 0),
            'entity_summary': entity_data,
            'raw_data': extracted_data,
            'metadata': {
                'bucket': bucket,
                'pdf_s3_uri': pdf_s3_uri,
                'project_arn': project_arn,
                'region': AWS_REGION
            }
        }
        
        s3_client.put_object(
            Bucket=bucket,
            Key=extracted_key,
            Body=json.dumps(output_data, indent=2),
            ContentType='application/json'
        )
        print(f"✓ Saved extracted data to s3://{bucket}/{extracted_key}")
    
    # Prepare response
    response = {
        'statusCode': 200,
        'invocation_arn': invocation_arn,
        'status': result['status'],
        'output_s3_uri': output_s3_uri,
        'extracted_key': extracted_key,
        'bucket': bucket,
        'pdf_key': pdf_key,
        'timestamp': timestamp
    }
    
    # Add entity summary if available
    if entity_data:
        response['entity_count'] = entity_data.get('entity_count', 0)
        response['relationship_count'] = entity_data.get('relationship_count', 0)
    
    print(f"\n{'='*60}")
    print(f"EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"Status: {result['status']}")
    print(f"Output: s3://{bucket}/{extracted_key}")
    if entity_data:
        print(f"Entities: {entity_data.get('entity_count', 0)}")
        print(f"Relationships: {entity_data.get('relationship_count', 0)}")
    print(f"{'='*60}")
    
    return response


def list_existing_projects() -> List[Dict[str, Any]]:
    """
    List all existing Data Automation projects
    
    Returns:
        List of project information
    """
    try:
        response = bedrock_da.list_data_automation_projects()
        return response.get('projects', [])
    except Exception as e:
        print(f"Error listing projects: {e}")
        return []


def ensure_data_automation_project() -> str:
    """
    Ensure Data Automation Project exists, create if needed
    
    Returns:
        Project ARN
    """
    print(f"Checking for Data Automation project: {PROJECT_NAME}")
    
    try:
        # Try to list existing projects
        projects = list_existing_projects()
        
        # Check if our project exists
        for project in projects:
            if project.get('projectName') == PROJECT_NAME:
                project_arn = project.get('projectArn')
                print(f"✓ Using existing project: {project_arn}")
                return project_arn
        
        # Project doesn't exist, create it
        print(f"Creating new Data Automation project: {PROJECT_NAME}")
        
        response = bedrock_da.create_data_automation_project(
            projectName=PROJECT_NAME,
            projectDescription="Historical newspaper data extraction with entity and relationship analysis",
            projectStage='DEVELOPMENT',
            standardOutputConfiguration={
                'document': {
                    'extraction': {
                        'granularity': {
                            'types': ['DOCUMENT', 'PAGE', 'ELEMENT', 'WORD', 'LINE']
                        },
                        'boundingBox': {
                            'state': 'ENABLED'
                        }
                    },
                    'generativeField': {
                        'state': 'ENABLED'
                    },
                    'outputFormat': {
                        'textFormat': {
                            'types': ['PLAIN_TEXT', 'MARKDOWN', 'HTML', 'CSV']
                        },
                        'additionalFileFormat': {
                            'state': 'ENABLED'
                        }
                    }
                }
            }
        )
        
        project_arn = response['projectArn']
        print(f"✓ Created new project: {project_arn}")
        print(f"  Status: {response.get('status', 'Unknown')}")
        
        # Wait for project to be ready
        print("  Waiting for project initialization...")
        time.sleep(5)
        
        return project_arn
        
    except Exception as e:
        print(f"✗ Error with Data Automation project: {e}")
        print(f"  Error type: {type(e).__name__}")
        raise


def create_custom_blueprint(
    blueprint_name: str,
    entity_types: List[str],
    relationship_types: List[str]
) -> str:
    """
    Create a custom blueprint for entity and relationship extraction
    
    Args:
        blueprint_name: Name for the blueprint
        entity_types: List of entity types to extract
        relationship_types: List of relationship types to identify
    
    Returns:
        Blueprint ARN
    """
    print(f"Creating custom blueprint: {blueprint_name}")
    
    # Define schema for newspaper entity extraction
    schema = {
        "version": "1.0",
        "entities": [
            {
                "name": entity_type,
                "description": f"Extract {entity_type} entities from historical newspapers"
            }
            for entity_type in entity_types
        ],
        "relationships": [
            {
                "name": rel_type,
                "description": f"{rel_type} relationship between entities"
            }
            for rel_type in relationship_types
        ]
    }
    
    try:
        response = bedrock_da.create_blueprint(
            blueprintName=blueprint_name,
            type='DOCUMENT',
            blueprintStage='DEVELOPMENT',
            schema=json.dumps(schema)
        )
        
        blueprint_arn = response['blueprint']['blueprintArn']
        print(f"✓ Created Blueprint ARN: {blueprint_arn}")
        print(f"  Entity Types: {len(entity_types)}")
        print(f"  Relationship Types: {len(relationship_types)}")
        
        return blueprint_arn
        
    except Exception as e:
        print(f"✗ Error creating blueprint: {e}")
        raise


def invoke_data_automation(
    input_s3_uri: str,
    output_s3_uri: str,
    project_arn: str
) -> str:
    """
    Invoke Bedrock Data Automation
    
    Args:
        input_s3_uri: S3 URI of input PDF
        output_s3_uri: S3 URI for output
        project_arn: Data Automation Project ARN
    
    Returns:
        Invocation ARN
    """
    print(f"Invoking Data Automation...")
    print(f"  Input: {input_s3_uri}")
    print(f"  Output: {output_s3_uri}")
    print(f"  Project: {project_arn}")
    
    try:
        # Verify input file exists
        input_parts = input_s3_uri.replace('s3://', '').split('/', 1)
        input_bucket = input_parts[0]
        input_key = input_parts[1] if len(input_parts) > 1 else ''
        
        try:
            s3_client.head_object(Bucket=input_bucket, Key=input_key)
            print(f"  ✓ Input file verified")
        except Exception as e:
            raise Exception(f"Input file not found: {input_s3_uri} - {e}")
        
        # Invoke Data Automation
        response = bedrock_da_runtime.invoke_data_automation_async(
            inputConfiguration={
                's3Uri': input_s3_uri
            },
            outputConfiguration={
                's3Uri': output_s3_uri
            },
            dataAutomationConfiguration={
                'dataAutomationProjectArn': project_arn,
                'stage': 'LIVE'
            }
        )
        
        invocation_arn = response['invocationArn']
        print(f"✓ Invocation started: {invocation_arn}")
        
        return invocation_arn
        
    except Exception as e:
        print(f"✗ Error invoking Data Automation: {e}")
        print(f"  Error type: {type(e).__name__}")
        raise


def get_invocation_status(invocation_arn: str) -> Dict[str, Any]:
    """
    Get status of a Data Automation invocation
    
    Args:
        invocation_arn: Invocation ARN
    
    Returns:
        Status information
    """
    try:
        response = bedrock_da_runtime.get_data_automation_status(
            invocationArn=invocation_arn
        )
        return response
    except Exception as e:
        print(f"✗ Error getting status: {e}")
        raise


def wait_for_completion(invocation_arn: str, max_wait: int = 600) -> Dict[str, Any]:
    """
    Wait for Data Automation to complete
    
    Args:
        invocation_arn: Invocation ARN
        max_wait: Maximum seconds to wait
    
    Returns:
        Final status response
    """
    print(f"Waiting for completion (max {max_wait}s)...")
    
    elapsed = 0
    interval = 10
    last_status = None
    
    while elapsed < max_wait:
        try:
            response = get_invocation_status(invocation_arn)
            status = response['status']
            
            # Only print if status changed
            if status != last_status:
                print(f"  Status: {status} ({elapsed}s elapsed)")
                last_status = status
            
            if status == 'Success':
                processing_time = response.get('processingTimeMillis', 0)
                print(f"✓ Processing completed in {elapsed}s (actual: {processing_time}ms)")
                return response
            elif status == 'Failed':
                error_msg = response.get('errorMessage', 'Unknown error')
                print(f"✗ Processing failed: {error_msg}")
                raise Exception(f"Processing failed: {error_msg}")
            
            # Still processing
            time.sleep(interval)
            elapsed += interval
            
        except Exception as e:
            if 'Failed' in str(e) or 'failed' in str(e):
                raise
            print(f"  Warning: Error checking status: {e}")
            time.sleep(interval)
            elapsed += interval
    
    raise TimeoutError(f"Processing did not complete within {max_wait}s")


def download_results(output_s3_uri: str) -> Dict[str, Any]:
    """
    Download and parse results from S3
    
    Args:
        output_s3_uri: S3 URI of output directory
    
    Returns:
        Parsed result data with all output files
    """
    print(f"Downloading results from {output_s3_uri}...")
    
    # Parse S3 URI
    if not output_s3_uri.startswith('s3://'):
        raise ValueError(f"Invalid S3 URI: {output_s3_uri}")
    
    uri_parts = output_s3_uri.replace('s3://', '').split('/', 1)
    bucket = uri_parts[0]
    prefix = uri_parts[1] if len(uri_parts) > 1 else ''
    
    # Remove trailing slash for listing
    if prefix.endswith('/'):
        prefix = prefix[:-1]
    
    # List objects in output prefix
    response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
    
    if 'Contents' not in response:
        raise Exception(f"No output files found at {output_s3_uri}")
    
    print(f"  Found {len(response['Contents'])} output files")
    
    # Find JSON result files
    result_files = [obj for obj in response['Contents'] if obj['Key'].endswith('.json')]
    
    if not result_files:
        raise Exception(f"No JSON result files found at {output_s3_uri}")
    
    # Download all JSON result files
    results = {}
    for result_file in result_files:
        result_key = result_file['Key']
        filename = result_key.split('/')[-1]
        
        print(f"  Downloading: {filename}")
        
        try:
            result_obj = s3_client.get_object(Bucket=bucket, Key=result_key)
            result_data = json.loads(result_obj['Body'].read())
            results[filename] = result_data
        except Exception as e:
            print(f"  Warning: Could not parse {filename}: {e}")
    
    print(f"✓ Downloaded and parsed {len(results)} result files")
    
    # Return the main result or all results
    if len(results) == 1:
        return list(results.values())[0]
    else:
        return results


def extract_entities_and_relationships(extracted_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract entities and relationships from Data Automation output
    
    Args:
        extracted_data: Raw output from Data Automation
    
    Returns:
        Structured entities and relationships
    """
    print("Extracting entities and relationships...")
    
    entities = []
    relationships = []
    
    try:
        # Parse document structure
        document = extracted_data.get('document', {})
        pages = document.get('pages', [])
        
        print(f"  Processing {len(pages)} pages")
        
        # Extract entities from pages
        for page in pages:
            page_entities = page.get('entities', [])
            entities.extend(page_entities)
        
        # Extract relationships
        doc_relationships = document.get('relationships', [])
        relationships.extend(doc_relationships)
        
        print(f"✓ Extracted {len(entities)} entities and {len(relationships)} relationships")
        
        return {
            'entities': entities,
            'relationships': relationships,
            'entity_count': len(entities),
            'relationship_count': len(relationships)
        }
        
    except Exception as e:
        print(f"Warning: Could not extract entities/relationships: {e}")
        return {
            'entities': [],
            'relationships': [],
            'entity_count': 0,
            'relationship_count': 0
        }
