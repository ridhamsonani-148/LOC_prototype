"""
Image Collector Lambda Function
Fetches newspaper images from Chronicling America API
"""

import json
import os
import boto3
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any

s3_client = boto3.client('s3')
DATA_BUCKET = os.environ['DATA_BUCKET']

def lambda_handler(event, context):
    """
    Collect newspaper images from Chronicling America API
    
    Event format:
    {
        "start_date": "1815-08-01",
        "end_date": "1815-08-31",
        "max_pages": 10
    }
    """
    print(f"Event: {json.dumps(event)}")
    
    start_date = event.get('start_date', '1815-08-01')
    end_date = event.get('end_date', '1815-08-31')
    max_pages = event.get('max_pages', 10)
    
    print(f"Collecting images from {start_date} to {end_date}, max {max_pages} pages")
    
    # Fetch images from API
    images = fetch_chronicling_america_images(start_date, end_date, max_pages)
    
    print(f"Collected {len(images)} images")
    
    # Save to S3
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    s3_key = f"images/image_list_{timestamp}.json"
    
    s3_client.put_object(
        Bucket=DATA_BUCKET,
        Key=s3_key,
        Body=json.dumps(images, indent=2),
        ContentType='application/json'
    )
    
    print(f"Saved image list to s3://{DATA_BUCKET}/{s3_key}")
    
    return {
        'statusCode': 200,
        'image_count': len(images),
        's3_key': s3_key,
        'bucket': DATA_BUCKET,
        'images': images[:5]  # Pass first 5 images to next step
    }


def fetch_chronicling_america_images(start_date: str, end_date: str, max_pages: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch newspaper images from Chronicling America API
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        max_pages: Maximum number of pages to fetch
        
    Returns:
        List of image records
    """
    base_url = "https://chroniclingamerica.loc.gov/search/pages/results/"
    
    images = []
    page = 1
    
    while page <= max_pages:
        params = {
            'dateFilterType': 'range',
            'date1': start_date,
            'date2': end_date,
            'format': 'json',
            'page': page
        }
        
        try:
            print(f"Fetching page {page}...")
            response = requests.get(base_url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            items = data.get('items', [])
            
            if not items:
                print(f"No more items found at page {page}")
                break
            
            for item in items:
                # Extract high-resolution image URL
                image_url = item.get('id', '').replace('.json', '/full/pct:12.5/0/default.jpg')
                
                if image_url:
                    images.append({
                        'page_id': item.get('id', ''),
                        'title': item.get('title', ''),
                        'date': item.get('date', ''),
                        'image_url': image_url,
                        'newspaper': item.get('title', '').split(',')[0] if item.get('title') else '',
                    })
            
            page += 1
            
        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            break
    
    # Deduplicate by page_id
    seen = set()
    unique_images = []
    for img in images:
        if img['page_id'] not in seen:
            seen.add(img['page_id'])
            unique_images.append(img)
    
    return unique_images
