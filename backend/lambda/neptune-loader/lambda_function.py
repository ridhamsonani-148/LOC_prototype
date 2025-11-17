"""
Neptune Loader Lambda Function
Loads knowledge graphs into Amazon Neptune
"""

import json
import os
import boto3
from gremlin_python.driver import client, serializer
from gremlin_python.driver.protocol import GremlinServerError

s3_client = boto3.client('s3')

DATA_BUCKET = os.environ['DATA_BUCKET']
NEPTUNE_ENDPOINT = os.environ['NEPTUNE_ENDPOINT']
NEPTUNE_PORT = os.environ.get('NEPTUNE_PORT', '8182')

def lambda_handler(event, context):
    """
    Load knowledge graphs into Neptune
    
    Event format:
    {
        "bucket": "bucket-name",
        "s3_key": "knowledge_graphs/kg_xxx.json",
        "knowledge_graphs": [...]  # Optional: direct KG data
    }
    """
    print(f"Event: {json.dumps(event)}")
    
    # Get knowledge graphs
    if 'knowledge_graphs' in event and event['knowledge_graphs']:
        knowledge_graphs = event['knowledge_graphs']
    else:
        s3_key = event.get('s3_key')
        bucket = event.get('bucket', DATA_BUCKET)
        
        response = s3_client.get_object(Bucket=bucket, Key=s3_key)
        knowledge_graphs = json.loads(response['Body'].read().decode('utf-8'))
    
    print(f"Loading {len(knowledge_graphs)} knowledge graphs to Neptune")
    
    # Connect to Neptune
    neptune_client = connect_to_neptune()
    
    # Load each knowledge graph
    total_entities = 0
    total_relationships = 0
    
    for i, kg in enumerate(knowledge_graphs):
        print(f"Loading KG {i+1}/{len(knowledge_graphs)}: {kg.get('document_id', 'unknown')}")
        
        try:
            entities_loaded, rels_loaded = load_knowledge_graph(neptune_client, kg)
            total_entities += entities_loaded
            total_relationships += rels_loaded
            
        except Exception as e:
            print(f"Error loading KG {i+1}: {e}")
            continue
    
    # Close connection
    neptune_client.close()
    
    print(f"Loaded {total_entities} entities and {total_relationships} relationships to Neptune")
    
    return {
        'statusCode': 200,
        'entities_loaded': total_entities,
        'relationships_loaded': total_relationships,
        'kg_count': len(knowledge_graphs)
    }


def connect_to_neptune():
    """Connect to Neptune cluster"""
    connection_url = f'wss://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/gremlin'
    print(f"Connecting to Neptune: {connection_url}")
    
    neptune_client = client.Client(
        connection_url,
        'g',
        message_serializer=serializer.GraphSONSerializersV2d0()
    )
    
    # Test connection
    neptune_client.submit('g.V().limit(1)').all().result()
    print("✅ Connected to Neptune")
    
    return neptune_client


def load_knowledge_graph(neptune_client, kg: dict) -> tuple:
    """Load a single knowledge graph"""
    entities = kg.get('entities', [])
    relationships = kg.get('relationships', [])
    
    entities_loaded = 0
    rels_loaded = 0
    
    # Load entities
    for entity in entities:
        try:
            query = create_vertex_query(entity)
            neptune_client.submit(query).all().result()
            entities_loaded += 1
        except GremlinServerError as e:
            if 'already exists' not in str(e).lower():
                print(f"Error creating entity {entity.get('id')}: {e}")
    
    # Load relationships
    for rel in relationships:
        try:
            query = create_edge_query(rel)
            neptune_client.submit(query).all().result()
            rels_loaded += 1
        except GremlinServerError as e:
            print(f"Error creating relationship {rel.get('id')}: {e}")
    
    return entities_loaded, rels_loaded


def create_vertex_query(entity: dict) -> str:
    """Generate Gremlin query to create a vertex"""
    entity_id = entity['id']
    entity_type = entity['type']
    entity_name = entity['name']
    properties = entity.get('properties', {})
    confidence = entity.get('confidence', 1.0)
    
    query = f"g.addV('{entity_type}')"
    query += f".property('id', '{escape_string(entity_id)}')"
    query += f".property('name', '{escape_string(entity_name)}')"
    query += f".property('confidence', {confidence})"
    
    # Add additional properties
    for key, value in properties.items():
        if value and key not in ['id', 'name'] and not isinstance(value, (list, dict)):
            escaped_value = escape_string(str(value))
            query += f".property('{key}', '{escaped_value}')"
    
    return query


def create_edge_query(relationship: dict) -> str:
    """Generate Gremlin query to create an edge"""
    source = relationship['source']
    target = relationship['target']
    rel_type = relationship['type']
    properties = relationship.get('properties', {})
    confidence = relationship.get('confidence', 1.0)
    rel_id = relationship.get('id', f"rel_{source}_{target}")
    
    query = f"g.V().has('id', '{escape_string(source)}').as('src')"
    query += f".V().has('id', '{escape_string(target)}').as('tgt')"
    query += f".addE('{rel_type}').from('src').to('tgt')"
    query += f".property('id', '{escape_string(rel_id)}')"
    query += f".property('confidence', {confidence})"
    
    # Add additional properties
    for key, value in properties.items():
        if value and key not in ['id'] and not isinstance(value, (list, dict)):
            escaped_value = escape_string(str(value))
            query += f".property('{key}', '{escaped_value}')"
    
    return query


def escape_string(s: str) -> str:
    """Escape special characters for Gremlin"""
    return str(s).replace("'", "\\'").replace('"', '\\"').replace('\n', ' ').replace('\r', '')
