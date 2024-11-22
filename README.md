# Discord Bluesky Bot

A Docker-based bot that monitors a Bluesky list and posts updates from list members to a Discord channel. Posts include text content, images, and links to the original Bluesky posts.

## Features

- Monitors specified Bluesky list members for new posts
- Posts updates to a configured Discord channel
- Supports multiple images per post
- Rate limiting to comply with API restrictions
- Automatic retries for failed requests
- Health monitoring and graceful error handling

## Prerequisites

- Docker and Docker Compose
- Discord bot token
- Bluesky account credentials
- Discord channel ID
- Bluesky list URL

## Configuration

Set the following environment variables in `docker-compose.yml`:

```yaml
DISCORD_CHANNEL_ID: Your Discord channel ID
DISCORD_TOKEN: Your Discord bot token
BLUESKY_USERNAME: Your Bluesky username
BLUESKY_PASSWORD: Your Bluesky password
BSKY_LIST_URL: URL of the Bluesky list to monitor
CHECK_INTERVAL_MINUTES: How often to check for updates (default: 1)
POST_AGE_MINUTES: Maximum age of posts to include (default: 2)
MAX_HISTORY_ENTRIES: Number of historical entries to maintain
```

## Installation

1. Clone the repository
2. Configure environment variables in `docker-compose.yml`
3. Run:
```bash
docker-compose up -d
```

## Monitoring

The bot logs its activity to stdout, which can be viewed with:
```bash
docker-compose logs -f
```

