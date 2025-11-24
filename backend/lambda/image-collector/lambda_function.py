"""
Data Collector Lambda Function
Fetches data from multiple sources:
- Newspaper images from LOC.gov API
- Congress bills from Congress.gov API
"""

import json
import os
import boto3
import requests
from datetime import datetime
from typing import List, Dict, Any

s3_client = boto3.client('s3')
DATA_BUCKET = os.environ['DATA_BUCKET']
CONGRESS_API_KEY = os.environ.get('CONGRESS_API_KEY', 'MThtRT5WkFu8I8CHOfiLLebG4nsnKcX3JnNv2N8A')

def lambda_handler(event, context):
    """
    Collect data from various sources
    
    Event format for newspapers:
    {
        "source": "newspapers",  # or omit for backward compatibility
        "start_date": "1815-08-01",
        "end_date": "1815-08-31",
        "max_pages": 10
    }
    
    Event format for Congress bills:
    {
        "source": "congress",
        "congress": 118,
        "bill_type": "hr",
        "limit": 10
    }
    """
    print(f"Event: {json.dumps(event)}")
    
    # Determine source
    source = event.get('source', 'newspapers')  # Default to newspapers for backward compatibility
    
    if source == 'congress':
        return handle_congress_bills(event)
    else:
        return handle_newspapers(event)


def handle_newspapers(event):
    """Handle newspaper image collection (original functionality)"""
    start_date = event.get('start_date', '1815-08-01')
    end_date = event.get('end_date', '1815-08-31')
    max_pages = event.get('max_pages', 10)
    
    print(f"Collecting newspaper images from {start_date} to {end_date}, max {max_pages} pages")
    
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


def handle_congress_bills(event):
    """Handle Congress bills collection"""
    congress = event.get('congress', 118)
    bill_type = event.get('bill_type', 'hr')
    limit = event.get('limit', 10)
    
    print(f"Collecting {limit} bills from Congress {congress}, type: {bill_type}")
    
    # Fetch bills
    bills = fetch_congress_bills(congress, bill_type, limit)
    
    if not bills:
        print("WARNING: No bills collected!")
        return {
            'statusCode': 200,
            'documents_count': 0,
            's3_key': None,
            'bucket': DATA_BUCKET
        }
    
    # Convert bills to Neptune-compatible format directly
    documents = []
    for bill in bills:
        doc = convert_bill_to_document(bill)
        if doc:
            documents.append(doc)
    
    # Save to S3
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    s3_key = f"congress-bills/{congress}/bills_{timestamp}.json"
    
    s3_client.put_object(
        Bucket=DATA_BUCKET,
        Key=s3_key,
        Body=json.dumps(documents, indent=2),
        ContentType='application/json'
    )
    
    print(f"Saved {len(documents)} bills to s3://{DATA_BUCKET}/{s3_key}")
    
    return {
        'statusCode': 200,
        'documents_count': len(documents),
        's3_key': s3_key,
        'bucket': DATA_BUCKET
    }


def fetch_congress_bills(congress: int, bill_type: str, limit: int) -> List[Dict]:
    """Fetch bills from Congress.gov API"""
    base_url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}"
    
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json',
        'limit': min(limit, 20)  # API limit per request
    }
    
    print(f"Fetching bills from: {base_url}")
    response = requests.get(base_url, params=params, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    bills_list = data.get('bills', [])
    print(f"Found {len(bills_list)} bills")
    
    # Fetch detailed information for each bill
    detailed_bills = []
    for bill in bills_list[:limit]:
        try:
            bill_number = bill['number']
            detail = fetch_bill_detail(congress, bill_type, bill_number)
            if detail:
                detailed_bills.append(detail)
        except Exception as e:
            print(f"Error fetching detail for bill {bill.get('number')}: {e}")
            continue
    
    return detailed_bills


def fetch_bill_detail(congress: int, bill_type: str, bill_number: int) -> Dict:
    """Fetch detailed information for a specific bill including full text"""
    url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json'
    }
    
    print(f"Fetching bill detail: {congress}/{bill_type}/{bill_number}")
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    bill = data.get('bill', {})
    
    # Fetch full bill text if available
    bill_text = fetch_bill_text(congress, bill_type, bill_number)
    if bill_text:
        bill['full_text'] = bill_text
    
    return bill


