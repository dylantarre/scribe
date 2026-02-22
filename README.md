# YouTube Transcription Service

A Docker-based service that automatically downloads and transcribes YouTube videos from specified channels.

## Features

- Automatically fetches the latest videos from YouTube channels
- Transcribes audio using OpenAI's Whisper model
- Supports monitoring channels for new videos
- Persists transcripts and processed video data
- IP rotation for reliable YouTube downloads

## Docker Setup

### Prerequisites

- Docker and Docker Compose installed on your server
- A `.env` file with your configuration (copy from `.env.example`)

### Quick Start

1. Clone this repository to your server (make sure to specify the `scribe` branch):
   ```bash
   git clone -b scribe https://github.com/dylantarre/scribe.git
   cd scribe
   ```

2. Create your `.env` file:
   ```bash
   cp .env.example .env
   ```

3. Edit the `.env` file with your API keys and configuration.

4. Build and start the Docker container:
   ```bash
   docker-compose up -d
   ```

## Portainer Deployment

This service can be easily deployed using Portainer:

1. In Portainer, navigate to "Stacks" and click "Add stack"
2. Enter a name for your stack (e.g., "youtube-transcription")
3. In the "Web editor" tab, paste the contents of your `docker-compose.yml` file
4. Click "Deploy the stack"
5. After deployment, you'll need to:
   - Create a `.env` file in the stack's volume directory
   - Configure the environment variables as described in `.env.example`

### Volume Management in Portainer

The service uses three named volumes that will persist your data:
- `transcripts`: Contains all transcription output files
- `database`: Contains the database tracking processed videos
- `config`: Contains configuration files

To set up your environment in Portainer:
1. After deploying the stack, go to "Volumes" in Portainer
2. Find the `config` volume for your stack
3. Use the "Browse" button to navigate into the volume
4. Create a new file named `.env` based on the `.env.example` template
5. Add your configuration values to this file

### Configuration Options

In your `.env` file:

- `ENABLE_MONITORING`: Set to 1 to enable automatic monitoring
- `MONITORING_INTERVAL`: How often to check for new videos (in seconds)
- `MONITOR_CHANNELS`: Comma-separated list of YouTube channels to monitor
- `FB_AUTO_REPOST`: Set to 1 to auto-repost videos to Facebook
- `FB_PAGE_ID`: Your Facebook Page ID
- `FB_PAGE_ACCESS_TOKEN`: A page access token with permission to publish posts
- `FB_NORMAL_VIDEO_DELAY_SECONDS`: Delay for non-Short videos before posting (default: 86400)
- `FB_SHORTS_AS_REELS`: If set to 1, Shorts are uploaded to Reels first
- `FB_REPOST_MESSAGE_TEMPLATE`: Facebook post template with placeholders `{channel}`, `{title}`, `{description}`, `{url}` (omit `{url}` if you do not want YouTube links in captions)
- `CLASSIC_AUTO_REPOST`: Enable weekly classic repost selection
- `CLASSIC_CHANNELS`: Channels to select classics from
- `CLASSIC_POST_DAY`: Day to run classic selection (e.g. `wednesday`)
- `CLASSIC_POST_HOUR`: Local hour for classic selection window
- `CLASSIC_POST_MINUTE`: Local minute for classic selection window
- `CLASSIC_POST_TZ`: Timezone for classic scheduling (e.g. `America/Chicago`)
- `CLASSIC_TOP_CANDIDATES`: How many top popular videos to scan per channel
- `CLASSIC_INCLUDE_SHORTS`: Include Shorts in classic selection (`0` recommended)

### Facebook Reposting Behavior

- Shorts are reposted immediately.
- Normal videos are reposted after `FB_NORMAL_VIDEO_DELAY_SECONDS` (default: 1 day).
- YouTube description text is saved and reused in the Facebook post body.
- Shorts attempt Reels upload (`/video_reels`) and fall back to normal video upload if Reels is unavailable.
- Posts are uploaded as native Facebook video posts when the local video file is available.
- Weekly classics can be queued once per week (Wednesday morning by default) from top popular videos, with duplicate prevention.

## IP Rotation for YouTube Downloads

This service includes IP rotation functionality to avoid rate limiting when downloading videos from YouTube:

- Uses Evomi proxy service for residential IPs
- Automatically rotates between multiple proxy configurations
- Implements retry logic with exponential backoff
- Marks failed proxies and avoids them for 5 minutes
- Falls back to configured proxies if the Evomi API fails

To configure proxy settings, add the following to your `.env` file:

```
EVOMI_API_KEY=your_api_key
EVOMI_HOST=core-residential.evomi.com
EVOMI_USER=your_username
EVOMI_PASS=your_password
```

### Using the Service

#### Transcribe a Specific Channel

```bash
docker-compose run --rm transcription python latest_video.py --channel @channelname
```

#### Monitor Channels Continuously

```bash
docker-compose run --rm transcription python monitor.py
```

## Output Files

Transcripts are saved in the `transcripts/` directory, organized by channel name. The following formats are generated:

- `.txt`: Plain text transcript
- `.vtt`: WebVTT format with timestamps
- `.srt`: SubRip format with timestamps
- `.json`: JSON format with detailed information

## Customization

You can modify the `docker-compose.yml` file to change the default behavior or add additional configuration.

## Troubleshooting

- If you encounter memory issues, you may need to allocate more memory to Docker
- For large videos, consider using the `medium` model instead of `large` for faster processing
- Check the logs with `docker-compose logs` if you encounter any issues 
