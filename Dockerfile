FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY yt_transcript_extractor.py .

# Create output directory
RUN mkdir -p /app/transcripts

# Create volume for output
VOLUME ["/app/transcripts"]

# Make script executable
RUN chmod +x yt_transcript_extractor.py

# Set default command
ENTRYPOINT ["python", "yt_transcript_extractor.py"]
CMD ["--help"]