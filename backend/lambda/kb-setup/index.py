"""
Custom Resource Lambda to create Neptune Analytics Graph and Bedrock Knowledge Base
"""
import json
import boto3
import time
import cfnresponse

bedrock_agent = boto3.client('bedrock-agent')
neptune_graph = boto3.client('neptune-graph')

def handler(event, context):
    """
    CloudFormation Custom Resource handler
    Creates Neptune Analytics graph and Bedrock Knowledge Base
    """
    print(f"Event: {json.dumps(event)}")
    
    request_type = event['RequestType']
    properties = event['ResourceProperties']
    
    try:
        if request_type == 'Create':
            result = create_resources(properties)
            cfnresponse.send(event, context, cfnresponse.SUCCESS, result)
        
        elif request_type == 'Update':
            result = update_resources(properties, event['PhysicalResourceId'])
            cfnresponse.send(event, context, cfnresponse.SUCCESS, result)
        
        elif request_type == 'Delete':
            delete_resources(event['PhysicalResourceId'])
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
    
    except Exception as e:
        print(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {'Error': str(e)})


def create_resources(properties):
    """Create Neptune Analytics graph and Bedrock Knowledge Base"""
    project_name = properties['ProjectName']
    bucket_arn = properties['BucketArn']
    role_arn = properties['RoleArn']
    region = properties['Region']
    account_id = properties['AccountId']
    
    # Step 1: Create Neptune Analytics Graph
    print("Creating Neptune Analytics graph...")
    graph_response = neptune_graph.create_graph(
        graphName=f"{project_name}-graph",
        provisionedMemory=128,  # Minimum 128 GB
        publicConnectivity=False,
        tags={'Project': project_name}
    )
    
    graph_id = graph_response['id']
    graph_arn = f"arn:aws:neptune-graph:{region}:{account_id}:graph/{graph_id}"
    
    print(f"Graph created: {graph_id}")
    
    # Wait for graph to be available
    print("Waiting for graph to be available...")
    waiter = neptune_graph.get_waiter('graph_available')
    waiter.wait(graphIdentifier=graph_id)
    
    # Step 2: Create Knowledge Base
    print("Creating Bedrock Knowledge Base...")
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
    print(f"Knowledge Base created: {kb_id}")
    
    # Step 3: Create Data Source with context enrichment
    print("Creating Data Source...")
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
    print(f"Data Source created: {ds_id}")
    
    return {
        'GraphId': graph_id,
        'GraphArn': graph_arn,
        'KnowledgeBaseId': kb_id,
        'DataSourceId': ds_id
    }


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
