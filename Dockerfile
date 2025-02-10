FROM python:3.9-slim

# Install system dependencies including ffmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p data

# Run the monitor script
CMD ["python", "monitor.py"] 