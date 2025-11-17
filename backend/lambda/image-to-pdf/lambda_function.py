"""
Image to PDF Converter Lambda
Converts downloaded newspaper images to a single PDF for Bedrock Data Automation
"""

import json
import os
import boto3
from io import BytesIO
from PIL import Image
from datetime import datetime
from typing import List, Dict, Any

s3_client = boto3.client('s3')
DATA_BUCKET = os.environ['DATA_BUCKET']

def lambda_handler(event, context):
    """
    Convert images to PDF
    
    Input from previous step:
    {
        "image_count": 10,
        "s3_key": "images/image_list_20231117_120000.json",
        "bucket": "bucket-name",
        "images": [...]
    }
    """
    print(f"Event: {json.dumps(event)}")
    
    bucket = event.get('bucket', DATA_BUCKET)
    images = event.get('images', [])
    
    if not images:
        print("No images to process")
        return {
            'statusCode': 400,
            'error': 'No images provided'
        }
    
    print(f"Converting {len(images)} images to PDF...")
    
    # Download and convert images
    pil_images = []
    for i, image_record in enumerate(images, 1):
        try:
            image_url = image_record.get('image_url')
            page_id = image_record.get('page_id', f'page_{i}')
            
            print(f"  [{i}/{len(images)}] Downloading {page_id}...")
            
            # Download image from IIIF URL
            import requests
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()
            
            # Open with PIL
            img = Image.open(BytesIO(response.content))
            
            # Convert to RGB if needed (PDFs need RGB)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            pil_images.append(img)
            
        except Exception as e:
            print(f"  Error processing image {i}: {e}")
            continue
    
    if not pil_images:
        return {
            'statusCode': 500,
            'error': 'Failed to download any images'
        }
    
    print(f"Successfully loaded {len(pil_images)} images")
    
    # Create PDF
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    pdf_key = f"pdfs/newspaper_{timestamp}.pdf"
    
    print(f"Creating PDF: {pdf_key}")
    
    # Save to BytesIO
    pdf_buffer = BytesIO()
    
    # Save first image as PDF, append rest
    if len(pil_images) == 1:
        pil_images[0].save(pdf_buffer, format='PDF')
    else:
        pil_images[0].save(
            pdf_buffer,
            format='PDF',
            save_all=True,
            append_images=pil_images[1:]
        )
    
    pdf_buffer.seek(0)
    
    # Upload to S3
    s3_client.put_object(
        Bucket=bucket,
        Key=pdf_key,
        Body=pdf_buffer.getvalue(),
        ContentType='application/pdf'
    )
    
    print(f"✓ PDF uploaded to s3://{bucket}/{pdf_key}")
    print(f"  Pages: {len(pil_images)}")
    print(f"  Size: {len(pdf_buffer.getvalue())} bytes")
    
    return {
        'statusCode': 200,
        'pdf_key': pdf_key,
        'pdf_s3_uri': f"s3://{bucket}/{pdf_key}",
        'bucket': bucket,
        'page_count': len(pil_images),
        'images': images  # Pass through for reference
    }
