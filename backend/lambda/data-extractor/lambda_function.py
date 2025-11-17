"""
Data Extractor Lambda Function
Extracts structured data from newspaper images using AWS Bedrock
"""

import json
import os
import boto3
import requests
import base64
from io import BytesIO
from PIL import Image
from datetime import datetime

s3_client = boto3.client('s3')
bedrock_runtime = boto3.client('bedrock-runtime')

DATA_BUCKET = os.environ['DATA_BUCKET']
BEDROCK_MODEL_ID = os.environ['BEDROCK_MODEL_ID']

def lambda_handler(event, context):
    """
    Extract data from newspaper images using Bedrock
    
    Event format:
    {
        "bucket": "bucket-name",
        "s3_key": "images/image_list_xxx.json",
        "images": [...]  # Optional: direct image list
    }
    """
    print(f"Event: {json.dumps(event)}")
    
    # Get images from S3 or event
    if 'images' in event and event['images']:
        images = event['images']
    else:
        s3_key = event.get('s3_key')
        bucket = event.get('bucket', DATA_BUCKET)
        
        response = s3_client.get_object(Bucket=bucket, Key=s3_key)
        images = json.loads(response['Body'].read().decode('utf-8'))
    
    print(f"Processing {len(images)} images")
    
    # Process each image
    results = []
    for i, image_record in enumerate(images[:5]):  # Limit to 5 for Lambda timeout
        print(f"Processing image {i+1}/{len(images[:5])}: {image_record.get('title', 'Unknown')}")
        
        try:
            # Download and process image
            image_bytes = download_image(image_record['image_url'])
            if not image_bytes:
                continue
            
            # Extract data using Bedrock
            extracted_data = extract_data_from_image(image_bytes)
            
            result = {
                'page_id': image_record['page_id'],
                'date': image_record['date'],
                'title': image_record['title'],
                'extraction': extracted_data,
                'processed_at': datetime.now().isoformat()
            }
            
            results.append(result)
            
        except Exception as e:
            print(f"Error processing image {i+1}: {e}")
            continue
    
    # Save results to S3
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_key = f"extracted/extraction_results_{timestamp}.json"
    
    s3_client.put_object(
        Bucket=DATA_BUCKET,
        Key=output_key,
        Body=json.dumps(results, indent=2),
        ContentType='application/json'
    )
    
    print(f"Saved {len(results)} extraction results to s3://{DATA_BUCKET}/{output_key}")
    
    return {
        'statusCode': 200,
        'processed_count': len(results),
        's3_key': output_key,
        'bucket': DATA_BUCKET,
        'results': results
    }


def download_image(image_url: str, max_size: tuple = (2048, 2048)) -> bytes:
    """Download and prepare image for Bedrock"""
    try:
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        
        # Open and resize image
        img = Image.open(BytesIO(response.content))
        
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Convert to JPEG bytes
        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=85)
        return buffer.getvalue()
        
    except Exception as e:
        print(f"Error downloading image {image_url}: {e}")
        return None


def extract_data_from_image(image_bytes: bytes) -> dict:
    """Extract structured data using Bedrock"""
    
    extraction_prompt = """Analyze this historical newspaper page and extract:

{
  "newspaper_name": "Name of the newspaper",
  "publication_date": "Date if visible",
  "headlines": ["Major headlines"],
  "articles": [
    {
      "headline": "Article headline",
      "summary": "Brief summary",
      "location": "Location mentioned"
    }
  ],
  "people_mentioned": ["Names of people"],
  "locations_mentioned": ["Geographic locations"],
  "organizations_mentioned": ["Organizations"],
  "events_mentioned": ["Historical events"],
  "advertisements": ["Products/services advertised"]
}

Return only valid JSON."""
    
    # Encode image
    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
    
    # Prepare request
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": extraction_prompt
                    }
                ]
            }
        ]
    }
    
    # Invoke Bedrock
    response = bedrock_runtime.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(request_body)
    )
    
    response_body = json.loads(response['body'].read())
    
    # Extract JSON from response
    content = response_body['content'][0]['text']
    
    # Try to parse JSON
    try:
        # Find JSON in response
        start = content.find('{')
        end = content.rfind('}') + 1
        if start >= 0 and end > start:
            json_str = content[start:end]
            return json.loads(json_str)
        else:
            return {'raw_response': content}
    except:
        return {'raw_response': content}
