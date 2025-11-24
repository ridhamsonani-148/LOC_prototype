#!/usr/bin/env python3
"""
Backend Testing Script
Tests the Chronicling America pipeline and API
"""

import boto3
import json
import time
import sys
import argparse
from datetime import datetime

# Colors for terminal output
GREEN = '\033[0;32m'
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color

def print_header(text):
    print(f"\n{'='*50}")
    print(f"{BLUE}{text}{NC}")
    print(f"{'='*50}\n")

def print_success(text):
    print(f"{GREEN}✅ {text}{NC}")

def print_error(text):
    print(f"{RED}❌ {text}{NC}")

def print_warning(text):
    print(f"{YELLOW}⚠️  {text}{NC}")

def get_stack_outputs():
    """Get CloudFormation stack outputs"""
    print_header("Fetching Stack Outputs")
    
    cf = boto3.client('cloudformation')
    
    try:
        response = cf.describe_stacks(StackName='ChroniclingAmericaStack')
        outputs = response['Stacks'][0]['Outputs']
        
        result = {}
        for output in outputs:
            result[output['OutputKey']] = output['OutputValue']
        
        print_success("Stack found")
        print(f"Data Bucket: {result.get('DataBucketName', 'N/A')}")
        print(f"State Machine: {result.get('StateMachineArn', 'N/A')}")
        print(f"Chat Endpoint: {result.get('ChatEndpoint', 'N/A')}")
        
        return result
    except Exception as e:
        print_error(f"Stack not found: {e}")
        print("\nPlease deploy the stack first:")
        print("  cd backend && ./deploy.sh")
        sys.exit(1)

def test_pipeline_execution(state_machine_arn, source='newspapers', start_date=None, end_date=None, max_pages=None, congress=None, bill_type=None, limit=None):
    """Test Step Functions pipeline execution"""
    print_header(f"Test 1: Pipeline Execution ({source})")
    
    sf = boto3.client('stepfunctions')
    
    # Build execution input based on source
    if source == 'congress':
        execution_input = {
            "source": "congress",
            "congress": congress or 118,
            "bill_type": bill_type or "hr",
            "limit": limit or 10
        }
    else:
        execution_input = {
            "source": "newspapers",
            "start_date": start_date or "1815-08-01",
            "end_date": end_date or "1815-08-05",
            "max_pages": max_pages or 20
        }
    
    print(f"Input: {json.dumps(execution_input, indent=2)}")
    
    try:
        response = sf.start_execution(
            stateMachineArn=state_machine_arn,
            input=json.dumps(execution_input)
        )
        
        execution_arn = response['executionArn']
        print_success(f"Execution started")
        print(f"Execution ARN: {execution_arn}")
        
        # Monitor execution
        print("\nMonitoring execution (max 10 minutes)...")
        max_wait = 600
        wait_time = 10
        interval = 15
        
        while wait_time < max_wait:
            response = sf.describe_execution(executionArn=execution_arn)
            status = response['status']
            
            if status == 'SUCCEEDED':
                print_success("Execution completed successfully!")
                return True
            elif status in ['FAILED', 'TIMED_OUT', 'ABORTED']:
                print_error(f"Execution failed with status: {status}")
                return False
            else:
                print(f"Status: {status} (waiting {wait_time}s / {max_wait}s)")
                time.sleep(interval)
                wait_time += interval
        
        print_warning(f"Execution still running after {max_wait}s")
        print("Check status in AWS Console")
        return None
        
    except Exception as e:
        print_error(f"Failed to start execution: {e}")
        return False

def test_s3_data(bucket_name):
    """Test S3 data storage"""
    print_header("Test 2: S3 Data Verification")
    
    s3 = boto3.client('s3')
    
    try:
        # Check images
        images = s3.list_objects_v2(Bucket=bucket_name, Prefix='images/')
        images_count = images.get('KeyCount', 0)
        
        # Check extracted
        extracted = s3.list_objects_v2(Bucket=bucket_name, Prefix='extracted/')
        extracted_count = extracted.get('KeyCount', 0)
        
        # Check knowledge graphs
        kg = s3.list_objects_v2(Bucket=bucket_name, Prefix='knowledge_graphs/')
        kg_count = kg.get('KeyCount', 0)
        
        print(f"Images: {images_count} files")
        print(f"Extracted: {extracted_count} files")
        print(f"Knowledge Graphs: {kg_count} files")
        
        if images_count > 0 and extracted_count > 0 and kg_count > 0:
            print_success("All data files created")
            return True
        else:
            print_warning("Some data files missing")
            return False
            
    except Exception as e:
        print_error(f"Failed to check S3: {e}")
        return False

