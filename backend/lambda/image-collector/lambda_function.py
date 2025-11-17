"""
Image Collector Lambda Function
Fetches newspaper images from NEW LOC.gov API
API: https://www.loc.gov/collections/chronicling-america/
"""

import json
import os
import boto3
import requests
from datetime import datetime
from typing import List, Dict, Any

s3_client = boto3.client('s3')
DATA_BUCKET = os.environ['DATA_BUCKET']

def lambda_handler(event, context):
    """
    Collect newspaper image URLs from NEW LOC.gov API
    
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
    
    # Fetch images from NEW LOC API
    images = fetch_loc_images(start_date, end_date, max_pages)
    
    print(f"Collected {len(images)} images")
    
    if not images:
        print("WARNING: No images collected!")
        return {
            'statusCode': 200,
            'image_count': 0,
            's3_key': None,
            'bucket': DATA_BUCKET,
            'images': []
        }
    
    # Save to S3
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    s3_key = f"images/image_list_{timestamp}.json"
    
    image_data = {
        'collected_at': datetime.utcnow().isoformat(),
        'time_period': f"{start_date} to {end_date}",
        'total_images': len(images),
        'images': images
    }
    
    s3_client.put_object(
        Bucket=DATA_BUCKET,
        Key=s3_key,
        Body=json.dumps(image_data, indent=2),
        ContentType='application/json'
    )
    
    print(f"Saved image list to s3://{DATA_BUCKET}/{s3_key}")
    
    return {
        'statusCode': 200,
        'image_count': len(images),
        's3_key': s3_key,
        'bucket': DATA_BUCKET,
        'images': images  # Pass all images to next step
    }


def fetch_loc_images(start_date: str, end_date: str, max_pages: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch newspaper images from NEW LOC.gov API
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        max_pages: Maximum number of pages to fetch
        
    Returns:
        List of image records with IIIF URLs
    """
    base_url = "https://www.loc.gov/collections/chronicling-america/"
    
    # Extract years from dates
    start_year = start_date.split('-')[0]
    end_year = end_date.split('-')[0]
    
    images = []
    page = 1
    
    print(f"Searching for newspapers from {start_year} to {end_year}")
    
    while page <= max_pages:
        params = {
            'dl': 'page',
            'dates': f"{start_year}/{end_year}",
            'fo': 'json',
            'c': 100,  # results per page
            'sp': page
        }
        
        try:
            print(f"Fetching page {page} from NEW LOC API...")
            response = requests.get(base_url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            results = data.get('results', [])
            
            if not results:
                print(f"No more results found at page {page}")
                break
            
            print(f"Processing {len(results)} results from page {page}")
            
            for item in results:
                try:
                    # Get page_id from item's id field
                    page_id = item.get('id', 'Unknown')
                    
                    # Get title
                    title = item.get('title', 'Unknown')
                    
                    # Get date
                    date = item.get('date', 'Unknown')
                    
                    # Get IIIF image URL (highest resolution)
                    image_url_field = item.get('image_url')
                    iiif_url = None
                    
                    if isinstance(image_url_field, list):
                        # API returns array of URLs - find IIIF URL
                        for url in image_url_field:
                            if isinstance(url, str) and 'iiif' in url and '.jpg' in url:
                                iiif_url = url
                                break
                    elif isinstance(image_url_field, str):
                        # Direct string URL
                        if 'iiif' in image_url_field and '.jpg' in image_url_field:
                            iiif_url = image_url_field
                    
                    if not iiif_url:
                        print(f"No IIIF URL found for {page_id}")
                        continue
                    
                    image_record = {
                        'page_id': page_id,
                        'title': title,
                        'date': date,
                        'image_url': iiif_url,
                        'newspaper': title.split(',')[0] if title else 'Unknown'
                    }
                    
                    images.append(image_record)
                    
                except Exception as e:
                    print(f"Error processing item: {e}")
                    continue
            
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
    
    print(f"Total unique images collected: {len(unique_images)}")
    return unique_images