def fetch_bill_text(congress: int, bill_type: str, bill_number: int) -> str:
    """
    Fetch full bill text from text versions endpoint
    Tries to get plain text format first, falls back to PDF if needed
    """
    url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}/text"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json'
    }
    
    try:
        print(f"Fetching bill text versions for {congress}/{bill_type}/{bill_number}")
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        text_versions = data.get('textVersions', [])
        
        if not text_versions:
            print(f"No text versions available for bill {bill_number}")
            return None
        
        # Get the first (most recent) text version
        latest_version = text_versions[0]
        formats = latest_version.get('formats', [])
        
        print(f"Found {len(formats)} format(s) for bill text")
        
        # Try to find plain text format first
        text_url = None
        pdf_url = None
        
        for fmt in formats:
            fmt_type = fmt.get('type', '').lower()
            fmt_url = fmt.get('url', '')
            
            if 'text' in fmt_type or 'txt' in fmt_type:
                text_url = fmt_url
                print(f"Found plain text format: {text_url}")
                break
            elif 'pdf' in fmt_type:
                pdf_url = fmt_url
        
        # Fetch plain text if available
        if text_url:
            print(f"Downloading plain text from: {text_url}")
            text_response = requests.get(text_url, timeout=60)
            text_response.raise_for_status()
            bill_text = text_response.text
            print(f"Downloaded bill text: {len(bill_text)} characters")
            return bill_text
        
        # If no plain text, note that PDF is available
        if pdf_url:
            print(f"Only PDF format available: {pdf_url}")
            print("PDF extraction not implemented yet - will use summary instead")
            return None
        
        print("No suitable text format found")
        return None
        
    except Exception as e:
        print(f"Error fetching bill text: {e}")
        return None


def convert_bill_to_document(bill: Dict) -> Dict:
    """
    Convert a Congress bill to Neptune document format
    This creates a document that neptune-loader can directly process
    """
    try:
        congress = bill.get('congress', 'unknown')
        bill_type = bill.get('type', 'unknown')
        bill_number = bill.get('number', 'unknown')
        bill_id = f"{congress}-{bill_type}-{bill_number}"
        
        # Build comprehensive text content
        text_parts = []
        
        # Title
        if bill.get('title'):
            text_parts.append(f"Bill Title: {bill['title']}")
        
        # Get short title from titles array
        titles = bill.get('titles', [])
        short_title = None
        for title_obj in titles:
            if title_obj.get('titleType') == 'Short Title(s) as Introduced':
                short_title = title_obj.get('title')
                break
        
        if short_title:
            text_parts.append(f"Short Title: {short_title}")
        
        # Bill identification
        text_parts.append(f"Bill ID: {bill_id}")
        
        # Dates
        if bill.get('introducedDate'):
            text_parts.append(f"Introduced: {bill['introducedDate']}")
        
        # Latest action
        latest_action = bill.get('latestAction', {})
        if latest_action.get('text'):
            text_parts.append(f"Latest Action: {latest_action['text']}")
            if latest_action.get('actionDate'):
                text_parts.append(f"Latest Action Date: {latest_action['actionDate']}")
        
        # Sponsors
        sponsors = bill.get('sponsors', [])
        if sponsors:
            sponsor_names = [s.get('fullName', '') for s in sponsors if s.get('fullName')]
            if sponsor_names:
                text_parts.append(f"Sponsors: {', '.join(sponsor_names)}")
        
        # Cosponsors
        cosponsors = bill.get('cosponsors', {})
        if cosponsors.get('count'):
            text_parts.append(f"Cosponsors: {cosponsors['count']}")
        
        # Committees
        committees = bill.get('committees', [])
        if committees:
            committee_names = [c.get('name', '') for c in committees if c.get('name')]
            if committee_names:
                text_parts.append(f"Committees: {', '.join(committee_names)}")
        
        # Subjects/Policy Areas
        subjects_data = bill.get('subjects', {})
        policy_area = subjects_data.get('policyArea', {}).get('name')
        if policy_area:
            text_parts.append(f"Policy Area: {policy_area}")
        
        legislative_subjects = subjects_data.get('legislativeSubjects', [])
        if legislative_subjects:
            subject_names = [s.get('name', '') for s in legislative_subjects if s.get('name')]
            if subject_names:
                text_parts.append(f"Legislative Subjects: {', '.join(subject_names[:5])}")  # Limit to 5
        
        # Full bill text (if available)
        if bill.get('full_text'):
            text_parts.append(f"\n{'='*60}")
            text_parts.append("FULL BILL TEXT:")
            text_parts.append('='*60)
            text_parts.append(bill['full_text'])
            print(f"Using full bill text ({len(bill['full_text'])} chars)")
        else:
            # Fallback to summary if full text not available
            summaries = bill.get('summaries', [])
            if summaries and summaries[0].get('text'):
                text_parts.append(f"\nSummary:\n{summaries[0]['text']}")
                print("Using bill summary (full text not available)")
        
        # Combine all text
        full_text = '\n'.join(text_parts)
        
        # Create document in Neptune-compatible format
        document = {
            'text': full_text,
            'page_id': bill_id,
            'title': short_title or bill.get('title', bill_id),
            'date': bill.get('introducedDate', ''),
            'page_number': 1,
            'metadata': {
                'source': 'congress.gov',
                'congress': congress,
                'bill_type': bill_type,
                'bill_number': bill_number,
                'url': bill.get('url', ''),
                'latest_action_date': latest_action.get('actionDate', ''),
                'cosponsors_count': cosponsors.get('count', 0)
            }
        }
        
        return document
        
    except Exception as e:
        print(f"Error converting bill: {e}")
        return None
