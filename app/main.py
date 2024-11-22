import os
import sys
import json
import discord
import asyncio
import logging
import aiofiles
import traceback
from pathlib import Path
from atproto import Client
from discord.ext import tasks
from datetime import datetime, timedelta, timezone
from tenacity import retry, stop_after_attempt, wait_exponential
from urllib.parse import urlparse, unquote

# Configuration from environment variables with validation
def get_env_or_fail(key: str) -> str:
    value = os.getenv(key)
    if value is None:
        logging.error(f"Missing required environment variable: {key}")
        sys.exit(1)
    return value

# Required environment variables - no defaults, must be set in Docker
DISCORD_TOKEN = get_env_or_fail('DISCORD_TOKEN')
BLUESKY_USERNAME = get_env_or_fail('BLUESKY_USERNAME')
BLUESKY_PASSWORD = get_env_or_fail('BLUESKY_PASSWORD')
DISCORD_CHANNEL_ID = int(get_env_or_fail('DISCORD_CHANNEL_ID'))
CHECK_INTERVAL_MINUTES = int(get_env_or_fail('CHECK_INTERVAL_MINUTES'))
POST_AGE_MINUTES = int(get_env_or_fail('POST_AGE_MINUTES'))
LOG_LEVEL = get_env_or_fail('LOG_LEVEL')
BSKY_LIST_URL = get_env_or_fail('BSKY_LIST_URL')

# Convert web URL to AT Protocol URI
def convert_web_url_to_at_uri(web_url: str) -> str:
    """Convert Bluesky web URL to AT Protocol URI"""
    try:
        # Parse the URL
        parsed = urlparse(web_url)
        if not parsed.path.startswith('/profile/'):
            raise ValueError("Invalid Bluesky list URL format")
        
        # Split path components
        parts = parsed.path.split('/')
        if len(parts) != 5 or parts[3] != 'lists':
            raise ValueError("Invalid Bluesky list URL format")
        
        did = parts[2]
        list_id = parts[4]
        
        # Construct AT Protocol URI
        return f"at://{did}/app.bsky.graph.list/{list_id}"
    except Exception as e:
        logger.error(f"Error converting web URL to AT URI: {e}")
        sys.exit(1)

# Constants
POST_AGE_THRESHOLD = timedelta(minutes=POST_AGE_MINUTES)
HISTORY_FILE = 'data/last_processed_times.json'
BSKY_LIST_URI = convert_web_url_to_at_uri(BSKY_LIST_URL)

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize clients
discord_client = discord.Client(intents=discord.Intents.default())
bluesky = Client()

class RateLimiter:
    def __init__(self, calls_per_minute=30):
        self.calls_per_minute = calls_per_minute
        self.calls = []
        
    async def acquire(self):
        now = datetime.now(timezone.utc)
        self.calls = [t for t in self.calls if now - t < timedelta(minutes=1)]
        
        if len(self.calls) >= self.calls_per_minute:
            wait_time = 60 - (now - min(self.calls)).seconds
            logger.debug(f"Rate limit hit, waiting {wait_time} seconds")
            await asyncio.sleep(wait_time)
        
        self.calls.append(now)

rate_limiter = RateLimiter()

async def load_history():
    """Load last processed times from file"""
    try:
        if Path(HISTORY_FILE).exists():
            async with aiofiles.open(HISTORY_FILE, 'r') as f:
                content = await f.read()
                return json.loads(content)
        return {}
    except Exception as e:
        logger.error(f"Error loading history: {e}")
        return {}

async def save_history(history):
    """Save last processed times to file"""
    try:
        Path(HISTORY_FILE).parent.mkdir(exist_ok=True)
        async with aiofiles.open(HISTORY_FILE, 'w') as f:
            await f.write(json.dumps(history))
    except Exception as e:
        logger.error(f"Error saving history: {e}\n{traceback.format_exc()}")

def construct_image_url(blob_ref, did):
    """Construct the CDN URL for an image from its blob reference"""
    # Using full-size images instead of thumbnails for better quality
    return f"https://cdn.bsky.app/img/feed_fullsize/plain/{did}/{blob_ref.ref.link}@jpeg"

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def get_list_members():
    """Fetch members from the Bluesky list"""
    await rate_limiter.acquire()
    
    try:
        response = await asyncio.to_thread(
            bluesky.app.bsky.graph.get_list,
            params={'list': BSKY_LIST_URI}
        )
        
        if not response or not response.items:
            logger.warning("No members found in list")
            return []
        
        # Extract handles from the subject field of each list item
        members = []
        for item in response.items:
            if hasattr(item.subject, 'handle'):
                members.append(item.subject.handle)
        
        logger.info(f"Found {len(members)} members in list")
        return members
        
    except Exception as e:
        logger.error(f"Error fetching list members: {e}")
        return []

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def fetch_posts(handle):
    """Fetch posts with retry logic"""
    await rate_limiter.acquire()
    return await asyncio.to_thread(
        bluesky.get_author_feed,
        actor=handle
    )

