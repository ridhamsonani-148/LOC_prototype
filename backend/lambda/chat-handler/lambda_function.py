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
        # Log detailed error for debugging
        print(f"ERROR in lambda_handler: {type(e).__name__}: {str(e)}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        
        # Return user-friendly error message
        return {
            'statusCode': 200,  # Return 200 to avoid frontend errors
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'question': body.get('question', ''),
                'answer': "I'm sorry, I encountered an unexpected error. Please try again in a moment.",
                'sources': [],
                'entities': [],
                'error': True
            })
        }


def generate_query_variations(question: str, aws_region: str) -> list:
    """
    Generate multiple variations of the query to improve retrieval consistency
    This solves the problem of vector search being sensitive to exact phrasing
    """
    bedrock_runtime = boto3.client('bedrock-runtime', region_name=aws_region)
    
    variation_prompt = f"""Generate 3 different ways to ask this question, keeping the same meaning but using different words and word orders.

Original question: {question}

Provide 3 variations (one per line, no numbering):"""

    try:
        response = bedrock_runtime.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 300,
                "temperature": 0.7,
                "messages": [{
                    "role": "user",
                    "content": variation_prompt
                }]
            })
        )
        
        response_body = json.loads(response['body'].read())
        variations_text = response_body['content'][0]['text'].strip()
        
        # Parse variations (one per line)
        variations = [v.strip() for v in variations_text.split('\n') if v.strip() and not v.strip().startswith(('1.', '2.', '3.', '-', '*'))]
        
        # Always include original question
        all_variations = [question] + variations[:3]  # Original + up to 3 variations
        
        return all_variations
        
    except Exception as e:
        print(f"Query variation generation failed: {e}")
        return [question]  # Fallback to original


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


def extract_bill_info(question: str) -> dict:
    """
    Extract bill information from user question for metadata filtering
    
    Examples:
    - "what is bill HR 1 in congress 6?" -> {"congress": "6", "bill_type": "HR", "bill_number": "1"}
    - "show me bill S 2 from congress 16" -> {"congress": "16", "bill_type": "S", "bill_number": "2"}
    - "tell me about HR1 congress 6" -> {"congress": "6", "bill_type": "HR", "bill_number": "1"}
    """
    import re
    
    # Normalize question to lowercase for pattern matching
    q = question.lower()
    
    bill_info = {}
    
    # Pattern 1: "bill HR 1 in congress 6" or "bill HR1 congress 6"
    pattern1 = r'bill\s+([a-z]+)\s*(\d+).*congress\s+(\d+)'
    match1 = re.search(pattern1, q)
    if match1:
        bill_info = {
            "bill_type": match1.group(1).upper(),
            "bill_number": match1.group(2),
            "congress": match1.group(3)
        }
    
    # Pattern 2: "HR 1 from congress 6" or "S2 congress 16"
    pattern2 = r'([a-z]+)\s*(\d+).*congress\s+(\d+)'
    match2 = re.search(pattern2, q)
    if match2 and not match1:  # Only if pattern1 didn't match
        bill_info = {
            "bill_type": match2.group(1).upper(),
            "bill_number": match2.group(2),
            "congress": match2.group(3)
        }
    
    # Pattern 3: "congress 6 bill HR 1"
    pattern3 = r'congress\s+(\d+).*bill\s+([a-z]+)\s*(\d+)'
    match3 = re.search(pattern3, q)
    if match3 and not match1 and not match2:
        bill_info = {
            "congress": match3.group(1),
            "bill_type": match3.group(2).upper(),
            "bill_number": match3.group(3)
        }
    
    print(f"Extracted bill info from '{question}': {bill_info}")
    return bill_info


def build_enhanced_query(question: str, bill_info: dict) -> str:
    """
    Build enhanced query that includes specific bill identifiers in the search text
    Since Knowledge Base doesn't index S3 metadata as filterable fields,
    we enhance the query to target specific bill content
    """
    if not bill_info:
        return question
    
    # Build specific search terms based on bill info
    search_terms = []
    
    if 'congress' in bill_info:
        search_terms.append(f"Congress: {bill_info['congress']}")
    
    if 'bill_type' in bill_info:
        search_terms.append(f"Bill Type: {bill_info['bill_type']}")
    
    if 'bill_number' in bill_info:
        search_terms.append(f"Bill Number: {bill_info['bill_number']}")
    
    if search_terms:
        # Combine original question with specific search terms
        enhanced_query = f"{question} {' '.join(search_terms)}"
        return enhanced_query
    
    return question



