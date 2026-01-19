import requests
from bs4 import BeautifulSoup
import datetime
import os
import re
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Source URL
BASE_URL = "https://allinonereborn.xyz/sony"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://allinonereborn.xyz/sony/",
    "Origin": "https://allinonereborn.xyz"
}

# Configuration
MAX_THREADS = 10  # Check 10 channels at once
TIMEOUT = 15      # Seconds to wait for a response

# Directories
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLAYLIST_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), 'playlist')
os.makedirs(PLAYLIST_DIR, exist_ok=True)
OUTPUT_FILE = os.path.join(PLAYLIST_DIR, "sony_liv.m3u")

# Create a robust session with retry logic
session = requests.Session()
session.headers.update(HEADERS)
adapter = requests.adapters.HTTPAdapter(max_retries=3)
session.mount('https://', adapter)
session.mount('http://', adapter)

def get_channel_links():
    """Scrapes the main page for all available channel sub-pages."""
    try:
        print(f"Fetching main page: {BASE_URL}")
        response = session.get(BASE_URL, timeout=TIMEOUT)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        links = soup.find_all('a', href=True)
        channel_pages = []
        
        for link in links:
            href = link['href']
            name = link.get_text(strip=True)
            
            # Target specifically the player pages
            if 'ptest.php' in href:
                if not name:
                    name = "Sony Liv Channel"
                
                if href.startswith('http'):
                    full_url = href
                else:
                    full_url = "https://allinonereborn.xyz/sony/" + href
                
                channel_pages.append({'name': name, 'page_url': full_url})
        
        # Remove duplicates based on URL
        unique_pages = {v['page_url']: v for v in channel_pages}.values()
        print(f"Found {len(unique_pages)} unique channel pages.")
        return list(unique_pages)
        
    except Exception as e:
        print(f"Error fetching channel list: {e}")
        return []

def process_channel(page_info):
    """
    Worker function:
    1. Visits the channel page.
    2. Extracts the M3U8 link.
    3. Validates if the M3U8 is actually live (HTTP 200).
    """
    page_url = page_info['page_url']
    name = page_info['name']
    
    try:
        response = session.get(page_url, timeout=10)
        
        if response.status_code != 200:
            return None

        # Extraction Logic
        m3u8 = None
        logo = None

        # Regex for JSON data (Most reliable)
        match = re.search(r'const\s+channelData\s*=\s*({.*?});', response.text)
        if match:
            try:
                data = json.loads(match.group(1))
                m3u8 = data.get('m3u8')
                logo = data.get('logo') or data.get('image') or data.get('poster')
            except:
                pass

        # Fallback Regex
        if not m3u8:
            m3u8_match = re.search(r'"m3u8"\s*:\s*"(.*?)"', response.text)
            if m3u8_match:
                m3u8 = m3u8_match.group(1).replace(r'\/', '/')

        if not logo:
             logo_match = re.search(r'"(logo|image|poster)"\s*:\s*"(.*?)"', response.text)
             if logo_match:
                 logo = logo_match.group(2).replace(r'\/', '/')

        # VALIDATION STEP: Check if the stream is actually working
        if m3u8 and m3u8.startswith('http'):
            # Quick HEAD request to check if stream is live
            try:
                stream_check = session.head(m3u8, timeout=5)
                if stream_check.status_code < 400: # 200, 301, 302 are all "working"
                    return {
                        'name': name,
                        'url': m3u8,
                        'logo': logo or ""
                    }
            except:
                # If HEAD fails, sometimes GET works (some servers block HEAD)
                pass 
                
            # Second try with GET (just headers) if HEAD failed
            try:
                 stream_check = session.get(m3u8, stream=True, timeout=5)
                 if stream_check.status_code < 400:
                     stream_check.close()
                     return {
                        'name': name,
                        'url': m3u8,
                        'logo': logo or ""
                    }
            except:
                pass

        return None

    except Exception as e:
        return None

def get_working_channels():
    pages = get_channel_links()
    valid_channels = []
    
    print(f"Validating {len(pages)} channels using {MAX_THREADS} threads...")
    
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        # Submit all tasks
        future_to_channel = {executor.submit(process_channel, page): page for page in pages}
        
        completed_count = 0
        for future in as_completed(future_to_channel):
            completed_count += 1
            result = future.result()
            
            # Print progress every 5 channels or when found
            if result:
                print(f"  [✓] Working: {result['name']}")
                valid_channels.append(result)
            else:
                # Optional: Uncomment to see failed channels
                # page_data = future_to_channel[future]
                # print(f"  [x] Dead/Offline: {page_data['name']}")
                pass
                
            if completed_count % 5 == 0:
                print(f"      Progress: {completed_count}/{len(pages)}")

    return valid_channels

def generate_m3u(channels):
    # Timezone-aware timestamp
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    bd_time = utc_now + datetime.timedelta(hours=6) # Adjust timezone here if needed
    formatted_time = bd_time.strftime("%Y-%m-%d %I:%M %p")

    m3u_header = f"""#EXTM3U
#=================================
# Developed By: OMNIX EMPIER
# Playlist: Sony Liv (Auto-Generated)
# Last Updated: {formatted_time} (BD Time)
# Working Channels: {len(channels)}
#=================================
"""
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(m3u_header + '\n')
        
        # Global Headers
        f.write('#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36\n')
        f.write('http://example.com/status\n\n')
        
        # Sort channels alphabetically by name
        channels.sort(key=lambda x: x['name'])

        for channel in channels:
            name = channel['name']
            url = channel['url']
            logo = channel['logo']
            
            f.write(f'#EXTINF:-1 group-title="Sony Liv" tvg-logo="{logo}",{name}\n')
            f.write('#EXTVLCOPT:network-caching=1000\n')
            f.write(f'#EXTVLCOPT:http-user-agent={HEADERS["User-Agent"]}\n')
            f.write(f'#EXTVLCOPT:http-referrer={HEADERS["Referer"]}\n')
            f.write(f'{url}\n\n')
            
    print(f"\nSuccess! Generated: {OUTPUT_FILE}")
    print(f"Total Working Channels: {len(channels)}")

if __name__ == "__main__":
    start_time = time.time()
    
    print("--- Starting Sony Liv Scraper ---")
    channels = get_working_channels()
    
    if channels:
        generate_m3u(channels)
    else:
        print("No working channels found.")
        
    print(f"--- Finished in {round(time.time() - start_time, 2)} seconds ---")
