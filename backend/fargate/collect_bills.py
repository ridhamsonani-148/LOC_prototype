#!/usr/bin/env python3
"""
Fargate Task: Congress Bills Collector
Fetches bills from Congress API (1-16) and extracts text to S3
"""

import os
import sys
import json
import time
import boto3
import requests
from bs4 import BeautifulSoup
import PyPDF2
from io import BytesIO
from datetime import datetime

# Configuration
API_KEY = os.environ.get('CONGRESS_API_KEY', 'MThtRT5WkFu8I8CHOfiLLebG4nsnKcX3JnNv2N8A')
BUCKET_NAME = os.environ.get('BUCKET_NAME')
START_CONGRESS = int(os.environ.get('START_CONGRESS', '1'))
END_CONGRESS = int(os.environ.get('END_CONGRESS', '16'))
BILL_TYPES = os.environ.get('BILL_TYPES', 'hr,s').split(',')

# AWS clients
s3 = boto3.client('s3')

class BillCollector:
    def __init__(self):
        self.total_bills = 0
        self.successful = 0
        self.failed = 0
        self.errors = []
    
    def log(self, message):
        """Log with timestamp"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {message}")
        sys.stdout.flush()
    
    def extract_text_from_url(self, url, format_type):
        """Extract text based on format type"""
        try:
            if format_type == "Plain Text":
                # Best case - direct text
                self.log(f"  Downloading plain text from: {url}")
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                return response.text
            
            elif format_type == "HTML" or format_type == "Formatted Text":
                # Extract from HTML
                self.log(f"  Extracting text from HTML: {url}")
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Remove scripts, styles, and navigation
                for element in soup(["script", "style", "nav", "header", "footer"]):
                    element.decompose()
                
                # Extract clean text
                text = soup.get_text(separator='\n', strip=True)
                # Clean up multiple newlines
                text = '\n'.join(line for line in text.split('\n') if line.strip())
                return text
            
            elif format_type == "PDF":
                # Extract from PDF
                self.log(f"  Extracting text from PDF: {url}")
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                pdf_file = BytesIO(response.content)
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                
                text = ""
                for page_num, page in enumerate(pdf_reader.pages):
                    text += f"\n--- Page {page_num + 1} ---\n"
                    text += page.extract_text() + "\n"
                
                return text
            
            else:
                self.log(f"  Unsupported format: {format_type}")
                return None
                
        except Exception as e:
            self.log(f"  Error extracting from {url}: {str(e)}")
            return None
    
    def get_bill_text(self, congress_num, bill_type, bill_number):
        """Get bill text from Congress API"""
        try:
            # Get text versions
            text_url = f"https://api.congress.gov/v3/bill/{congress_num}/{bill_type}/{bill_number}/text"
            params = {'api_key': API_KEY, 'format': 'json'}
            
            self.log(f"  Fetching text versions from: {text_url}")
            response = requests.get(text_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if 'textVersions' not in data or not data['textVersions']:
                self.log(f"  No text versions available")
                return None
            
            # Get the first (latest) text version
            text_version = data['textVersions'][0]
            formats = text_version.get('formats', [])
            
            if not formats:
                self.log(f"  No formats available")
                return None
            
            # Priority: Plain Text > HTML > PDF
            text_content = None
            
            # Try Plain Text first
            for fmt in formats:
                if fmt.get('type') == 'Plain Text':
                    text_content = self.extract_text_from_url(fmt['url'], 'Plain Text')
                    if text_content:
                        return text_content
            
            # Try HTML/Formatted Text
            for fmt in formats:
                if fmt.get('type') in ['HTML', 'Formatted Text']:
                    text_content = self.extract_text_from_url(fmt['url'], 'HTML')
                    if text_content:
                        return text_content
            
            # Try PDF as last resort
            for fmt in formats:
                if fmt.get('type') == 'PDF':
                    text_content = self.extract_text_from_url(fmt['url'], 'PDF')
                    if text_content:
                        return text_content
            
            return None
            
        except Exception as e:
            self.log(f"  Error getting bill text: {str(e)}")
            return None
    
    def save_to_s3(self, congress_num, bill_type, bill_number, text_content, metadata):
        """Save extracted text to S3"""
        try:
            # Create metadata header
            header = f"""# Congress {congress_num} - {bill_type.upper()} {bill_number}
# Title: {metadata.get('title', 'N/A')}
# Introduced: {metadata.get('introducedDate', 'N/A')}
# Latest Action: {metadata.get('latestAction', {}).get('text', 'N/A')}
# Latest Action Date: {metadata.get('latestAction', {}).get('actionDate', 'N/A')}

---

