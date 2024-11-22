FROM python:3.11-slim

# Define build arguments
ARG DISCORD_CHANNEL_ID
ARG DISCORD_TOKEN
ARG BLUESKY_USERNAME
ARG BLUESKY_PASSWORD
ARG BSKY_LIST_URL
ARG CHECK_INTERVAL_MINUTES
ARG POST_AGE_MINUTES
ARG MAX_HISTORY_ENTRIES
ARG LOG_LEVEL="INFO"
ARG DEBUG_MODE="false"

# Set environment variables from build arguments
ENV DISCORD_CHANNEL_ID=${DISCORD_CHANNEL_ID}
ENV DISCORD_TOKEN=${DISCORD_TOKEN}
ENV BLUESKY_USERNAME=${BLUESKY_USERNAME}
ENV BLUESKY_PASSWORD=${BLUESKY_PASSWORD}
ENV BSKY_LIST_URL=${BSKY_LIST_URL}
ENV CHECK_INTERVAL_MINUTES=${CHECK_INTERVAL}
ENV POST_AGE_MINUTES=${POST_AGE_MINUTES}
ENV MAX_HISTORY_ENTRIES=${MAX_HISTORY_ENTRIES}
ENV LOG_LEVEL=${LOG_LEVEL}
ENV DEBUG_MODE=${DEBUG_MODE}

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser

# Upgrade pip
RUN pip install --upgrade pip

# Set working directory
WORKDIR /app


# Copy the app directory
COPY app/ .


# Fix perms
RUN chown -R appuser:appuser /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Make scripts executable
RUN chmod +x entrypoint.sh

# Switch to non-root user
USER appuser

# Use entrypoint script
ENTRYPOINT ["./entrypoint.sh"]
