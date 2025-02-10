#!/usr/bin/env python3
import yt_dlp
import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from tqdm import tqdm

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

def download_and_extract_audio(url, output_dir="data"):
    conn = init_db()
    
    progress_hook = ProgressHook()
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
        }],
        'outtmpl': f'{output_dir}/%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [progress_hook]
    }

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
            
            return str(audio_path)
            
    except Exception as e:
        print(f"Error downloading {url}: {str(e)}")
        raise 