"""
Data Automation Processor Lambda Function

Responsibility: Process PDFs with Amazon Bedrock Data Automation
Follows Single Responsibility Principle - only handles text extraction via Data Automation
Configured for 1760-1820 newspaper processing

Profile ARN: arn:aws:bedrock:{region}:803633136603:data-automation-profile/us.data-automation-v1
"""

import json
import logging
import os
import boto3
import time
from typing import Dict, List, Any
from dataclasses import dataclass, asdict
from datetime import datetime

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.getenv('LOG_LEVEL', 'INFO'))


@dataclass
class ProcessingResult:
    """Data class for processing result"""
    document_id: str
    source_pdf: str
    invocation_arn: str
    status: str
    output_s3_uri: str
    processing_time_seconds: float

class BedrockDataAutomationClient:
    """Client for Bedrock Data Automation - Single Responsibility"""
    
    def __init__(self, region: str, profile_arn: str, project_arn: str = None, project_name: str = None):
        self.region = region
        self.profile_arn = profile_arn
        self.project_arn = project_arn
        self.project_name = project_name
        self.runtime = boto3.client('bedrock-data-automation-runtime', region_name=region)
        self.bedrock_da = boto3.client('bedrock-data-automation', region_name=region)
        
        # Auto-create project if ARN not provided
        if not self.project_arn:
            logger.info("No project ARN provided, will create project on first use")
    
    def ensure_profile_exists(self) -> str:
        """
        Ensure Data Automation profile exists, create if needed
        
        Returns:
            Profile ARN
        """
        logger.info(f"Checking if profile exists: {self.profile_arn}")
        
        try:
            # Try to get the profile
            response = self.bedrock_da.get_data_automation_profile(
                dataAutomationProfileArn=self.profile_arn
            )
            logger.info(f"✅ Profile exists: {self.profile_arn}")
            return self.profile_arn
        except self.bedrock_da.exceptions.ResourceNotFoundException:
            logger.info(f"Profile not found, creating: {self.profile_arn}")
        except Exception as e:
            logger.warning(f"Error checking profile: {e}, will attempt to create")
        
        # Profile doesn't exist, create it
        try:
            logger.info(f"Creating Data Automation profile in region {self.region}")
            
            response = self.bedrock_da.create_data_automation_profile(
                dataAutomationProfileName="us.data-automation-v1",
                dataAutomationProfileDescription="Standard data automation profile for document processing"
            )
            
            created_arn = response['dataAutomationProfileArn']
            logger.info(f"✅ Created profile: {created_arn}")
            return created_arn
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Failed to create profile: {error_msg}")
            
            # If profile already exists, return the ARN
            if 'already exists' in error_msg.lower() or 'ConflictException' in error_msg:
                logger.info("Profile already exists, using provided ARN")
                return self.profile_arn
            
            raise RuntimeError(f"Failed to create profile: {error_msg}")
    
    def ensure_project_exists(self) -> str:
        """
        Ensure Data Automation project exists, create if needed
        
        Returns:
            Project ARN
        """
        if self.project_arn:
            return self.project_arn
        
        logger.info(f"Checking if project '{self.project_name}' exists in region {self.region}...")
        
        # First, try to get the project directly by constructing its ARN
        # This works even if the project doesn't show up in list
        try:
            # Construct potential ARN - we'll try to get it directly
            # Format: arn:aws:bedrock:region:account:data-automation-project/project-id
            # We don't know the project-id, so we'll try listing first
            
            logger.info("Attempting to list all projects...")
            next_token = None
            all_projects = []
            while True:
                if next_token:
                    response = self.bedrock_da.list_data_automation_projects(nextToken=next_token)
                else:
                    response = self.bedrock_da.list_data_automation_projects()
                
                projects = response.get('projects', [])
                all_projects.extend(projects)
                logger.info(f"Found {len(projects)} projects in this page")
                
                for project in projects:
                    logger.info(f"  - {project['projectName']}: {project['projectArn']} (stage: {project.get('projectStage', 'N/A')})")
                    if project['projectName'] == self.project_name:
                        self.project_arn = project['projectArn']
                        logger.info(f"✅ Found existing project: {self.project_arn}")
                        return self.project_arn
                
                next_token = response.get('nextToken')
                if not next_token:
                    break
            
            logger.info(f"Project '{self.project_name}' not found in {len(all_projects)} existing projects")
            
        except Exception as e:
            logger.error(f"Error listing projects: {e}")
            # Continue to try creating the project
        
        # Project doesn't exist, create it
        try:
            logger.info(f"Creating new Data Automation project: {self.project_name}")
            logger.info(f"Region: {self.region}")
            
            response = self.bedrock_da.create_data_automation_project(
                projectName=self.project_name,
                projectDescription="Historical newspaper data extraction with entity and relationship analysis",
                projectStage='LIVE',
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
            
            self.project_arn = response['projectArn']
            logger.info(f"✅ Created project: {self.project_arn}")
            return self.project_arn
            
        except Exception as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown') if hasattr(e, 'response') else 'Unknown'
            error_msg = str(e)
            
            logger.error(f"❌ Failed to create project: {error_code} - {error_msg}")
            
            # If it's a ConflictException, the project exists but is hidden (possibly DELETING state)
            if 'ConflictException' in error_code or 'already exists' in error_msg.lower():
                logger.warning("ConflictException detected - project exists but not visible in list")
                logger.warning("This usually means the project is in DELETING state or there's an API consistency issue")
                
                # Wait a moment and try listing again with more retries
                for attempt in range(3):
                    logger.info(f"Retry attempt {attempt + 1}/3: Waiting 2 seconds and listing projects again...")
                    time.sleep(2)
                    
                    try:
                        response = self.bedrock_da.list_data_automation_projects()
                        projects = response.get('projects', [])
                        logger.info(f"Found {len(projects)} projects on retry {attempt + 1}")
                        
                        for project in projects:
                            logger.info(f"  - {project['projectName']}: {project['projectArn']}")
                            if project['projectName'] == self.project_name:
                                self.project_arn = project['projectArn']
                                logger.info(f"✅ Found project after retry: {self.project_arn}")
                                return self.project_arn
                    except Exception as list_error:
                        logger.error(f"Retry {attempt + 1} failed: {list_error}")
                
                # Still not found - provide workaround
                logger.error("Project exists but cannot be found after multiple retries")
                logger.error("WORKAROUND: Use a different project name or manually delete the ghost project")
                
                raise RuntimeError(
                    f"Ghost project detected: '{self.project_name}' exists but is not visible. "
                    f"This typically happens when a project is stuck in DELETING state. "
                    f"Solutions: "
                    f"1) Wait 5-10 minutes and try again (deletion may complete), "
                    f"2) Use a different project name (set BEDROCK_PROJECT_NAME env var), "
                    f"3) Contact AWS support to remove the stuck project, "
                    f"4) Use your existing 'loc' project by setting BEDROCK_PROJECT_ARN=arn:aws:bedrock:us-east-1:541064517181:data-automation-project/399b803ec8ad"
                )
            
            # Other error
            raise RuntimeError(
                f"Failed to create project '{self.project_name}' in region {self.region}. "
                f"Error: {error_code} - {error_msg}. "
                f"Check IAM permissions and Bedrock Data Automation availability."
            )
    
    def invoke_data_automation(self,
                               input_s3_uri: str,
                               output_s3_uri: str) -> str:
        """
        Invoke Data Automation processing
        
        Args:
            input_s3_uri: S3 URI of input PDF
            output_s3_uri: S3 URI for output
        
        Returns:
            Invocation ARN
        """
        # Ensure profile and project exist before invoking
        profile_arn = self.ensure_profile_exists()
        project_arn = self.ensure_project_exists()
        
        logger.info(f"Invoking Data Automation for {input_s3_uri}")
        logger.info(f"Using profile: {profile_arn}")
        logger.info(f"Using project: {project_arn}")
        
        response = self.runtime.invoke_data_automation_async(
            inputConfiguration={
                's3Uri': input_s3_uri
            },
            outputConfiguration={
                's3Uri': output_s3_uri
            },
            dataAutomationConfiguration={
                'dataAutomationProjectArn': project_arn,
                'stage': 'LIVE'
            },
            dataAutomationProfileArn=profile_arn
        )
        
        invocation_arn = response['invocationArn']
        logger.info(f"Invocation started: {invocation_arn}")
        return invocation_arn
    
    def wait_for_completion(self,
                           invocation_arn: str,
                           max_wait_seconds: int = 300,
                           poll_interval: int = 10) -> Dict[str, Any]:
        """
        Wait for Data Automation processing to complete
        
        Args:
            invocation_arn: Invocation ARN to monitor
            max_wait_seconds: Maximum time to wait
            poll_interval: Seconds between status checks
        
        Returns:
            Final status response
        
        Raises:
            TimeoutError: If processing doesn't complete in time
            RuntimeError: If processing fails
        """
        logger.info(f"Waiting for completion: {invocation_arn}")
        elapsed = 0
        
        while elapsed < max_wait_seconds:
            status_response = self.runtime.get_data_automation_status(
                invocationArn=invocation_arn
            )
            
            status = status_response['status']
            logger.info(f"Status: {status} (elapsed: {elapsed}s)")
            
            if status == 'Success':
                logger.info(f"Processing completed successfully in {elapsed}s")
                return status_response
            elif status in ['ClientError', 'ServiceError']:
                error_msg = status_response.get('errorMessage', 'Unknown error')
                raise RuntimeError(f"Processing failed: {error_msg}")
            
            time.sleep(poll_interval)
            elapsed += poll_interval
        
        raise TimeoutError(f"Processing did not complete within {max_wait_seconds}s")


class S3DocumentHandler:
    """Handles S3 operations for documents - Single Responsibility"""
    
    def __init__(self, s3_client=None):
        self.s3 = s3_client or boto3.client('s3')
    
    def save_processing_metadata(self,
                                bucket: str,
                                key: str,
                                result: ProcessingResult) -> None:
        """Save processing metadata to S3"""
        data = {
            **asdict(result),
            'processed_at': datetime.utcnow().isoformat()
        }
        
        self.s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(data, indent=2),
            ContentType='application/json'
        )
        logger.info(f"Saved metadata to s3://{bucket}/{key}")


