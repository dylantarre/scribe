#!/usr/bin/env python3

import time
import sqlite3
import os
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv
import subprocess
import sys
import signal

# Import from latest_video.py
from latest_video import get_latest_video, transcribe_latest_video, init_db

# Load environment variables
load_dotenv()
# Also try to load from config directory
if os.path.exists('config/.env'):
    load_dotenv('config/.env')

# Configuration
MONITORING_INTERVAL = int(os.getenv("MONITORING_INTERVAL", 3600))  # Default: 1 hour
ENABLE_MONITORING = os.getenv("ENABLE_MONITORING", "0") == "1"
MONITOR_CHANNELS = os.getenv("MONITOR_CHANNELS", "@fantano,@theneedledrop").split(",")

# Default settings
CHANNEL = "@fantano"  # Default to @fantano
CHECK_INTERVAL = 120  # Check every 2 minutes (in seconds)

# Handle graceful shutdown
running = True

def signal_handler(sig, frame):
    global running
    print("\nShutting down monitor gracefully...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def monitor_channels():
    """
    Continuously monitor channels for new videos and transcribe them
    """
    print(f"Starting YouTube channel monitor")
    print(f"Monitoring channels: {', '.join(MONITOR_CHANNELS)}")
    print(f"Checking interval: {MONITORING_INTERVAL} seconds")
    
    if not ENABLE_MONITORING:
        print("Warning: Monitoring is disabled in .env file (ENABLE_MONITORING=0)")
        print("Setting ENABLE_MONITORING=1 in .env to enable automatic monitoring")
    
    while running:
        print(f"\n--- Checking for new videos at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        
        for channel in MONITOR_CHANNELS:
            channel = channel.strip()
            if not channel:
                continue
                
            print(f"Checking channel: {channel}")
            try:
                transcribe_latest_video(
                    channel,
                    filter_filler_words=False,
                    add_paragraphs=True,
                    force=False  # Don't force reprocessing
                )
            except Exception as e:
                print(f"Error processing channel {channel}: {str(e)}")
        
        # Wait for next check if still running
        if running:
            print(f"Next check in {MONITORING_INTERVAL} seconds...")
            # Sleep in smaller increments to allow for graceful shutdown
            for _ in range(min(MONITORING_INTERVAL, 3600)):
                if not running:
                    break
                time.sleep(1)

if __name__ == "__main__":
    try:
        monitor_channels()
    except KeyboardInterrupt:
        print("\nMonitor stopped by user")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
    
    print("Monitor shutdown complete") 