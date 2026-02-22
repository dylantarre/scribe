#!/usr/bin/env python3
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yt_dlp
from dotenv import load_dotenv

from facebook_reposter import enqueue_facebook_repost

load_dotenv()
if os.path.exists('config/.env'):
    load_dotenv('config/.env')

CLASSIC_AUTO_REPOST = os.getenv("CLASSIC_AUTO_REPOST", "0") == "1"
CLASSIC_CHANNELS = [c.strip() for c in os.getenv("CLASSIC_CHANNELS", "@fantano,@theneedledrop").split(",") if c.strip()]
CLASSIC_POST_DAY = os.getenv("CLASSIC_POST_DAY", "wednesday").strip().lower()
CLASSIC_POST_HOUR = int(os.getenv("CLASSIC_POST_HOUR", "9"))
CLASSIC_POST_MINUTE = int(os.getenv("CLASSIC_POST_MINUTE", "0"))
CLASSIC_POST_TZ = os.getenv("CLASSIC_POST_TZ", os.getenv("TZ", "UTC"))
CLASSIC_TOP_CANDIDATES = int(os.getenv("CLASSIC_TOP_CANDIDATES", "50"))
CLASSIC_INCLUDE_SHORTS = os.getenv("CLASSIC_INCLUDE_SHORTS", "0") == "1"
CLASSIC_MIN_AGE_YEARS = int(os.getenv("CLASSIC_MIN_AGE_YEARS", "3"))

DAY_MAP = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


def init_classic_db(db_path="latest_videos.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS classic_posts (
            channel TEXT,
            video_id TEXT,
            title TEXT,
            youtube_url TEXT,
            view_count INTEGER,
            is_short INTEGER,
            selected_time TEXT,
            PRIMARY KEY (channel, video_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS classic_weekly_runs (
            channel TEXT,
            week_key TEXT,
            run_time TEXT,
            PRIMARY KEY (channel, week_key)
        )
        """
    )
    conn.commit()
    return conn


def _now_local():
    try:
        tz = ZoneInfo(CLASSIC_POST_TZ)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def _current_week_key(now_local):
    return now_local.strftime("%G-W%V")


def _within_weekly_window(now_local):
    day_index = DAY_MAP.get(CLASSIC_POST_DAY, 2)
    return (
        now_local.weekday() == day_index
        and (now_local.hour, now_local.minute) >= (CLASSIC_POST_HOUR, CLASSIC_POST_MINUTE)
    )


def _already_posted_classic(conn, channel, video_id):
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM classic_posts WHERE channel = ? AND video_id = ?",
        (channel, video_id),
    )
    return cur.fetchone() is not None


def _already_queued_or_posted_fb(conn, video_id):
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT 1 FROM facebook_reposts WHERE video_id = ?",
            (video_id,),
        )
    except sqlite3.OperationalError:
        return False
    return cur.fetchone() is not None


def _has_run_this_week(conn, channel, week_key):
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM classic_weekly_runs WHERE channel = ? AND week_key = ?",
        (channel, week_key),
    )
    return cur.fetchone() is not None


def _mark_run_this_week(conn, channel, week_key):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO classic_weekly_runs (channel, week_key, run_time)
        VALUES (?, ?, ?)
        """,
        (channel, week_key, datetime.utcnow().replace(microsecond=0).isoformat() + "Z"),
    )
    conn.commit()


def _record_classic_selection(conn, channel, candidate):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO classic_posts (
            channel, video_id, title, youtube_url, view_count, is_short, selected_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            channel,
            candidate["video_id"],
            candidate["title"],
            candidate["video_url"],
            candidate.get("view_count"),
            int(candidate["is_short"]),
            datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        ),
    )
    conn.commit()


