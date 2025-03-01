#!/usr/bin/env python3
import yt_dlp
import os
import sqlite3
import json
import requests
from datetime import datetime
from pathlib import Path
from tqdm import tqdm
from random import choice
import random
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def init_db():
    os.makedirs('data', exist_ok=True)
    conn = sqlite3.connect('data/downloads.db')
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS downloads (
        video_id TEXT PRIMARY KEY,
        title TEXT,
        channel TEXT,
        download_date TEXT,
        audio_path TEXT,
        metadata TEXT
    )
    ''')
    conn.commit()
    return conn

class ProgressHook:
    def __init__(self):
        self.pbar = None

    def __call__(self, d):
        if d['status'] == 'downloading':
            if self.pbar is None:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                self.pbar = tqdm(total=total, unit='B', unit_scale=True, desc='Downloading')
            
            downloaded = d.get('downloaded_bytes', 0)
            self.pbar.update(downloaded - self.pbar.n)
            
        elif d['status'] == 'finished' and self.pbar is not None:
            self.pbar.close()

# Define multiple proxy configurations
PROXY_CONFIGS = [
    {
        'host': os.getenv('EVOMI_HOST', 'core-residential.evomi.com'),
        'port': os.getenv('EVOMI_PORT', '1000'),
        'username': os.getenv('EVOMI_USER', 'dylan4'),
        'password': os.getenv('EVOMI_PASS', 'EiSIAcpnwcjrYIQ4Ughw')
    },
    # Additional configurations using the same credentials but different ports
    {
        'host': os.getenv('EVOMI_HOST', 'core-residential.evomi.com'),
        'port': '1001',
        'username': os.getenv('EVOMI_USER', 'dylan4'),
        'password': os.getenv('EVOMI_PASS', 'EiSIAcpnwcjrYIQ4Ughw')
    },
    {
        'host': os.getenv('EVOMI_HOST', 'core-residential.evomi.com'),
        'port': '1002',
        'username': os.getenv('EVOMI_USER', 'dylan4'),
        'password': os.getenv('EVOMI_PASS', 'EiSIAcpnwcjrYIQ4Ughw')
    },
    {
        'host': os.getenv('EVOMI_HOST', 'core-residential.evomi.com'),
        'port': '1003',
        'username': os.getenv('EVOMI_USER', 'dylan4'),
        'password': os.getenv('EVOMI_PASS', 'EiSIAcpnwcjrYIQ4Ughw')
    },
    {
        'host': os.getenv('EVOMI_HOST', 'core-residential.evomi.com'),
        'port': '1004',
        'username': os.getenv('EVOMI_USER', 'dylan4'),
        'password': os.getenv('EVOMI_PASS', 'EiSIAcpnwcjrYIQ4Ughw')
    }
]

# Keep track of which proxies have failed recently
PROXY_FAILURES = {}

def get_evomi_api_proxy():
    """Get a proxy URL directly from Evomi API with all expert settings enabled"""
    api_key = os.getenv('EVOMI_API_KEY')
    if not api_key or api_key == '@Evomi':
        print("WARNING: No valid Evomi API key found. Using fallback proxy configuration.")
        return None
    
    try:
        # Construct the API URL with all expert settings enabled
        base_url = "https://api.evomi.com/public"
        params = {
            "apikey": api_key,
            # Enable all expert settings
            "min_connection_time": "enabled",  # Minimum Node Connection Time
            "fraud_score": "enabled",          # IP Fraud Score
            "tcp_fingerprint": "enabled",      # TCP/IP Fingerprint
            "response_time": "enabled",        # Response Time
            "isp": "enabled",                  # ISP Targeting
            "asn": "enabled",                  # ASN Targeting
            "additional_pool": "enabled"       # Additional Pool Size
        }
        
        # Make the API request
        response = requests.get(base_url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check if the response has the expected structure
            if data.get('success') and 'products' in data:
                # Look for the residential core product (rpc)
                if 'rpc' in data['products']:
                    product = data['products']['rpc']
                    username = product.get('username')
                    password = product.get('password')
                    endpoint = product.get('endpoint')
                    
                    # Get HTTP port
                    port = None
                    if 'ports' in product and 'http' in product['ports']:
                        port = product['ports']['http']
                    
                    if username and password and endpoint and port:
                        proxy_url = f'http://{username}:{password}@{endpoint}:{port}'
                        print(f"Successfully retrieved proxy from Evomi API: {endpoint}:{port}")
                        return proxy_url
            
            print(f"Invalid or unexpected response format from Evomi API: {data}")
        else:
            print(f"Failed to get proxy from Evomi API. Status code: {response.status_code}")
            
    except Exception as e:
        print(f"Error accessing Evomi API: {str(e)}")
    
    return None

def get_proxy_url():
    """Get a proxy URL, first trying the Evomi API with expert settings, then falling back to configured proxies"""
    # First try to get a proxy from the Evomi API with all expert settings
    api_proxy = get_evomi_api_proxy()
    if api_proxy:
        return api_proxy
    
    # If API fails, fall back to the configured proxies
    if not PROXY_CONFIGS:
        print("WARNING: No proxy configurations available.")
        return None
    
    # Filter out proxies that have failed recently (within the last 5 minutes)
    current_time = time.time()
    available_proxies = [
        config for config in PROXY_CONFIGS 
        if config.get('host') not in PROXY_FAILURES or 
           current_time - PROXY_FAILURES[config.get('host')] > 300  # 5 minutes cooldown
    ]
    
    if not available_proxies:
        print("WARNING: All proxies have failed recently. Resetting failure history.")
        PROXY_FAILURES.clear()
        available_proxies = PROXY_CONFIGS
    
    # Select a proxy configuration randomly from available ones
    config = random.choice(available_proxies)
    
    if not all([config.get("username"), config.get("password"), 
                config.get("host"), config.get("port")]):
        print("WARNING: Incomplete proxy configuration.")
        return None
    
    proxy_url = f'http://{config["username"]}:{config["password"]}@{config["host"]}:{config["port"]}'
    print(f"Using fallback proxy: {config['host']}:{config['port']}")
    return proxy_url

def mark_proxy_failure(proxy_url):
    """Mark a proxy as having failed"""
    if not proxy_url:
        return
    
    # Extract the host from the proxy URL
    try:
        import re
        host_match = re.search(r'@([^:]+):', proxy_url)
        if host_match:
            host = host_match.group(1)
            PROXY_FAILURES[host] = time.time()
            print(f"Marked proxy {host} as failed. Will avoid for 5 minutes.")
    except Exception as e:
        print(f"Error marking proxy failure: {str(e)}")

def download_and_extract_audio(url, output_dir="data"):
    conn = init_db()
    
    progress_hook = ProgressHook()
    
    # Implement retry logic with exponential backoff and proxy rotation
    max_retries = 5
    for attempt in range(max_retries):
        # Get a fresh proxy for each attempt
        proxy_url = get_proxy_url()
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
            }],
            'outtmpl': f'{output_dir}/%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [progress_hook],
            'socket_timeout': 30,       # Increase socket timeout
            'retries': 5,               # Internal retries by yt-dlp
            'fragment_retries': 5,      # Fragment retry attempts
            'retry_sleep_functions': {  # Custom sleep between retries
                'http': lambda n: 2 * (1.5 ** n),
                'fragment': lambda n: 2 * (1.5 ** n),
                'file_access': lambda n: 2 * (1.5 ** n),
            }
        }
        
        # Add proxy if available
        if proxy_url:
            ydl_opts['proxy'] = proxy_url
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Get the final filename after conversion
                title = info['title']
                audio_path = Path(output_dir) / f"{title}.wav"
                
                # Store in database
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO downloads 
                    (video_id, title, channel, download_date, audio_path, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    info['id'],
                    title,
                    info['channel'],
                    datetime.now().isoformat(),
                    str(audio_path),
                    json.dumps(info)
                ))
                conn.commit()
                
                print(f"Successfully downloaded using proxy: {proxy_url}")
                return str(audio_path)
                
        except Exception as e:
            # Mark this proxy as failed
            if proxy_url:
                mark_proxy_failure(proxy_url)
                
            if attempt < max_retries - 1:
                # Calculate exponential backoff with jitter
                sleep_time = (2 ** attempt) + random.uniform(0, 1)
                print(f"Download attempt {attempt+1} failed: {str(e)}")
                print(f"Retrying with different proxy in {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)
            else:
                print(f"Failed to download after {max_retries} attempts: {str(e)}")
                raise 