class DataAutomationOrchestrator:
    """Orchestrates Data Automation processing workflow"""
    
    def __init__(self,
                 da_client: BedrockDataAutomationClient,
                 s3_handler: S3DocumentHandler,
                 output_bucket: str):
        self.da_client = da_client
        self.s3_handler = s3_handler
        self.output_bucket = output_bucket
    
    def process_pdfs(self, pdf_list: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Process list of PDFs with Data Automation
        
        Args:
            pdf_list: List of dicts with 's3_uri' and 's3_key'
        
        Returns:
            Processing results dict
        """
        logger.info(f"Processing {len(pdf_list)} PDFs with Data Automation")
        
        results = []
        failed = []
        
        for pdf_info in pdf_list:
            try:
                result = self._process_single_pdf(pdf_info)
                results.append(asdict(result))
            except Exception as e:
                logger.error(f"Failed to process {pdf_info.get('s3_uri')}: {e}")
                failed.append({
                    's3_uri': pdf_info.get('s3_uri'),
                    'error': str(e)
                })
        
        return {
            'success': True,
            'total_processed': len(results),
            'total_failed': len(failed),
            'results': results,
            'failed': failed
        }
    
    def _process_single_pdf(self, pdf_info: Dict[str, str]) -> ProcessingResult:
        """Process a single PDF"""
        input_s3_uri = pdf_info['s3_uri']
        pdf_key = pdf_info['s3_key']
        
        # Generate output path
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        document_id = f"da_{timestamp}_{os.path.basename(pdf_key).replace('.pdf', '')}"
        output_prefix = f"data_automation/{document_id}"
        output_s3_uri = f"s3://{self.output_bucket}/{output_prefix}/"
        
        # Invoke processing
        start_time = time.time()
        invocation_arn = self.da_client.invoke_data_automation(
            input_s3_uri=input_s3_uri,
            output_s3_uri=output_s3_uri
        )
        
        # Wait for completion
        status_response = self.da_client.wait_for_completion(invocation_arn)
        processing_time = time.time() - start_time
        
        # Create result
        result = ProcessingResult(
            document_id=document_id,
            source_pdf=input_s3_uri,
            invocation_arn=invocation_arn,
            status=status_response['status'],
            output_s3_uri=status_response['outputConfiguration']['s3Uri'],
            processing_time_seconds=processing_time
        )
        
        # Save metadata
        metadata_key = f"{output_prefix}/metadata.json"
        self.s3_handler.save_processing_metadata(
            bucket=self.output_bucket,
            key=metadata_key,
            result=result
        )
        
        logger.info(f"Completed processing: {document_id} in {processing_time:.1f}s")
        return result


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for Data Automation processing
    
    Input format:
    {
        "pdf_key": "pdfs/newspaper_20231117_120000.pdf",
        "pdf_s3_uri": "s3://bucket/pdfs/newspaper_20231117_120000.pdf",
        "bucket": "bucket-name"
    }
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        # Extract parameters from event
        pdf_s3_uri = event.get('pdf_s3_uri')
        pdf_key = event.get('pdf_key')
        bucket = event.get('bucket')
        
        if not pdf_s3_uri or not pdf_key:
            raise ValueError("Missing required parameters: pdf_s3_uri and pdf_key")
        
        # Get configuration from environment
        region = os.environ.get('BEDROCK_REGION') or os.environ.get('AWS_REGION')
        if not region:
            raise ValueError("BEDROCK_REGION or AWS_REGION environment variable must be set")
        
        logger.info(f"Using region: {region}")
        
        profile_arn = os.environ.get('BEDROCK_PROFILE_ARN')
        if not profile_arn:
            raise ValueError("BEDROCK_PROFILE_ARN environment variable must be set")
        
        project_arn = os.environ.get('BEDROCK_PROJECT_ARN')  # Optional - will auto-create if not provided
        project_name = os.environ.get('BEDROCK_PROJECT_NAME')
        if not project_name:
            raise ValueError("BEDROCK_PROJECT_NAME environment variable must be set")
        
        output_bucket = bucket or os.environ.get('DATA_BUCKET')
        
        logger.info(f"Configuration: region={region}, project_name={project_name}, output_bucket={output_bucket}")
        
        if not output_bucket:
            raise ValueError("DATA_BUCKET environment variable not set")
        
        # Initialize components (Dependency Injection)
        # Project ARN is optional - will be created automatically if not provided
        da_client = BedrockDataAutomationClient(region, profile_arn, project_arn, project_name)
        s3_handler = S3DocumentHandler()
        orchestrator = DataAutomationOrchestrator(da_client, s3_handler, output_bucket)
        
        # Prepare PDF info
        pdf_list = [{
            's3_uri': pdf_s3_uri,
            's3_key': pdf_key
        }]
        
        # Execute processing
        result = orchestrator.process_pdfs(pdf_list)
        
        logger.info(f"Processing completed: {result['total_processed']} succeeded, {result['total_failed']} failed")
        
        # Format response for Step Functions
        if result['total_processed'] > 0:
            processing_result = result['results'][0]
            return {
                'statusCode': 200,
                'document_id': processing_result['document_id'],
                'source_pdf': processing_result['source_pdf'],
                'invocation_arn': processing_result['invocation_arn'],
                'status': processing_result['status'],
                'output_s3_uri': processing_result['output_s3_uri'],
                'processing_time_seconds': processing_result['processing_time_seconds'],
                'bucket': output_bucket,
                'pdf_key': pdf_key
            }
        else:
            # Processing failed
            error_info = result['failed'][0] if result['failed'] else {}
            return {
                'statusCode': 500,
                'error': error_info.get('error', 'Unknown error'),
                'pdf_s3_uri': pdf_s3_uri
            }
    
    except Exception as e:
        logger.error(f"Error in Data Automation processing: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'error': str(e),
            'pdf_s3_uri': event.get('pdf_s3_uri', 'unknown')
        }