async def process_images(post, embed):
    """Process and add images to the Discord embed"""
    try:
        embed_data = getattr(post.post.record, 'embed', None)
        if embed_data and hasattr(embed_data, 'images'):
            # Process multiple images if available
            for i, image in enumerate(embed_data.images):
                if hasattr(image, 'image'):
                    image_url = construct_image_url(image.image, post.post.author.did)
                    if i == 0:
                        # Set the first image as the main embed image
                        embed.set_image(url=image_url)
                    else:
                        # Add additional images as fields with their URLs
                        embed.add_field(
                            name=f"Additional Image {i+1}",
                            value=f"[View Image]({image_url})",
                            inline=True
                        )
    except Exception as img_error:
        logger.error(f"Error processing images: {img_error}")

async def create_post_embed(post, post_time):
    """Create Discord embed for a post"""
    post_url = f"https://bsky.app/profile/{post.post.author.handle}/post/{post.post.uri.split('/')[-1]}"
    
    embed = discord.Embed(
        description=post.post.record.text,
        color=discord.Color.blue(),
        timestamp=post_time,
        url=post_url
    )

    # Set author information
    embed.set_author(
        name=post.post.author.display_name or post.post.author.handle,
        url=f"https://bsky.app/profile/{post.post.author.handle}"
    )

    # Process images
    await process_images(post, embed)

    # Add link to original post
    embed.add_field(
        name="View on BlueSky",
        value=f"[Click here]({post_url})",
        inline=False
    )

    return embed

@discord_client.event
async def on_ready():
    """Called when Discord bot is ready"""
    global last_processed_times
    
    logger.info(f'{discord_client.user} has connected to Discord!')
    logger.info(f'Checking for new posts every {CHECK_INTERVAL_MINUTES} minute(s)')
    logger.info(f'Including posts up to {POST_AGE_MINUTES} minute(s) old')
    logger.info(f'Using Bluesky list: {BSKY_LIST_URI}')
    
    try:
        # Load history
        last_processed_times = await load_history()
        
        # Login to BlueSky
        profile = await asyncio.to_thread(
            bluesky.login,
            BLUESKY_USERNAME,
            BLUESKY_PASSWORD
        )
        logger.info(f'Connected to BlueSky as {profile.handle}')
        
        # Start background tasks
        check_subscriptions_updates.start()
        health_check.start()
    except Exception as e:
        logger.error(f'Failed to initialize: {e}\n{traceback.format_exc()}')
        await shutdown()

@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def check_subscriptions_updates():
    """Check for new posts from subscribed users"""
    global last_processed_times

    try:
        channel = discord_client.get_channel(DISCORD_CHANNEL_ID)
        if not channel:
            logger.error(f"Could not find channel with ID {DISCORD_CHANNEL_ID}")
            return

        handles = await get_list_members()
        if not handles:
            logger.warning("No handles found in Bluesky list.")
            return

        current_time = datetime.now(timezone.utc)

        for handle in handles:
            try:
                response = await fetch_posts(handle)
                
                if not response or not response.feed:
                    continue

                newest_time = None
                if handle in last_processed_times:
                    newest_time = datetime.fromisoformat(last_processed_times[handle])

                for post in reversed(response.feed):
                    post_time = datetime.fromisoformat(post.post.indexed_at.replace('Z', '+00:00'))

                    if post_age := current_time - post_time > POST_AGE_THRESHOLD:
                        continue

                    if newest_time and post_time <= newest_time:
                        continue

                    if newest_time is None or post_time > newest_time:
                        newest_time = post_time

                    logger.info(f"New post from {handle} at {post_time}")

                    embed = await create_post_embed(post, post_time)
                    await channel.send(embed=embed)

                if newest_time:
                    last_processed_times[handle] = newest_time.isoformat()
                    await save_history(last_processed_times)

            except Exception as user_error:
                logger.error(f"Error processing user {handle}: {user_error}\n{traceback.format_exc()}")

    except Exception as e:
        logger.error(f"Error checking updates: {e}\n{traceback.format_exc()}")

@tasks.loop(minutes=30)
async def health_check():
    """Periodic health check"""
    try:
        # Verify BlueSky connection by checking our own profile
        await asyncio.to_thread(
            bluesky.app.bsky.actor.get_profile,
            params={'actor': BLUESKY_USERNAME}
        )
        logger.debug("BlueSky connection healthy")
        
        # Verify Discord connection
        if not discord_client.is_ready():
            logger.error("Discord client disconnected")
            await shutdown()
            
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        await shutdown()

async def shutdown():
    """Handle graceful shutdown"""
    logger.info("Initiating shutdown")
    
    # Save current state
    await save_history(last_processed_times)
    
    # Cancel background tasks
    check_subscriptions_updates.cancel()
    health_check.cancel()
    
    # Close connections
    await discord_client.close()
    
    # Exit
    sys.exit(0)

# Initialize last processed times
last_processed_times = {}

# Start the bot
if __name__ == "__main__":
    discord_client.run(DISCORD_TOKEN)
