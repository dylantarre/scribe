#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv


def _load_env() -> None:
    load_dotenv()
    if os.path.exists("config/.env"):
        load_dotenv("config/.env")


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


def _graph_get(path: str, token: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    all_params = {"access_token": token}
    if params:
        all_params.update(params)
    resp = requests.get(f"https://graph.facebook.com/v22.0/{path}", params=all_params, timeout=60)
    data = resp.json()
    if not resp.ok:
        raise RuntimeError(f"Graph API error ({resp.status_code}) on /{path}: {json.dumps(data)}")
    return data


def _print_json(title: str, payload: Dict[str, Any]) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2, sort_keys=True))


def inspect_post(post_id: str, token: str) -> None:
    post = _graph_get(
        post_id,
        token,
        {
            "fields": ",".join(
                [
                    "id",
                    "created_time",
                    "message",
                    "permalink_url",
                    "status_type",
                    "type",
                    "object_id",
                    "attachments",
                ]
            )
        },
    )
    _print_json("POST", post)

    try:
        post_insights = _graph_get(
            f"{post_id}/insights",
            token,
            {
                "metric": ",".join(
                    [
                        "post_impressions",
                        "post_impressions_unique",
                        "post_engaged_users",
                        "post_video_views",
                    ]
                )
            },
        )
        _print_json("POST_INSIGHTS", post_insights)
    except Exception as err:
        print(f"\nPOST_INSIGHTS error: {err}")

    object_id = post.get("object_id")
    if not object_id:
        print("\nNo object_id on post. This is commonly a link/feed post, not a native Facebook video object.")
        return

    try:
        video = _graph_get(
            object_id,
            token,
            {"fields": "id,created_time,description,length,permalink_url,status,title,views"},
        )
        _print_json("VIDEO_OBJECT", video)
    except Exception as err:
        print(f"\nVIDEO_OBJECT error: {err}")

    try:
        video_insights = _graph_get(
            f"{object_id}/video_insights",
            token,
            {
                "metric": ",".join(
                    [
                        "total_video_impressions",
                        "total_video_views",
                        "total_video_10s_views",
                        "total_video_avg_time_watched",
                    ]
                )
            },
        )
        _print_json("VIDEO_INSIGHTS", video_insights)
    except Exception as err:
        print(f"\nVIDEO_INSIGHTS error: {err}")


def list_recent_posts(page_id: str, token: str, limit: int) -> None:
    posts = _graph_get(
        f"{page_id}/posts",
        token,
        {
            "limit": str(limit),
            "fields": "id,created_time,type,status_type,object_id,permalink_url",
        },
    )
    _print_json("RECENT_POSTS", posts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Facebook post/video metrics via Graph API.")
    parser.add_argument("--post-id", help="Facebook post ID to inspect")
    parser.add_argument("--list-recent", type=int, default=0, help="List recent posts for FB_PAGE_ID")
    parser.add_argument("--page-id", default="", help="Override FB_PAGE_ID")
    parser.add_argument("--token", default="", help="Override FB_PAGE_ACCESS_TOKEN")
    args = parser.parse_args()

    _load_env()
    token = args.token.strip() or _require_env("FB_PAGE_ACCESS_TOKEN")
    page_id = args.page_id.strip() or os.getenv("FB_PAGE_ID", "").strip()

    if args.list_recent > 0:
        if not page_id:
            raise SystemExit("Missing page ID. Set FB_PAGE_ID or pass --page-id.")
        list_recent_posts(page_id, token, args.list_recent)

    if args.post_id:
        inspect_post(args.post_id, token)
    elif args.list_recent <= 0:
        raise SystemExit("Nothing to do. Pass --post-id and/or --list-recent N.")


if __name__ == "__main__":
    main()
