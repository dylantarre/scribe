import yt_dlp
import time
import sqlite3
from datetime import datetime, timedelta
from main import transcribe_youtube

CHANNELS = [
    "https://www.youtube.com/@theneedledrop",
    "https://www.youtube.com/@fantano"
]
CHECK_INTERVAL = 120  # 2 minutes

def init_monitor_db():
    conn = sqlite3.connect('data/monitor.db')
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS processed_videos (
        video_id TEXT PRIMARY KEY,
        channel TEXT,
        processed_date TEXT
    )
    ''')
    conn.commit()
    return conn

def get_latest_videos(channel_url):
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'playlist_items': '1-5'  # Only check latest 5 videos
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"{channel_url}/videos", download=False)
            return [(entry['id'], f"https://www.youtube.com/watch?v={entry['id']}", channel_url) 
                   for entry in info['entries'] if entry]
        except Exception as e:
            print(f"Error checking {channel_url}: {str(e)}")
            return []

def monitor_channels():
    conn = init_monitor_db()
    cursor = conn.cursor()
    
    print(f"Monitoring channels: {CHANNELS}")
    print(f"Checking every {CHECK_INTERVAL} seconds...")
    
    while True:
        for channel in CHANNELS:
            videos = get_latest_videos(channel)
            
            for video_id, video_url, channel_url in videos:
                # Check if we've already processed this video
                cursor.execute('SELECT 1 FROM processed_videos WHERE video_id = ?', (video_id,))
                if not cursor.fetchone():
                    print(f"\nNew video detected on {channel}!")
                    print(f"Processing: {video_url}")
                    
                    try:
                        transcribe_youtube(video_url)
                        
                        # Mark as processed
                        cursor.execute('''
                            INSERT INTO processed_videos (video_id, channel, processed_date)
                            VALUES (?, ?, ?)
                        ''', (video_id, channel_url, datetime.now().isoformat()))
                        conn.commit()
                        
                    except Exception as e:
                        print(f"Error processing video {video_id}: {str(e)}")
        
        # Clean up old entries (optional)
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        cursor.execute('DELETE FROM processed_videos WHERE processed_date < ?', (week_ago,))
        conn.commit()
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        monitor_channels()
    except KeyboardInterrupt:
        print("\nMonitoring stopped.") 