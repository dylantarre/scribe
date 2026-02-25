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

ENABLE_TRANSCRIPTION = os.getenv("ENABLE_TRANSCRIPTION", "0") == "1"


def _upsert_latest_video(cursor, channel_url, video_id, title, description, video_file_path):
    cursor.execute(
        """
        INSERT INTO latest_videos (channel, video_id, title, description, video_file_path, processed_date)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(channel, video_id)
        DO UPDATE SET
            title = excluded.title,
            description = excluded.description,
            video_file_path = excluded.video_file_path,
            processed_date = excluded.processed_date
        """,
        (channel_url, video_id, title, description, video_file_path, datetime.now().isoformat()),
    )


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
        description TEXT,
        video_file_path TEXT,
        processed_date TEXT,
        PRIMARY KEY (channel, video_id)
    )
    ''')

    # Backfill old schema
    cursor.execute("PRAGMA table_info(latest_videos)")
    columns = [row[1] for row in cursor.fetchall()]
    if "description" not in columns:
        cursor.execute("ALTER TABLE latest_videos ADD COLUMN description TEXT")
    if "video_file_path" not in columns:
        cursor.execute("ALTER TABLE latest_videos ADD COLUMN video_file_path TEXT")
    
    conn.commit()
    return conn

def get_latest_video(channel_url):
    """
    Get the latest video from a YouTube channel
    
    Args:
        channel_url (str): YouTube channel URL or handle
        
    Returns:
        dict: latest video metadata or None if error
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

                duration = video.get('duration')
                description = video.get('description')
                webpage_url = video.get('webpage_url') or video.get('url') or video_url

                # Pull full metadata for better shorts detection + description capture.
                try:
                    detail_opts = {'quiet': True}
                    with yt_dlp.YoutubeDL(detail_opts) as detail_ydl:
                        detail_info = detail_ydl.extract_info(video_url, download=False)
                    duration = detail_info.get('duration', duration)
                    description = detail_info.get('description', description)
                    webpage_url = detail_info.get('webpage_url', webpage_url)
                except Exception as detail_err:
                    print(f"Warning: Could not fetch detailed metadata for {video_id}: {detail_err}")
                is_short = False
                if isinstance(duration, (int, float)) and duration <= 90:
                    is_short = True
                if isinstance(webpage_url, str) and '/shorts/' in webpage_url:
                    is_short = True

                print(f"Found latest video: {title}")
                return {
                    "video_id": video_id,
                    "video_url": video_url,
                    "title": title,
                    "description": description,
                    "duration": duration,
                    "is_short": is_short,
                }
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
        return {"status": "error", "channel": channel_url, "error": "latest_video_not_found"}

    video_id = video_info["video_id"]
    video_url = video_info["video_url"]
    title = video_info["title"]
    description = video_info.get("description")
    is_short = video_info.get("is_short", False)

    # Create output directory
    channel_name = channel_url.split('/')[-1] if '/' in channel_url else channel_url
    if channel_name.startswith('@'):
        channel_name = channel_name[1:]  # Remove @ from handle

    output_dir = os.path.join('transcripts', channel_name)
    os.makedirs(output_dir, exist_ok=True)

    video_file_path = os.path.join(output_dir, f"{video_id}.mp4")
    if not os.path.exists(video_file_path):
        video_file_path = None
    
    # Check if we've already processed this video
    conn = init_db()
    cursor = conn.cursor()
    cursor.execute("SELECT video_id FROM latest_videos WHERE channel = ? AND video_id = ?", 
                  (channel_url, video_id))
    result = cursor.fetchone()
    
    if result and not force:
        print(f"Video {video_id} has already been processed. Skipping.")
        conn.close()
        return {
            "status": "skipped",
            "channel": channel_url,
            "video_id": video_id,
            "video_url": video_url,
            "title": title,
            "description": description,
            "video_file_path": video_file_path,
            "is_short": is_short,
        }
    elif result and force:
        print(f"Video {video_id} has already been processed, but force flag is set. Reprocessing...")
    
    # Download video for native Facebook video uploads
    if not video_file_path:
        print(f"Downloading video for {title}...")
        video_base = os.path.join(output_dir, video_id)
        ydl_video_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'outtmpl': f"{video_base}.%(ext)s",
            'quiet': False,
        }
        with yt_dlp.YoutubeDL(ydl_video_opts) as ydl:
            ydl.download([video_url])

        preferred_path = os.path.join(output_dir, f"{video_id}.mp4")
        if os.path.exists(preferred_path):
            video_file_path = preferred_path
        else:
            candidates = sorted(Path(output_dir).glob(f"{video_id}.*"))
            video_file_path = str(candidates[0]) if candidates else None
    else:
        print(f"Video file already exists: {video_file_path}")

    if not ENABLE_TRANSCRIPTION:
        print("Transcription disabled (ENABLE_TRANSCRIPTION=0). Skipping audio download and Whisper.")
        _upsert_latest_video(cursor, channel_url, video_id, title, description, video_file_path)
        conn.commit()
        conn.close()
        return {
            "status": "processed",
            "channel": channel_url,
            "video_id": video_id,
            "video_url": video_url,
            "title": title,
            "description": description,
            "video_file_path": video_file_path,
            "is_short": is_short,
        }

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
        
        # Mark as processed (insert on first run, refresh timestamp on re-run)
        _upsert_latest_video(cursor, channel_url, video_id, title, description, video_file_path)
        conn.commit()
        conn.close()
        
        print(f"Whisper transcription completed for {title}")
        return {
            "status": "processed",
            "channel": channel_url,
            "video_id": video_id,
            "video_url": video_url,
            "title": title,
            "description": description,
            "video_file_path": video_file_path,
            "is_short": is_short,
        }
    except subprocess.CalledProcessError as e:
        print(f"Error with Whisper transcription: {e.stderr}")
        conn.close()
        return {
            "status": "error",
            "channel": channel_url,
            "video_id": video_id,
            "video_url": video_url,
            "title": title,
            "description": description,
            "video_file_path": video_file_path,
            "is_short": is_short,
            "error": e.stderr,
        }
    except Exception as e:
        print(f"Unexpected error with Whisper: {str(e)}")
        conn.close()
        return {
            "status": "error",
            "channel": channel_url,
            "video_id": video_id,
            "video_url": video_url,
            "title": title,
            "description": description,
            "video_file_path": video_file_path,
            "is_short": is_short,
            "error": str(e),
        }
    
    print(f"Successfully processed latest video from {channel_url}")
    return {
        "status": "processed",
        "channel": channel_url,
        "video_id": video_id,
        "video_url": video_url,
        "title": title,
        "description": description,
        "video_file_path": video_file_path,
        "is_short": is_short,
    }

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