def test_congress_direct(congress=118, bill_type='hr', limit=5):
    """Test Congress bills collection directly (without Step Functions)"""
    print_header("Quick Test: Congress Bills Collection")
    
    lambda_client = boto3.client('lambda')
    
    payload = {
        "source": "congress",
        "congress": congress,
        "bill_type": bill_type,
        "limit": limit
    }
    
    print(f"Testing with: Congress {congress}, Type: {bill_type}, Limit: {limit}")
    
    try:
        # Invoke image-collector Lambda directly
        response = lambda_client.invoke(
            FunctionName='chronicling-america-pipeline-image-collector',
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        
        result = json.loads(response['Payload'].read())
        print(f"\nResponse: {json.dumps(result, indent=2)}")
        
        if result.get('statusCode') == 200:
            print_success(f"Collected {result.get('documents_count', 0)} bills")
            print(f"Saved to: {result.get('s3_key', 'N/A')}")
            
            # Now test Neptune loader
            if result.get('s3_key'):
                print("\nLoading to Neptune...")
                neptune_response = lambda_client.invoke(
                    FunctionName='chronicling-america-pipeline-neptune-loader',
                    InvocationType='RequestResponse',
                    Payload=json.dumps({
                        'bucket': result['bucket'],
                        's3_key': result['s3_key']
                    })
                )
                
                neptune_result = json.loads(neptune_response['Payload'].read())
                
                if neptune_result.get('statusCode') == 200:
                    print_success(f"Loaded {neptune_result.get('documents_loaded', 0)} documents to Neptune")
                    
                    # Trigger KB sync
                    print("\nTriggering Knowledge Base sync...")
                    kb_response = lambda_client.invoke(
                        FunctionName='chronicling-america-pipeline-kb-sync-trigger',
                        InvocationType='RequestResponse',
                        Payload=json.dumps({})
                    )
                    
                    kb_result = json.loads(kb_response['Payload'].read())
                    
                    if kb_result.get('statusCode') == 200:
                        print_success(f"KB sync started: {kb_result.get('ingestion_job_id', 'N/A')}")
                        print_info("Entity extraction will complete in 5-10 minutes")
                        return True
                    else:
                        print_warning(f"KB sync failed: {kb_result.get('error', 'Unknown')}")
                        return True  # Still success if Neptune loaded
                else:
                    print_error(f"Neptune loading failed: {neptune_result.get('error', 'Unknown')}")
                    return False
        else:
            print_error(f"Collection failed: {result.get('error', 'Unknown')}")
            return False
            
    except Exception as e:
        print_error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def wait_for_kb_sync(kb_id, ds_id, max_wait=600):
    """Wait for Knowledge Base sync to complete"""
    print_header("Monitoring Knowledge Base Sync")
    
    bedrock_agent = boto3.client('bedrock-agent')
    elapsed = 0
    
    print(f"Checking sync status every 30 seconds (max {max_wait}s)...")
    
    while elapsed < max_wait:
        try:
            response = bedrock_agent.list_ingestion_jobs(
                knowledgeBaseId=kb_id,
                dataSourceId=ds_id,
                maxResults=1
            )
            
            if response.get('ingestionJobSummaries'):
                job = response['ingestionJobSummaries'][0]
                status = job['status']
                job_id = job.get('ingestionJobId', 'N/A')
                
                print(f"[{elapsed}s] Job: {job_id[:8]}... Status: {status}")
                
                if status == 'COMPLETE':
                    print_success("Knowledge Base sync completed!")
                    print_info("Entities and relationships extracted successfully")
                    return True
                elif status == 'FAILED':
                    print_error("Knowledge Base sync failed")
                    return False
                
        except Exception as e:
            print_error(f"Error checking status: {e}")
        
        time.sleep(30)
        elapsed += 30
    
    print_warning(f"Sync still in progress after {max_wait}s")
    print_info("Check AWS Console → Bedrock → Knowledge Bases for status")
    return None


def test_chat_api(api_url):
    """Test Chat API endpoint"""
    print_header("Test 3: Chat API")
    
    import requests
    
    # Test questions
    questions = [
        "What newspapers are in the database?",
        "Who are the people mentioned?",
        "What locations are mentioned?"
    ]
    
    for i, question in enumerate(questions, 1):
        print(f"\nQuestion {i}: {question}")
        
        try:
            response = requests.post(
                api_url,
                json={"question": question},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                print_success("API responded")
                print(f"Answer: {data.get('answer', 'N/A')[:200]}...")
                if 'result_count' in data:
                    print(f"Results: {data['result_count']}")
            else:
                print_error(f"API returned status {response.status_code}")
                
        except Exception as e:
            print_error(f"API request failed: {e}")
    
    return True

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Test Chronicling America Backend Pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Test with newspapers (default)
  python test_backend.py
  python test_backend.py --max-pages 5
  python test_backend.py --start-date 1815-08-01 --end-date 1815-08-10 --max-pages 10
  
  # Test with Congress bills
  python test_backend.py --source congress
  python test_backend.py --source congress --congress 118 --bill-type hr --limit 5
  python test_backend.py --source congress --congress 117 --bill-type s --limit 10
        '''
    )
    
    # Source selection
    parser.add_argument('--source', type=str, choices=['newspapers', 'congress'], 
                       default='newspapers', help='Data source: newspapers or congress')
    
    # Newspaper options
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD), default: 1815-08-01')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD), default: 1815-08-05')
    parser.add_argument('--max-pages', type=int, help='Maximum pages to process, default: 20')
    
    # Congress options
    parser.add_argument('--congress', type=int, help='Congress number (e.g., 118), default: 118')
    parser.add_argument('--bill-type', type=str, help='Bill type (hr, s, hjres, etc.), default: hr')
    parser.add_argument('--limit', type=int, help='Number of bills to fetch, default: 10')
    
    args = parser.parse_args()
    
    print(f"\n{BLUE}{'='*50}")
    print("Chronicling America Backend Testing")
    print(f"{'='*50}{NC}\n")
    
    # Get stack outputs
    outputs = get_stack_outputs()
    
    state_machine_arn = outputs.get('StateMachineArn')
    bucket_name = outputs.get('DataBucketName')
    api_url = outputs.get('ChatEndpoint')
    
    # Run tests
    results = []
    
    # Test 1: Pipeline execution
    if state_machine_arn:
        result = test_pipeline_execution(
            state_machine_arn,
            source=args.source,
            start_date=args.start_date,
            end_date=args.end_date,
            max_pages=args.max_pages,
            congress=args.congress,
            bill_type=args.bill_type,
            limit=args.limit
        )
        results.append(('Pipeline Execution', result))
    
    # Test 2: S3 data
    if bucket_name:
        result = test_s3_data(bucket_name)
        results.append(('S3 Data', result))
    
    # Test 3: Chat API
    if api_url:
        result = test_chat_api(api_url)
        results.append(('Chat API', result))
    
    # Summary
    print_header("Test Summary")
    
    for test_name, result in results:
        if result is True:
            print_success(f"{test_name}: PASSED")
        elif result is False:
            print_error(f"{test_name}: FAILED")
        else:
            print_warning(f"{test_name}: INCOMPLETE")
    
    # Quick Congress test if requested
    if args.source == 'congress':
        print("\n" + "="*50)
        print("Running quick Congress bills test...")
        print("="*50)
        congress_result = test_congress_direct(
            congress=args.congress or 118,
            bill_type=args.bill_type or 'hr',
            limit=args.limit or 5
        )
        if congress_result:
            print_success("Congress bills test completed!")
            
            # Optionally wait for KB sync
            kb_id = outputs.get('KnowledgeBaseId')
            ds_id = outputs.get('KnowledgeBaseDataSourceId')
            
            if kb_id and ds_id:
                print("\n" + "="*50)
                user_input = input("Wait for Knowledge Base sync to complete? (y/n): ")
                if user_input.lower() == 'y':
                    wait_for_kb_sync(kb_id, ds_id, max_wait=600)
                else:
                    print_info("Skipping wait. Check sync status later:")
                    print(f"  aws bedrock-agent list-ingestion-jobs --knowledge-base-id {kb_id}")
            else:
                print_warning("Knowledge Base IDs not found in stack outputs")
    
    print(f"\n{BLUE}Next Steps:{NC}")
    if args.source == 'congress':
        print("1. Wait for Knowledge Base sync (~5-10 minutes)")
        print("2. Query bills via chat API")
        print(f"3. Example: curl -X POST {api_url} -d '{{\"question\":\"What bills were introduced about taxation?\"}}'")
    else:
        print("1. Open the web UI: frontend/index.html")
        print(f"2. Enter API URL: {api_url}")
        print("3. Start chatting with your historical newspaper data!")
    print("")

if __name__ == '__main__':
    main()
