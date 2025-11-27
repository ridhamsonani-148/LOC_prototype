"""
Custom Resource Lambda to create Neptune Analytics Graph and Bedrock Knowledge Base
"""
import json
import boto3
import time
import cfnresponse
import os

# Initialize clients
region = os.environ.get('AWS_REGION', 'us-east-1')
bedrock_agent = boto3.client('bedrock-agent', region_name=region)
neptune_graph = boto3.client('neptune-graph', region_name=region)

def handler(event, context):
    """
    CloudFormation Custom Resource handler
    Creates Neptune Analytics graph and Bedrock Knowledge Base
    """
    print("=" * 60)
    print("KB Setup Lambda Handler Started")
    print("=" * 60)
    print(f"Event: {json.dumps(event, indent=2)}")
    print(f"Region: {region}")
    print(f"Context: {context}")
    
    request_type = event['RequestType']
    properties = event['ResourceProperties']
    
    print(f"Request Type: {request_type}")
    print(f"Properties: {json.dumps(properties, indent=2)}")
    
    try:
        if request_type == 'Create':
            result = create_resources(properties)
            # PhysicalResourceId format: "graph_id|kb_id|ds_id"
            physical_id = f"{result['GraphId']}|{result['KnowledgeBaseId']}|{result['DataSourceId']}"
            cfnresponse.send(event, context, cfnresponse.SUCCESS, result, physical_id)
        
        elif request_type == 'Update':
            physical_id = event['PhysicalResourceId']
            result = update_resources(properties, physical_id)
            cfnresponse.send(event, context, cfnresponse.SUCCESS, result, physical_id)
        
        elif request_type == 'Delete':
            physical_id = event['PhysicalResourceId']
            delete_resources(physical_id)
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physical_id)
    
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        # Use existing physical ID for Update/Delete, or generate one for Create
        physical_id = event.get('PhysicalResourceId', 'FAILED')
        cfnresponse.send(event, context, cfnresponse.FAILED, {'Error': str(e)}, physical_id)


