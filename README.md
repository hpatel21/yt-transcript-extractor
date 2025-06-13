# YouTube Transcript Extractor

A Python application that extracts transcripts from YouTube videos and saves them as individual text files. Perfect for preparing content for AI analysis, research, or documentation purposes.

## Features

- ✅ Extract transcripts from single YouTube videos
- ✅ Batch process multiple videos from file or command line
- ✅ Support for various YouTube URL formats
- ✅ Automatic filename generation using video titles
- ✅ Custom filename support for single videos
- ✅ Docker containerization for easy deployment
- ✅ Robust error handling and progress tracking
- ✅ Supports both manual and auto-generated transcripts

## Prerequisites

### Local Installation
- Python 3.8 or higher
- pip package manager

### Docker Installation
- Docker installed on your system

## Installation

### Option 1: Local Installation

1. Clone or download this repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

### Option 2: Docker Installation

1. Build the Docker image:
```bash
docker build -t yt-transcript-extractor .
```

## Usage

### Local Usage

#### Extract Single Video Transcript
```bash
# Basic usage
python yt_transcript_extractor.py -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# With custom filename
python yt_transcript_extractor.py -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ" -f "my_video_transcript.txt"

# Custom output directory
python yt_transcript_extractor.py -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ" -o "/path/to/output"
```

#### Extract Multiple Video Transcripts

**From file (recommended for large batches):**
```bash
# Create a file with URLs (one per line)
echo "https://www.youtube.com/watch?v=dQw4w9WgXcQ" > urls.txt
echo "https://www.youtube.com/watch?v=oHg5SJYRHA0" >> urls.txt

# Process all URLs
python yt_transcript_extractor.py -i urls.txt -o ./output
```

**From command line:**
```bash
python yt_transcript_extractor.py -m "https://www.youtube.com/watch?v=dQw4w9WgXcQ" "https://www.youtube.com/watch?v=oHg5SJYRHA0"
```

### Docker Usage

#### Extract Single Video Transcript
```bash
# Basic usage - transcript saved to ./transcripts on host
docker run --rm -v $(pwd)/transcripts:/app/transcripts yt-transcript-extractor -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# With custom filename
docker run --rm -v $(pwd)/transcripts:/app/transcripts yt-transcript-extractor -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ" -f "my_video.txt"
```

#### Extract Multiple Video Transcripts
```bash
# From file (mount the URLs file)
docker run --rm -v $(pwd)/urls.txt:/app/urls.txt -v $(pwd)/transcripts:/app/transcripts yt-transcript-extractor -i urls.txt

# From command line
docker run --rm -v $(pwd)/transcripts:/app/transcripts yt-transcript-extractor -m "https://www.youtube.com/watch?v=dQw4w9WgXcQ" "https://www.youtube.com/watch?v=oHg5SJYRHA0"
```

## Command Line Arguments

| Argument | Short | Description | Required |
|----------|-------|-------------|----------|
| `--url` | `-u` | Single YouTube video URL | * |
| `--input-file` | `-i` | File containing URLs (one per line) | * |
| `--multiple` | `-m` | Multiple URLs from command line | * |
| `--output-dir` | `-o` | Output directory (default: ./transcripts) | No |
| `--filename` | `-f` | Custom filename for single video | No |

*One of `--url`, `--input-file`, or `--multiple` is required.

## Supported YouTube URL Formats

The application supports various YouTube URL formats:
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/embed/VIDEO_ID`
- `https://www.youtube.com/v/VIDEO_ID`

## Output Format

- **File naming**: `{Video_Title}_{Video_ID}.txt` (auto-generated) or custom filename
- **Content**: Plain text transcript with sentences properly formatted
- **Encoding**: UTF-8
- **Location**: Specified output directory or `./transcripts/` by default

## Error Handling

The application handles various scenarios gracefully:
- Invalid YouTube URLs
- Videos without available transcripts
- Network connectivity issues
- File system errors
- Interrupted operations (Ctrl+C)

## Transcript Availability

The application attempts to extract transcripts in this order:
1. Manually created English transcripts (highest quality)
2. Auto-generated English transcripts
3. Any available English variant transcripts

**Note**: Not all YouTube videos have transcripts available. The application will skip videos without transcripts and continue processing others.

## Examples

### Example 1: Single Video
```bash
python yt_transcript_extractor.py -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```
Output: `./transcripts/Rick_Astley_Never_Gonna_Give_You_Up_dQw4w9WgXcQ.txt`

### Example 2: Multiple Videos from File
Create `urls.txt`:
```
https://www.youtube.com/watch?v=dQw4w9WgXcQ
https://www.youtube.com/watch?v=oHg5SJYRHA0
https://youtu.be/9bZkp7q19f0
```

Run:
```bash
python yt_transcript_extractor.py -i urls.txt -o ./my_transcripts
```

### Example 3: Docker with Volume Mounting
```bash
# Create output directory
mkdir transcripts

# Run with Docker
docker run --rm -v $(pwd)/transcripts:/app/transcripts yt-transcript-extractor -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Check output
ls transcripts/
```

## Use Cases for AI Analysis

These transcript files are perfect for:
- **Content Analysis**: Feed transcripts to AI models for sentiment analysis, topic extraction, or summarization
- **Research**: Analyze educational content, interviews, or presentations
- **Documentation**: Convert video content to searchable text format
- **Translation**: Use as source material for translation services
- **Accessibility**: Create text versions of video content

## Troubleshooting

### Common Issues

**1. "No transcript available"**
- Not all YouTube videos have transcripts
- Some videos may have transcripts in non-English languages only
- Try checking the video manually on YouTube for transcript availability

**2. "Invalid YouTube URL"**
- Ensure the URL is a valid YouTube video URL
- Check for typos in the URL
- Make sure it's a video URL, not a channel or playlist URL

**3. Docker permission issues**
- On Linux/Mac, ensure the output directory has proper permissions:
  ```bash
  chmod 755 transcripts/
  ```

**4. Network connectivity**
- Ensure stable internet connection
- Some corporate networks may block YouTube API access

### Getting Help

If you encounter issues:
1. Check the error message for specific details
2. Verify the YouTube URL works in a browser
3. Ensure all dependencies are installed correctly
4. For Docker issues, try rebuilding the image

## Technical Details

### Dependencies
- `youtube-transcript-api`: For transcript extraction
- `yt-dlp`: For video metadata and robust URL handling

### File Structure
```
yt-txt-transcriptor/
├── yt_transcript_extractor.py  # Main application
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker configuration
├── README.md                   # This file
└── transcripts/               # Default output directory
```

### Performance
- Processing speed depends on network connectivity
- Each video typically takes 2-5 seconds to process
- Batch processing includes progress indicators
- Failed videos don't interrupt the batch process

## License

This project is provided as-is for educational and research purposes. Please respect YouTube's Terms of Service when using this tool.

## Contributing

Feel free to submit issues, feature requests, or pull requests to improve this tool.