def query_knowledge_base(question: str, persona: str = 'general') -> dict:
    """
    Query Bedrock Knowledge Base with dynamic metadata filtering
    Automatically detects bill references and filters to specific bills
    """
    print(f"Querying Knowledge Base: {KNOWLEDGE_BASE_ID}")
    
    # Get AWS context from Lambda environment
    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    
    # Get account ID from Lambda context (available via STS)
    sts_client = boto3.client('sts')
    account_id = sts_client.get_caller_identity()['Account']
    
    # Extract bill information for enhanced query targeting
    bill_info = extract_bill_info(question)
    enhanced_query = build_enhanced_query(question, bill_info)
    
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
        
        # Use simple retrieval approach with content-based targeting
        print(f"Processing question: {question}")
        if bill_info:
            print("Detected specific bill reference - will use enhanced query targeting")
        
        # Build retrieval configuration for content-based targeting
        retrieval_config = {
            'vectorSearchConfiguration': {
                'numberOfResults': 100  # Increased to 100 for better retrieval
            }
        }
        
        # Log the enhanced query approach
        if bill_info:
            print(f"Detected specific bill: {bill_info}")
            print(f"Enhanced query: {enhanced_query}")
            print("Using content-based targeting instead of metadata filtering")
        else:
            print("No specific bill detected - using original query")
        
        print(f"Retrieval Configuration: {json.dumps(retrieval_config, indent=2)}")
        
        # Build the full configuration
        retrieve_and_generate_config = {
            'type': 'KNOWLEDGE_BASE',
            'knowledgeBaseConfiguration': {
                'knowledgeBaseId': KNOWLEDGE_BASE_ID,
                'modelArn': model_arn,
                'generationConfiguration': {
                    'promptTemplate': {
                        'textPromptTemplate': f"""{system_prompt}

Use the following context to answer the question. If the context doesn't contain the answer, say "I don't have information about this in the knowledge base."

Context:
$search_results$

Question: $query$

Answer:"""
                    },
                    'inferenceConfig': {
                        'textInferenceConfig': {
                            'temperature': 0.0,  # Deterministic generation
                            'maxTokens': 2000
                        }
                    }
                },
                'retrievalConfiguration': retrieval_config
                # Query decomposition DISABLED - causes inconsistent results for structured queries
                # 'orchestrationConfiguration': {
                #     'queryTransformationConfiguration': {
                #         'type': 'QUERY_DECOMPOSITION'
                #     }
                # }
            }
        }
        
        print(f"Knowledge Base ID: {KNOWLEDGE_BASE_ID}")
        print(f"Using enhanced query for retrieval: {enhanced_query}")
        
        response = bedrock_agent_runtime.retrieve_and_generate(
            input={
                'text': enhanced_query  # Use enhanced query with bill identifiers
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
                        'content': reference.get('content', {}).get('text', '')[:200] + '...',
                        'score': reference.get('score', 0)
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
        
        # UPDATED: Check if we have citations (not just sources)
        # Sometimes citations exist but retrievedReferences is empty
        has_citations = 'citations' in response and len(response['citations']) > 0
        
        if not has_citations:
            print("WARNING: No citations found - this might be a hallucinated response")
            return {
                'answer': "I couldn't find any relevant information in the knowledge base to answer your question. Please try rephrasing your query or ask about a different topic.",
                'sources': [],
                'entities': []
            }
        else:
            print(f"Found {len(response['citations'])} citations - proceeding with answer")
            # Even if sources is empty, we have citations, so the answer is valid
        
        return {
            'answer': answer,
            'sources': sources,
            'entities': entities
        }
        
    except Exception as e:
        # Log detailed error for debugging
        print(f"ERROR querying Knowledge Base: {type(e).__name__}: {str(e)}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        
        # Return user-friendly message (don't expose internal errors)
        return {
            'answer': "I'm sorry, I couldn't process your question at this time. Please try again in a moment. If the problem persists, try rephrasing your question.",
            'sources': [],
            'entities': [],
            'error': True  # Flag for frontend to handle differently
        }
