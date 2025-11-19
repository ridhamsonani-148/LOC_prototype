#!/usr/bin/env python3
"""
Backend Testing Script
Tests the Chronicling America pipeline and API
"""

import boto3
import json
import time
import sys
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

def test_pipeline_execution(state_machine_arn):
    """Test Step Functions pipeline execution"""
    print_header("Test 1: Pipeline Execution")
    
    sf = boto3.client('stepfunctions')
    
    execution_input = {
        "start_date": "1815-08-01",
        "end_date": "1815-08-05",
        "max_pages": 20
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
        wait_time = 0
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
        result = test_pipeline_execution(state_machine_arn)
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
    
    print(f"\n{BLUE}Next Steps:{NC}")
    print("1. Open the web UI: frontend/index.html")
    print(f"2. Enter API URL: {api_url}")
    print("3. Start chatting with your historical newspaper data!")
    print("")

if __name__ == '__main__':
    main()
