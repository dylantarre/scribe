#!/usr/bin/env python3
import os
import sqlite3
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()
if os.path.exists('config/.env'):
    load_dotenv('config/.env')

FB_AUTO_REPOST = os.getenv("FB_AUTO_REPOST", "0") == "1"
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "")
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "")
FB_USER_ACCESS_TOKEN = os.getenv("FB_USER_ACCESS_TOKEN", "")
FB_NORMAL_VIDEO_DELAY_SECONDS = int(os.getenv("FB_NORMAL_VIDEO_DELAY_SECONDS", "86400"))
FB_SHORTS_AS_REELS = os.getenv("FB_SHORTS_AS_REELS", "1") == "1"
FB_REPOST_MESSAGE_TEMPLATE = os.getenv(
    "FB_REPOST_MESSAGE_TEMPLATE",
    "{title}",
)

_DERIVED_PAGE_ACCESS_TOKEN = None


def init_facebook_db(db_path="latest_videos.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS facebook_reposts (
            video_id TEXT PRIMARY KEY,
            channel TEXT,
            title TEXT,
            description TEXT,
            video_file_path TEXT,
            video_url TEXT,
            is_short INTEGER,
            scheduled_time TEXT,
            status TEXT,
            posted_time TEXT,
            attempts INTEGER,
            last_error TEXT,
            facebook_post_id TEXT
        )
        """
    )
    conn.commit()

    # Backfill old schema
    cursor.execute("PRAGMA table_info(facebook_reposts)")
    columns = [row[1] for row in cursor.fetchall()]
    if "description" not in columns:
        cursor.execute("ALTER TABLE facebook_reposts ADD COLUMN description TEXT")
        conn.commit()
    if "video_file_path" not in columns:
        cursor.execute("ALTER TABLE facebook_reposts ADD COLUMN video_file_path TEXT")
        conn.commit()

    return conn


def facebook_enabled():
    return FB_AUTO_REPOST and bool(FB_PAGE_ID) and bool(FB_PAGE_ACCESS_TOKEN or FB_USER_ACCESS_TOKEN)


def _effective_page_access_token():
    global _DERIVED_PAGE_ACCESS_TOKEN

    if _DERIVED_PAGE_ACCESS_TOKEN:
        return _DERIVED_PAGE_ACCESS_TOKEN

    if FB_USER_ACCESS_TOKEN and FB_PAGE_ID:
        try:
            resp = requests.get(
                f"https://graph.facebook.com/v22.0/{FB_PAGE_ID}",
                params={
                    "fields": "access_token",
                    "access_token": FB_USER_ACCESS_TOKEN,
                },
                timeout=30,
            )
            if resp.ok:
                token = resp.json().get("access_token")
                if token:
                    _DERIVED_PAGE_ACCESS_TOKEN = token
                    return token
            else:
                print(f"Facebook token derivation failed: {resp.status_code} {resp.text[:300]}")
        except Exception as exc:
            print(f"Facebook token derivation error: {exc}")

    return FB_PAGE_ACCESS_TOKEN


def _iso_now():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _compute_schedule(is_short, delay_override_seconds=None):
    now = datetime.utcnow()
    if delay_override_seconds is not None:
        scheduled = now + timedelta(seconds=int(delay_override_seconds))
    elif is_short:
        scheduled = now
    else:
        scheduled = now + timedelta(seconds=FB_NORMAL_VIDEO_DELAY_SECONDS)
    return scheduled.replace(microsecond=0).isoformat() + "Z"


def enqueue_facebook_repost(
    video_id,
    channel,
    title,
    description,
    video_file_path,
    video_url,
    is_short,
    db_path="latest_videos.db",
    delay_override_seconds=None,
):
    if not facebook_enabled():
        return False

    conn = init_facebook_db(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM facebook_reposts WHERE video_id = ?", (video_id,))
    existing = cursor.fetchone()

    if existing:
        conn.close()
        return False

    scheduled_time = _compute_schedule(is_short, delay_override_seconds=delay_override_seconds)

    cursor.execute(
        """
        INSERT INTO facebook_reposts (
            video_id, channel, title, description, video_file_path, video_url, is_short,
            scheduled_time, status, posted_time, attempts, last_error, facebook_post_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, 0, NULL, NULL)
        """,
        (video_id, channel, title, description, video_file_path, video_url, int(is_short), scheduled_time),
    )

    conn.commit()
    conn.close()

    kind = "short" if is_short else "normal"
    print(f"Queued Facebook repost for {video_id} ({kind}). Scheduled at {scheduled_time}")
    return True


def _build_message(video_url, title, description, channel):
    message = FB_REPOST_MESSAGE_TEMPLATE.format(
        channel=channel,
        title=title,
        description=description or "",
        url=video_url,
    )
    return message


def _publish_link_to_facebook(video_url, message):
    access_token = _effective_page_access_token()
    payload = {
        "message": message,
        "link": video_url,
        "access_token": access_token,
    }
    endpoint = f"https://graph.facebook.com/v22.0/{FB_PAGE_ID}/feed"
    response = requests.post(endpoint, data=payload, timeout=30)
    return response


def _require_native_video_file(video_file_path, video_id):
    if video_file_path and os.path.exists(video_file_path):
        return
    raise FileNotFoundError(
        f"Missing local video file for {video_id}; native upload required, link-post fallback disabled."
    )


def _publish_native_video_to_facebook(video_file_path, title, message):
    endpoint = f"https://graph-video.facebook.com/v22.0/{FB_PAGE_ID}/videos"
    access_token = _effective_page_access_token()
    payload = {
        "title": title,
        "description": message,
        "access_token": access_token,
    }
    with open(video_file_path, "rb") as video_stream:
        files = {
            "source": (os.path.basename(video_file_path), video_stream, "video/mp4"),
        }
        response = requests.post(endpoint, data=payload, files=files, timeout=600)
    if response.status_code == 413:
        print("Native /videos upload returned 413; retrying with resumable upload.")
        return _publish_native_video_resumable(video_file_path, title, message)
    return response


def _publish_native_video_resumable(video_file_path, title, message):
    endpoint = f"https://graph-video.facebook.com/v22.0/{FB_PAGE_ID}/videos"
    access_token = _effective_page_access_token()
    file_size = os.path.getsize(video_file_path)

    start_resp = requests.post(
        endpoint,
        data={
            "access_token": access_token,
            "upload_phase": "start",
            "file_size": str(file_size),
        },
        timeout=60,
    )
    if not start_resp.ok:
        print(f"Resumable start failed: {start_resp.status_code} {start_resp.text[:500]}")
        return start_resp

    start_data = start_resp.json()
    upload_session_id = start_data.get("upload_session_id")
    start_offset = start_data.get("start_offset")
    end_offset = start_data.get("end_offset")
    if not upload_session_id or start_offset is None or end_offset is None:
        print(f"Resumable start missing fields: {start_resp.text[:500]}")
        return start_resp

    with open(video_file_path, "rb") as video_stream:
        while str(start_offset) != str(end_offset):
            start_i = int(start_offset)
            end_i = int(end_offset)
            chunk_size = max(0, end_i - start_i)
            video_stream.seek(start_i)
            chunk = video_stream.read(chunk_size)
            transfer_resp = requests.post(
                endpoint,
                data={
                    "access_token": access_token,
                    "upload_phase": "transfer",
                    "upload_session_id": upload_session_id,
                    "start_offset": str(start_offset),
                },
                files={
                    "video_file_chunk": ("chunk.bin", chunk, "application/octet-stream"),
                },
                timeout=600,
            )
            if not transfer_resp.ok:
                print(f"Resumable transfer failed: {transfer_resp.status_code} {transfer_resp.text[:500]}")
                return transfer_resp
            transfer_data = transfer_resp.json()
            start_offset = transfer_data.get("start_offset", end_offset)
            end_offset = transfer_data.get("end_offset", end_offset)

    finish_resp = requests.post(
        endpoint,
        data={
            "access_token": access_token,
            "upload_phase": "finish",
            "upload_session_id": upload_session_id,
            "title": title,
            "description": message,
        },
        timeout=180,
    )
    if not finish_resp.ok:
        print(f"Resumable finish failed: {finish_resp.status_code} {finish_resp.text[:500]}")
    return finish_resp


def _publish_reel_to_facebook(video_file_path, title, message):
    endpoint = f"https://graph.facebook.com/v22.0/{FB_PAGE_ID}/video_reels"
    file_size = os.path.getsize(video_file_path)
    access_token = _effective_page_access_token()

    # Phase 1: start upload session
    start_resp = requests.post(
        endpoint,
        data={
            "access_token": access_token,
            "upload_phase": "start",
        },
        timeout=60,
    )
    if not start_resp.ok:
        return start_resp

    start_data = start_resp.json()
    video_id = start_data.get("video_id")
    upload_url = start_data.get("upload_url")
    if not video_id or not upload_url:
        return start_resp

    # Phase 2: upload bytes to provided URL
    with open(video_file_path, "rb") as video_stream:
        transfer_resp = requests.post(
            upload_url,
            headers={
                "Authorization": f"OAuth {access_token}",
                "offset": "0",
                "file_size": str(file_size),
            },
            data=video_stream,
            timeout=1200,
        )
    if not transfer_resp.ok:
        return transfer_resp

    # Phase 3: finish and publish
    finish_resp = requests.post(
        endpoint,
        data={
            "access_token": access_token,
            "video_id": video_id,
            "upload_phase": "finish",
            "video_state": "PUBLISHED",
            "title": title,
            "description": message,
        },
        timeout=120,
    )
    return finish_resp


def _resolve_post_id_from_response(data):
    # For /feed posts, "id" is a post ID. For /videos, the response often includes
    # both "id" (video object) and "post_id" (feed post).
    post_id = data.get("post_id")
    if post_id:
        return post_id

    object_id = data.get("video_id") or data.get("id")
    if not object_id:
        return None

    try:
        access_token = _effective_page_access_token()
        lookup = requests.get(
            f"https://graph.facebook.com/v22.0/{object_id}",
            params={
                "fields": "post_id",
                "access_token": access_token,
            },
            timeout=30,
        )
        if lookup.ok:
            resolved = lookup.json().get("post_id")
            if resolved:
                return resolved
    except Exception:
        pass

    # Fallback to raw ID if we couldn't resolve a separate post ID.
    return data.get("id")


def publish_due_facebook_reposts(db_path="latest_videos.db", limit=20):
    if not facebook_enabled():
        return 0

    now_iso = _iso_now()
    conn = init_facebook_db(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT video_id, channel, title, description, video_file_path, video_url, is_short, attempts
        FROM facebook_reposts
        WHERE status = 'pending' AND scheduled_time <= ?
        ORDER BY scheduled_time ASC
        LIMIT ?
        """,
        (now_iso, limit),
    )

    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return 0

    posted_count = 0
    for video_id, channel, title, description, video_file_path, video_url, is_short, attempts in rows:
        try:
            message = _build_message(video_url, title, description, channel)
            _require_native_video_file(video_file_path, video_id)
            if is_short and FB_SHORTS_AS_REELS:
                response = _publish_reel_to_facebook(video_file_path, title, message)
                if not response.ok:
                    print(f"Reels upload failed for {video_id}, falling back to /videos endpoint.")
                    response = _publish_native_video_to_facebook(video_file_path, title, message)
            else:
                response = _publish_native_video_to_facebook(video_file_path, title, message)
            if response.ok:
                data = response.json()
                post_id = _resolve_post_id_from_response(data)
                cursor.execute(
                    """
                    UPDATE facebook_reposts
                    SET status = 'posted', posted_time = ?, facebook_post_id = ?, last_error = NULL
                    WHERE video_id = ?
                    """,
                    (_iso_now(), post_id, video_id),
                )
                posted_count += 1
                print(f"Facebook repost published for {video_id}")
            else:
                error_text = response.text[:1000]
                cursor.execute(
                    """
                    UPDATE facebook_reposts
                    SET attempts = ?, last_error = ?
                    WHERE video_id = ?
                    """,
                    (attempts + 1, error_text, video_id),
                )
                print(f"Facebook repost failed for {video_id}: {error_text}")
        except Exception as exc:
            cursor.execute(
                """
                UPDATE facebook_reposts
                SET attempts = ?, last_error = ?
                WHERE video_id = ?
                """,
                (attempts + 1, str(exc)[:1000], video_id),
            )
            print(f"Facebook repost error for {video_id}: {exc}")

    conn.commit()
    conn.close()
    return posted_count
