#!/usr/bin/env python3
import yt_dlp
import sqlite3
import os
import argparse
from datetime import datetime
from youtube_downloader import download_and_extract_audio, get_proxy_url, mark_proxy_failure
from dotenv import load_dotenv
import random
import time
import sys
import json
import subprocess
from pathlib import Path
from yt_dlp import YoutubeDL, utils
from yt_dlp.extractor.youtube import YoutubeTabIE

# Load environment variables
load_dotenv()
# Also try to load from config directory
if os.path.exists('config/.env'):
    load_dotenv('config/.env')

def init_db():
    """Initialize SQLite database for tracking processed videos"""
    conn = sqlite3.connect('latest_videos.db')
    cursor = conn.cursor()
    
    # Create table if it doesn't exist
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS latest_videos (
        channel TEXT,
        video_id TEXT,
        title TEXT,
        processed_date TEXT,
        PRIMARY KEY (channel, video_id)
    )
    ''')
    
    conn.commit()
    return conn

def get_latest_video(channel_url):
    """
    Get the latest video from a YouTube channel
    
    Args:
        channel_url (str): YouTube channel URL or handle
        
    Returns:
        tuple: (video_id, video_url, title) or None if error
    """
    # Format the channel URL if it's a handle
    if channel_url.startswith('@'):
        channel_url = f"https://www.youtube.com/{channel_url}/videos"
    else:
        channel_url = f"{channel_url}/videos"
    
    # Configure yt-dlp options
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': False,
        'playlist_items': '1',  # Only get the latest video
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"Fetching latest video from {channel_url}...")
            info = ydl.extract_info(channel_url, download=False)
            
            if 'entries' in info and info['entries']:
                video = info['entries'][0]
                video_id = video.get('id')
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                title = video.get('title', 'Unknown Title')
                
                print(f"Found latest video: {title}")
                return video_id, video_url, title
            else:
                print(f"No videos found for {channel_url}")
                return None
    except Exception as e:
        print(f"Error fetching latest video from {channel_url}: {e}")
        return None

def transcribe_latest_video(channel_url, filter_filler_words=False, add_paragraphs=True, force=False):
    """
    Check for and transcribe the latest video from a channel if it hasn't been processed
    
    Args:
        channel_url (str): YouTube channel URL or handle
        filter_filler_words (bool): Whether to filter out filler words like "um", "uh", etc.
        add_paragraphs (bool): Whether to add paragraph breaks to the text
        force (bool): Whether to force reprocessing even if the video has been processed before
    """
    # Get the latest video info
    video_info = get_latest_video(channel_url)
    if not video_info:
        return
    
    video_id, video_url, title = video_info
    
    # Check if we've already processed this video
    conn = init_db()
    cursor = conn.cursor()
    cursor.execute("SELECT video_id FROM latest_videos WHERE channel = ? AND video_id = ?", 
                  (channel_url, video_id))
    result = cursor.fetchone()
    
    if result and not force:
        print(f"Video {video_id} has already been processed. Skipping.")
        conn.close()
        return
    elif result and force:
        print(f"Video {video_id} has already been processed, but force flag is set. Reprocessing...")
    
    # Create output directory
    channel_name = channel_url.split('/')[-1] if '/' in channel_url else channel_url
    if channel_name.startswith('@'):
        channel_name = channel_name[1:]  # Remove @ from handle
    
    output_dir = os.path.join('transcripts', channel_name)
    os.makedirs(output_dir, exist_ok=True)
    
    # Download audio
    audio_path = os.path.join(output_dir, f"{video_id}.mp3")
    
    if not os.path.exists(audio_path):
        print(f"Downloading audio for {title}...")
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': audio_path.replace('.mp3', ''),
            'quiet': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
    else:
        print(f"Audio file already exists: {audio_path}")
    
    # Transcribe the audio
    print(f"Transcribing {title}...")
    
    # Use Whisper for transcription
    try:
        print("Transcribing with Whisper (turbo model for fast processing with good accuracy)...")
        
        # Use the full audio file instead of a test segment
        audio_to_transcribe = audio_path
        
        # Use python3 explicitly instead of python
        whisper_cmd = [
            "python3", "-m", "whisper", audio_to_transcribe,
            "--model", "turbo",  # Using turbo model for fast processing with good accuracy
            "--language", "en",  # Always use English
            "--task", "transcribe",  # Specify transcribe task (skips language detection)
            "--output_dir", output_dir,
            "--output_format", "all",  # Use 'all' to generate all formats
            "--verbose", "True",  # Add verbose output
            "--threads", "4"  # Use multiple threads for faster processing
        ]
        
        print(f"Running command: {' '.join(whisper_cmd)}")
        print("This should process quickly with the turbo model...")
        
        # Run with a timeout of 10 minutes for the full audio with turbo model
        result = subprocess.run(whisper_cmd, capture_output=True, text=True, check=True, timeout=600)
        print(result.stdout)
        
        # Check if output files were created
        expected_base_name = os.path.basename(audio_to_transcribe).replace('.mp3', '')
        expected_files = [
            os.path.join(output_dir, f"{expected_base_name}.txt"),
            os.path.join(output_dir, f"{expected_base_name}.vtt"),
            os.path.join(output_dir, f"{expected_base_name}.srt"),
            os.path.join(output_dir, f"{expected_base_name}.json")
        ]
        
        for file_path in expected_files:
            if os.path.exists(file_path):
                print(f"Output file created: {file_path}")
            else:
                print(f"Warning: Expected output file not found: {file_path}")
        
        # Mark as processed
        if not result:
            cursor.execute(
                "INSERT INTO latest_videos (channel, video_id, title, processed_date) VALUES (?, ?, ?, ?)",
                (channel_url, video_id, title, datetime.now().isoformat())
            )
        else:
            cursor.execute(
                "UPDATE latest_videos SET processed_date = ? WHERE channel = ? AND video_id = ?",
                (datetime.now().isoformat(), channel_url, video_id)
            )
        conn.commit()
        conn.close()
        
        print(f"Whisper transcription completed for {title}")
    except subprocess.CalledProcessError as e:
        print(f"Error with Whisper transcription: {e.stderr}")
        conn.close()
    except Exception as e:
        print(f"Unexpected error with Whisper: {str(e)}")
        conn.close()
    
    print(f"Successfully processed latest video from {channel_url}")

if __name__ == "__main__":
    # Initialize database
    init_db()
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Fetch and transcribe latest videos from YouTube channels")
    parser.add_argument("--channel", help="Specific channel to check (default: check both fantano and theneedledrop)")
    parser.add_argument("--filter-filler", action="store_true", help="Filter out filler words like 'um', 'uh', etc.")
    parser.add_argument("--no-paragraphs", action="store_true", help="Disable automatic paragraph formatting")
    parser.add_argument("--force", action="store_true", help="Force reprocessing of videos even if already processed")
    args = parser.parse_args()
    
    # Define channels to check
    channels = ["@fantano", "@theneedledrop"]
    
    # If a specific channel is provided, only check that one
    if args.channel:
        if args.channel in ["fantano", "@fantano"]:
            channels = ["@fantano"]
        elif args.channel in ["theneedledrop", "@theneedledrop"]:
            channels = ["@theneedledrop"]
        else:
            channels = [args.channel]
    
    # Process each channel
    for channel in channels:
        transcribe_latest_video(
            channel, 
            filter_filler_words=args.filter_filler,
            add_paragraphs=not args.no_paragraphs,
            force=args.force
        )