def _fetch_top_candidates(channel, limit):
    channel_path = channel if channel.startswith("@") else f"@{channel}"
    popular_url = f"https://www.youtube.com/{channel_path}/videos?view=0&sort=p&flow=grid"
    with yt_dlp.YoutubeDL(
        {"quiet": True, "extract_flat": True, "playlist_items": f"1-{limit}"}
    ) as ydl:
        info = ydl.extract_info(popular_url, download=False)

    entries = info.get("entries", []) if isinstance(info, dict) else []
    candidates = []
    for entry in entries:
        video_id = entry.get("id")
        if not video_id:
            continue
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            with yt_dlp.YoutubeDL({"quiet": True}) as detail_ydl:
                detail = detail_ydl.extract_info(video_url, download=False)
        except Exception as err:
            print(f"Could not load details for {video_id}: {err}")
            continue

        duration = detail.get("duration")
        webpage_url = detail.get("webpage_url", video_url)
        upload_date = detail.get("upload_date")
        is_short = False
        if isinstance(duration, (int, float)) and duration <= 60:
            is_short = True
        if isinstance(webpage_url, str) and "/shorts/" in webpage_url:
            is_short = True
        if is_short and not CLASSIC_INCLUDE_SHORTS:
            continue

        if upload_date and len(str(upload_date)) == 8:
            try:
                published_date = datetime.strptime(str(upload_date), "%Y%m%d").date()
                cutoff_date = (datetime.now(timezone.utc) - timedelta(days=365 * CLASSIC_MIN_AGE_YEARS)).date()
                if published_date > cutoff_date:
                    continue
            except Exception:
                pass

        candidates.append(
            {
                "video_id": video_id,
                "video_url": video_url,
                "title": detail.get("title") or entry.get("title") or "Unknown Title",
                "description": detail.get("description") or "",
                "view_count": detail.get("view_count") or 0,
                "upload_date": upload_date,
                "duration": duration,
                "is_short": is_short,
                "channel": channel,
            }
        )

    candidates.sort(key=lambda c: c.get("view_count") or 0, reverse=True)
    return candidates


def _download_video(candidate):
    channel_name = candidate["channel"].lstrip("@")
    output_dir = os.path.join("transcripts", "classics", channel_name)
    os.makedirs(output_dir, exist_ok=True)
    video_id = candidate["video_id"]
    preferred_path = os.path.join(output_dir, f"{video_id}.mp4")
    if os.path.exists(preferred_path):
        return preferred_path

    video_base = os.path.join(output_dir, video_id)
    ydl_video_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": f"{video_base}.%(ext)s",
        "quiet": False,
    }
    with yt_dlp.YoutubeDL(ydl_video_opts) as ydl:
        ydl.download([candidate["video_url"]])

    if os.path.exists(preferred_path):
        return preferred_path
    files = sorted(Path(output_dir).glob(f"{video_id}.*"))
    return str(files[0]) if files else None


def _choose_and_queue_for_channel(conn, channel):
    candidates = _fetch_top_candidates(channel, CLASSIC_TOP_CANDIDATES)
    for candidate in candidates:
        if _already_posted_classic(conn, channel, candidate["video_id"]):
            continue
        if _already_queued_or_posted_fb(conn, candidate["video_id"]):
            continue

        video_file_path = _download_video(candidate)
        if not video_file_path:
            print(f"No downloaded file for classic candidate {candidate['video_id']}")
            continue

        queued = enqueue_facebook_repost(
            video_id=candidate["video_id"],
            channel=channel,
            title=candidate["title"],
            description=candidate.get("description"),
            video_file_path=video_file_path,
            video_url=candidate["video_url"],
            is_short=candidate["is_short"],
            delay_override_seconds=0,
        )
        if queued:
            _record_classic_selection(conn, channel, candidate)
            print(f"Queued weekly classic for {channel}: {candidate['title']}")
            return True
    print(f"No eligible classic candidate found for {channel}")
    return False


def run_weekly_classic_reposts(db_path="latest_videos.db"):
    if not CLASSIC_AUTO_REPOST:
        return 0

    now_local = _now_local()
    if not _within_weekly_window(now_local):
        return 0

    week_key = _current_week_key(now_local)
    conn = init_classic_db(db_path)

    queued = 0
    for channel in CLASSIC_CHANNELS:
        if _has_run_this_week(conn, channel, week_key):
            continue
        try:
            if _choose_and_queue_for_channel(conn, channel):
                queued += 1
        finally:
            _mark_run_this_week(conn, channel, week_key)

    conn.close()
    return queued
