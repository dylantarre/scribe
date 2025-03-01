FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir git+https://github.com/openai/whisper.git

# Create directories
RUN mkdir -p transcripts/fantano transcripts/theneedledrop config

# Copy application code
COPY . .

# Move .env.example to config directory
RUN cp .env.example config/.env.example

# Make scripts executable
RUN chmod +x latest_video.py monitor.py

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sys, os; sys.exit(0 if os.path.exists('/app') else 1)"

# Command to run when container starts
CMD ["python", "latest_video.py", "--channel", "@fantano"] 