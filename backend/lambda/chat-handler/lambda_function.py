"""
Chat Handler Lambda Function
Provides chat interface using Bedrock Knowledge Base with GraphRAG
Uses Neptune Analytics graph through Knowledge Base for entity extraction
"""

import json
import os
import boto3

bedrock_agent_runtime = boto3.client('bedrock-agent-runtime')

BEDROCK_MODEL_ID = os.environ.get('MODEL_ID', 'anthropic.claude-3-5-sonnet-20241022-v2:0')
KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID', '')

def lambda_handler(event, context):
    """
    Handle chat requests
    
    GET /health - Health check
    POST /chat - Chat query
    """
    print(f"Event: {json.dumps(event)}")
    
    http_method = event.get('httpMethod', 'POST')
    
    # Health check
    if http_method == 'GET':
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'status': 'healthy',
                'service': 'chronicling-america-chat',
                'knowledge_base_id': KNOWLEDGE_BASE_ID,
                'model_id': BEDROCK_MODEL_ID
            })
        }
    
    # Chat query
    try:
        body = json.loads(event.get('body', '{}'))
        question = body.get('question', '')
        persona = body.get('persona', 'general')  # congressional_staffer, research_journalist, law_student, general
        
        if not question:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Question is required'})
            }
        
        print(f"Question: {question}")
        print(f"Persona: {persona}")
        
        # Check if Knowledge Base is configured
        if not KNOWLEDGE_BASE_ID:
            print("ERROR: KNOWLEDGE_BASE_ID not set")
            return {
                'statusCode': 503,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Knowledge Base not configured yet. Please run the deployment pipeline first.'
                })
            }
        
        # Query Knowledge Base with GraphRAG
        response = query_knowledge_base(question, persona)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'question': question,
                'answer': response['answer'],
                'sources': response.get('sources', []),
                'entities': response.get('entities', [])
            })
        }
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': str(e)})
        }


def get_persona_prompt(persona: str) -> str:
    """
    Get system prompt based on user persona
    """
    prompts = {
        'congressional_staffer': """You are an expert constitutional research assistant for Congressional staff. 
Your responses should be:
- Precise and authoritative with specific citations
- Focused on precedent and constitutional interpretation
- Include relevant Federalist Papers references when applicable
- Provide historical context for legislative decisions
- Use formal, professional language suitable for briefing members of Congress
- Cite specific articles, sections, and amendments
- Reference relevant Supreme Court cases with case names and years""",
        
        'research_journalist': """You are a constitutional expert helping journalists research stories.
Your responses should be:
- Provide cultural and historical context from the era
- Explain constitutional language in accessible terms
- Connect constitutional provisions to modern relevance
- Include interesting historical anecdotes and context
- Explain the "why" behind constitutional decisions
- Reference the social and political climate of the time
- Use clear, engaging language suitable for news articles""",
        
        'law_student': """You are a constitutional law professor helping students learn.
Your responses should be:
- Educational and comprehensive
- Explain legal reasoning and constitutional theory
- Trace the evolution of constitutional interpretation
- Reference landmark cases with detailed analysis
- Explain both majority and dissenting opinions
- Connect constitutional provisions to broader legal principles
- Use precise legal terminology with explanations
- Encourage critical thinking about constitutional questions""",
        
        'general': """You are a knowledgeable constitutional expert.
Your responses should be:
- Clear and informative
- Balanced and objective
- Include relevant historical context
- Cite specific constitutional provisions
- Reference important court cases when relevant
- Use accessible language while maintaining accuracy"""
    }
    
    return prompts.get(persona, prompts['general'])