"""
            full_content = header + text_content
            
            # Save to S3
            key = f"extracted/congress_{congress_num}/{bill_type}_{bill_number}.txt"
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key=key,
                Body=full_content.encode('utf-8'),
                ContentType='text/plain',
                Metadata={
                    'congress': str(congress_num),
                    'bill_type': bill_type,
                    'bill_number': str(bill_number),
                    'title': metadata.get('title', '')[:1024]  # S3 metadata limit
                }
            )
            
            self.log(f"  ✓ Saved to S3: {key}")
            return True
            
        except Exception as e:
            self.log(f"  ✗ Error saving to S3: {str(e)}")
            return False
    
    def collect_bills_for_congress(self, congress_num, bill_type):
        """Collect all bills for a specific Congress and bill type"""
        self.log(f"\n{'='*60}")
        self.log(f"Processing Congress {congress_num} - {bill_type.upper()} bills")
        self.log(f"{'='*60}")
        
        try:
            # Get list of bills
            bills_url = f"https://api.congress.gov/v3/bill/{congress_num}/{bill_type}"
            params = {'api_key': API_KEY, 'format': 'json', 'limit': 250}
            
            self.log(f"Fetching bills from: {bills_url}")
            response = requests.get(bills_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            bills = data.get('bills', [])
            
            if not bills:
                self.log(f"No {bill_type.upper()} bills found in Congress {congress_num}")
                return
            
            self.log(f"Found {len(bills)} {bill_type.upper()} bills")
            
            for idx, bill in enumerate(bills, 1):
                bill_number = bill.get('number')
                bill_title = bill.get('title', 'N/A')[:100]
                
                self.log(f"\n[{idx}/{len(bills)}] Processing {bill_type.upper()} {bill_number}")
                self.log(f"  Title: {bill_title}...")
                
                self.total_bills += 1
                
                # Get bill text
                text_content = self.get_bill_text(congress_num, bill_type, bill_number)
                
                if text_content:
                    # Save to S3
                    metadata = {
                        'title': bill.get('title', ''),
                        'introducedDate': bill.get('introducedDate', ''),
                        'latestAction': bill.get('latestAction', {})
                    }
                    
                    if self.save_to_s3(congress_num, bill_type, bill_number, text_content, metadata):
                        self.successful += 1
                    else:
                        self.failed += 1
                        self.errors.append(f"Congress {congress_num} {bill_type} {bill_number}: Save failed")
                else:
                    self.log(f"  ✗ No text content available")
                    self.failed += 1
                    self.errors.append(f"Congress {congress_num} {bill_type} {bill_number}: No text")
                
                # Rate limiting - be nice to the API
                time.sleep(0.5)
            
        except Exception as e:
            self.log(f"Error processing Congress {congress_num} {bill_type}: {str(e)}")
            self.errors.append(f"Congress {congress_num} {bill_type}: {str(e)}")
    
    def run(self):
        """Main execution"""
        self.log("="*60)
        self.log("Congress Bills Collector - Starting")
        self.log("="*60)
        self.log(f"Configuration:")
        self.log(f"  S3 Bucket: {BUCKET_NAME}")
        self.log(f"  Congress Range: {START_CONGRESS} to {END_CONGRESS}")
        self.log(f"  Bill Types: {', '.join(BILL_TYPES)}")
        self.log("="*60)
        
        start_time = time.time()
        
        # Collect bills for each Congress
        for congress_num in range(START_CONGRESS, END_CONGRESS + 1):
            for bill_type in BILL_TYPES:
                self.collect_bills_for_congress(congress_num, bill_type.strip())
        
        # Summary
        elapsed_time = time.time() - start_time
        
        self.log("\n" + "="*60)
        self.log("Collection Complete!")
        self.log("="*60)
        self.log(f"Total Bills Processed: {self.total_bills}")
        self.log(f"Successful: {self.successful}")
        self.log(f"Failed: {self.failed}")
        self.log(f"Time Elapsed: {elapsed_time:.2f} seconds ({elapsed_time/60:.2f} minutes)")
        
        if self.errors:
            self.log(f"\nErrors ({len(self.errors)}):")
            for error in self.errors[:10]:  # Show first 10 errors
                self.log(f"  - {error}")
            if len(self.errors) > 10:
                self.log(f"  ... and {len(self.errors) - 10} more")
        
        # Save summary to S3
        summary = {
            'total_bills': self.total_bills,
            'successful': self.successful,
            'failed': self.failed,
            'elapsed_seconds': elapsed_time,
            'congress_range': f"{START_CONGRESS}-{END_CONGRESS}",
            'bill_types': BILL_TYPES,
            'timestamp': datetime.now().isoformat(),
            'errors': self.errors
        }
        
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key='collection_summary.json',
            Body=json.dumps(summary, indent=2),
            ContentType='application/json'
        )
        
        self.log(f"\nSummary saved to s3://{BUCKET_NAME}/collection_summary.json")
        
        return 0 if self.failed == 0 else 1

if __name__ == '__main__':
    if not BUCKET_NAME:
        print("ERROR: BUCKET_NAME environment variable not set")
        sys.exit(1)
    
    collector = BillCollector()
    exit_code = collector.run()
    sys.exit(exit_code)
