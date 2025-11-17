"""
Bedrock Data Automation Lambda
Processes PDF using Bedrock Data Automation for entity and relationship extraction
"""

import json
import os
import boto3
import time
from datetime import datetime
from typing import Dict, Any, Optional

s3_client = boto3.client('s3')
bedrock_da = boto3.client('bedrock-data-automation')
bedrock_da_runtime = boto3.client('bedrock-data-automation-runtime')

DATA_BUCKET = os.environ['DATA_BUCKET']
AWS_REGION = os.environ.get('AWS_REGION', 'us-west-2')
AWS_ACCOUNT_ID = os.environ.get('AWS_ACCOUNT_ID', '541064517181')

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
    if result['status'] == 'Success':
        try:
            extracted_data = download_results(output_s3_uri)
        except Exception as e:
            print(f"Warning: Could not download results: {e}")
    
    # Step 5: Save extracted data to S3
    if extracted_data:
        extracted_key = f"extracted/{timestamp}_bedrock_da.json"
        s3_client.put_object(
            Bucket=bucket,
            Key=extracted_key,
            Body=json.dumps(extracted_data, indent=2),
            ContentType='application/json'
        )
        print(f"✓ Saved extracted data to s3://{bucket}/{extracted_key}")
    
    return {
        'statusCode': 200,
        'invocation_arn': invocation_arn,
        'status': result['status'],
        'output_s3_uri': output_s3_uri,
        'extracted_key': extracted_key if extracted_data else None,
        'bucket': bucket,
        'pdf_key': pdf_key
    }


def ensure_data_automation_project() -> str:
    """
    Ensure Data Automation Project exists, create if needed
    
    Returns:
        Project ARN
    """
    project_name = "chronicling-america-extraction"
    
    try:
        # Try to list existing projects
        response = bedrock_da.list_data_automation_projects()
        
        # Check if our project exists
        for project in response.get('projects', []):
            if project['projectName'] == project_name:
                project_arn = project['projectArn']
                print(f"✓ Using existing project: {project_arn}")
                return project_arn
        
        # Project doesn't exist, create it
        print(f"Creating new Data Automation project: {project_name}")
        
        response = bedrock_da.create_data_automation_project(
            projectName=project_name,
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
        
        # Wait for project to be ready
        time.sleep(5)
        
        return project_arn
        
    except Exception as e:
        print(f"Error with Data Automation project: {e}")
        raise


def invoke_data_automation(
    input_s3_uri: str,
    output_s3_uri: str,
    project_arn: str
) -> str:
    """
    Invoke Bedrock Data Automation
    
    Returns:
        Invocation ARN
    """
    print(f"Invoking Data Automation...")
    print(f"  Input: {input_s3_uri}")
    print(f"  Output: {output_s3_uri}")
    print(f"  Project: {project_arn}")
    
    try:
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
        print(f"Error invoking Data Automation: {e}")
        raise


def wait_for_completion(invocation_arn: str, max_wait: int = 600) -> Dict[str, Any]:
    """
    Wait for Data Automation to complete
    
    Returns:
        Status response
    """
    print(f"Waiting for completion (max {max_wait}s)...")
    
    elapsed = 0
    interval = 10
    
    while elapsed < max_wait:
        try:
            response = bedrock_da_runtime.get_data_automation_status(
                invocationArn=invocation_arn
            )
            
            status = response['status']
            
            if status == 'Success':
                print(f"✓ Processing completed in {elapsed}s")
                return response
            elif status == 'Failed':
                error_msg = response.get('errorMessage', 'Unknown error')
                raise Exception(f"Processing failed: {error_msg}")
            
            # Still processing
            print(f"  Status: {status} ({elapsed}s elapsed)")
            time.sleep(interval)
            elapsed += interval
            
        except Exception as e:
            if 'Failed' in str(e):
                raise
            print(f"  Error checking status: {e}")
            time.sleep(interval)
            elapsed += interval
    
    raise TimeoutError(f"Processing did not complete within {max_wait}s")


def download_results(output_s3_uri: str) -> Dict[str, Any]:
    """
    Download and parse results from S3
    
    Returns:
        Parsed result data
    """
    print(f"Downloading results from {output_s3_uri}...")
    
    # Parse S3 URI
    uri_parts = output_s3_uri.replace('s3://', '').split('/', 1)
    bucket = uri_parts[0]
    prefix = uri_parts[1] if len(uri_parts) > 1 else ''
    
    # List objects
    response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
    
    if 'Contents' not in response:
        raise Exception(f"No output files found at {output_s3_uri}")
    
    # Find JSON result files
    result_files = [obj for obj in response['Contents'] if obj['Key'].endswith('.json')]
    
    if not result_files:
        raise Exception(f"No JSON result files found at {output_s3_uri}")
    
    # Download first result file
    result_key = result_files[0]['Key']
    print(f"  Downloading: {result_key}")
    
    result_obj = s3_client.get_object(Bucket=bucket, Key=result_key)
    result_data = json.loads(result_obj['Body'].read())
    
    print(f"✓ Downloaded and parsed results")
    
    return result_data