def query_knowledge_base(question: str, persona: str = 'general') -> dict:
    """
    Query Bedrock Knowledge Base with GraphRAG and Reranking
    Neptune Analytics graph provides automatic entity extraction and relationships
    Uses Amazon Rerank model for improved relevance
    """
    print(f"Querying Knowledge Base: {KNOWLEDGE_BASE_ID}")
    
    # Get AWS context from Lambda environment
    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    
    # Get account ID from Lambda context (available via STS)
    sts_client = boto3.client('sts')
    account_id = sts_client.get_caller_identity()['Account']
    
    try:
        # Determine if MODEL_ID is an inference profile or foundation model
        # Inference profiles start with region or 'us.' or 'eu.' or 'global.' prefix
        if BEDROCK_MODEL_ID.startswith(('us.', 'eu.', 'global.')):
            # It's an inference profile ARN - requires account ID
            model_arn = f'arn:aws:bedrock:{aws_region}:{account_id}:inference-profile/{BEDROCK_MODEL_ID}'
        else:
            # It's a foundation model ID - no account ID needed
            model_arn = f'arn:aws:bedrock:{aws_region}::foundation-model/{BEDROCK_MODEL_ID}'
        
        print(f"Using model ARN: {model_arn}")
        print(f"Using persona: {persona}")
        
        # Get persona-specific system prompt
        system_prompt = get_persona_prompt(persona)
        
        # Log retrieval configuration with reranking
        # According to AWS docs, reranking goes INSIDE vectorSearchConfiguration
        retrieval_config = {
            'vectorSearchConfiguration': {
                'numberOfResults': 100,  # Retrieve 100 documents initially
                'rerankingConfiguration': {
                    'type': 'BEDROCK_RERANKING_MODEL',
                    'bedrockRerankingConfiguration': {
                        'numberOfRerankedResults': 100,  # Keep 100 after reranking
                        'modelConfiguration': {
                            'modelArn': f'arn:aws:bedrock:{aws_region}::foundation-model/amazon.rerank-v1:0'
                        }
                    }
                }
            }
        }
        
        print(f"Retrieval Configuration with Reranking: {json.dumps(retrieval_config, indent=2)}")
        
        # Build the full configuration
        retrieve_and_generate_config = {
            'type': 'KNOWLEDGE_BASE',
            'knowledgeBaseConfiguration': {
                'knowledgeBaseId': KNOWLEDGE_BASE_ID,
                'modelArn': model_arn,
                'generationConfiguration': {
                    'promptTemplate': {
                        'textPromptTemplate': f"""{system_prompt}

Use the following retrieved context to answer the question. If you don't know the answer based on the context, say so.

Context:
$search_results$

Question: $query$

Answer:"""
                    }
                },
                'retrievalConfiguration': retrieval_config,
                'orchestrationConfiguration': {
                    'queryTransformationConfiguration': {
                        'type': 'QUERY_DECOMPOSITION'
                    }
                }
            }
        }
        
        print(f"Full Configuration Type: {retrieve_and_generate_config['type']}")
        print(f"Knowledge Base ID: {KNOWLEDGE_BASE_ID}")
        print(f"Number of results to retrieve: 100")
        print(f"Reranking enabled: True (amazon.rerank-v1:0)")
        print(f"Number of results after reranking: 100")
        
        response = bedrock_agent_runtime.retrieve_and_generate(
            input={
                'text': question
            },
            retrieveAndGenerateConfiguration=retrieve_and_generate_config
        )
        
        # Extract answer and sources
        answer = response['output']['text']
        
        # Log response structure
        print(f"Response keys: {list(response.keys())}")
        
        # Extract sources (documents that were retrieved)
        sources = []
        if 'citations' in response:
            print(f"Number of citations: {len(response['citations'])}")
            for citation in response['citations']:
                retrieved_refs = citation.get('retrievedReferences', [])
                print(f"Citation has {len(retrieved_refs)} retrieved references")
                for reference in retrieved_refs:
                    sources.append({
                        'document_id': reference.get('location', {}).get('s3Location', {}).get('uri', ''),
                        'content': reference.get('content', {}).get('text', '')[:200] + '...'
                    })
        else:
            print("No citations in response")
        
        # Extract entities (if available in response metadata)
        entities = []
        if 'metadata' in response:
            entities = response['metadata'].get('entities', [])
            print(f"Found {len(entities)} entities in metadata")
        
        print(f"Answer generated with {len(sources)} sources")
        print(f"Total unique documents retrieved: {len(set(s['document_id'] for s in sources))}")
        
        return {
            'answer': answer,
            'sources': sources,
            'entities': entities
        }
        
    except Exception as e:
        print(f"Error querying Knowledge Base: {e}")
        return {
            'answer': f"I encountered an error querying the knowledge base: {str(e)}",
            'sources': [],
            'entities': []
        }