def create_resources(properties):
    """Create Neptune Analytics graph and Bedrock Knowledge Base"""
    project_name = properties['ProjectName']
    bucket_arn = properties['BucketArn']
    role_arn = properties['RoleArn']
    region = properties['Region']
    account_id = properties['AccountId']
    
    print(f"Starting resource creation for project: {project_name}")
    print(f"Bucket ARN: {bucket_arn}")
    print(f"Role ARN: {role_arn}")
    print(f"Region: {region}")
    
    # Step 1: Create Neptune Analytics Graph
    print("Step 1: Creating Neptune Analytics graph...")
    try:
        graph_response = neptune_graph.create_graph(
            graphName=f"{project_name}-graph",
            provisionedMemory=128,  # Minimum 128 GB
            publicConnectivity=False,
            tags={'Project': project_name}
        )
        
        graph_id = graph_response['id']
        graph_arn = f"arn:aws:neptune-graph:{region}:{account_id}:graph/{graph_id}"
        
        print(f"✓ Graph created: {graph_id}")
        print(f"  Graph ARN: {graph_arn}")
    except Exception as e:
        print(f"✗ Failed to create graph: {str(e)}")
        raise
    
    # Wait for graph to be available
    print("Step 2: Waiting for graph to be available...")
    try:
        max_wait = 600  # 10 minutes
        elapsed = 0
        while elapsed < max_wait:
            response = neptune_graph.get_graph(graphIdentifier=graph_id)
            status = response['status']
            print(f"  Graph status: {status} (waited {elapsed}s)")
            
            if status == 'AVAILABLE':
                print("✓ Graph is available")
                break
            elif status in ['FAILED', 'DELETING']:
                raise Exception(f"Graph creation failed with status: {status}")
            
            time.sleep(30)
            elapsed += 30
        
        if elapsed >= max_wait:
            raise Exception("Graph creation timed out")
    except Exception as e:
        print(f"✗ Graph availability check failed: {str(e)}")
        raise
    
    # Step 2: Create Knowledge Base
    print("Step 3: Creating Bedrock Knowledge Base...")
    try:
        kb_response = bedrock_agent.create_knowledge_base(
            name=f"{project_name}-knowledge-base",
            roleArn=role_arn,
            knowledgeBaseConfiguration={
                'type': 'VECTOR',
                'vectorKnowledgeBaseConfiguration': {
                    'embeddingModelArn': f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"
                }
            },
            storageConfiguration={
                'type': 'NEPTUNE_ANALYTICS',
                'neptuneAnalyticsConfiguration': {
                    'graphArn': graph_arn,
                    'fieldMapping': {
                        'metadataField': 'metadata',
                        'textField': 'text'
                    }
                }
            }
        )
        
        kb_id = kb_response['knowledgeBase']['knowledgeBaseId']
        print(f"✓ Knowledge Base created: {kb_id}")
    except Exception as e:
        print(f"✗ Failed to create Knowledge Base: {str(e)}")
        raise
    
    # Step 3: Create Data Source with context enrichment
    print("Step 4: Creating Data Source...")
    try:
        ds_response = bedrock_agent.create_data_source(
            name=f"{project_name}-s3-datasource",
            description="S3 data source for GraphRAG",
            knowledgeBaseId=kb_id,
            dataSourceConfiguration={
                'type': 'S3',
                's3Configuration': {
                    'bucketArn': bucket_arn,
                    'inclusionPrefixes': ['extracted/']
                }
            },
            vectorIngestionConfiguration={
                'chunkingConfiguration': {
                    'chunkingStrategy': 'FIXED_SIZE',
                    'fixedSizeChunkingConfiguration': {
                        'maxTokens': 1000,
                        'overlapPercentage': 20
                    }
                },
                'contextEnrichmentConfiguration': {
                    'type': 'BEDROCK_FOUNDATION_MODEL',
                    'bedrockFoundationModelConfiguration': {
                        'modelArn': f"arn:aws:bedrock:{region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                        'enrichmentStrategyConfiguration': {
                            'method': 'CHUNK_ENTITY_EXTRACTION'
                        }
                    }
                }
            }
        )
        
        ds_id = ds_response['dataSource']['dataSourceId']
        print(f"✓ Data Source created: {ds_id}")
    except Exception as e:
        print(f"✗ Failed to create Data Source: {str(e)}")
        raise
    
    result = {
        'GraphId': graph_id,
        'GraphArn': graph_arn,
        'KnowledgeBaseId': kb_id,
        'DataSourceId': ds_id
    }
    
    print("=" * 60)
    print("✓ All resources created successfully!")
    print(f"  Graph ID: {graph_id}")
    print(f"  Knowledge Base ID: {kb_id}")
    print(f"  Data Source ID: {ds_id}")
    print("=" * 60)
    
    return result


def update_resources(properties, physical_resource_id):
    """Update resources (not implemented)"""
    # For now, just return existing IDs
    return {'Message': 'Update not implemented'}


def delete_resources(physical_resource_id):
    """Delete Neptune Analytics graph and Bedrock Knowledge Base"""
    # Parse physical resource ID to get graph_id and kb_id
    # Format: "graph_id|kb_id|ds_id"
    try:
        parts = physical_resource_id.split('|')
        if len(parts) >= 3:
            graph_id, kb_id, ds_id = parts[0], parts[1], parts[2]
            
            # Delete Data Source
            try:
                bedrock_agent.delete_data_source(
                    knowledgeBaseId=kb_id,
                    dataSourceId=ds_id
                )
                print(f"Deleted Data Source: {ds_id}")
            except Exception as e:
                print(f"Error deleting data source: {e}")
            
            # Delete Knowledge Base
            try:
                bedrock_agent.delete_knowledge_base(
                    knowledgeBaseId=kb_id
                )
                print(f"Deleted Knowledge Base: {kb_id}")
            except Exception as e:
                print(f"Error deleting knowledge base: {e}")
            
            # Delete Neptune Graph
            try:
                neptune_graph.delete_graph(
                    graphIdentifier=graph_id,
                    skipSnapshot=True
                )
                print(f"Deleted Neptune Graph: {graph_id}")
            except Exception as e:
                print(f"Error deleting graph: {e}")
    
    except Exception as e:
        print(f"Error during deletion: {e}")
