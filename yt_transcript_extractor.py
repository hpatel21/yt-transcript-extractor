#!/usr/bin/env python3
"""
YouTube Transcript Extractor

A Python application that extracts transcripts from YouTube videos and saves them as text files.
Supports single videos and batch processing of multiple videos.
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import re

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    import yt_dlp
except ImportError as e:
    print(f"Error: Required package not found. {e}")
    print("Please install required packages: pip install -r requirements.txt")
    sys.exit(1)


class YouTubeTranscriptExtractor:
    """Main class for extracting YouTube video transcripts."""
    
    def __init__(self, output_dir="./transcripts"):
        """
        Initialize the extractor.
        
        Args:
            output_dir (str): Directory to save transcript files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def extract_video_id(self, url):
        """
        Extract YouTube video ID from various URL formats.
        
        Args:
            url (str): YouTube video URL
            
        Returns:
            str: Video ID or None if invalid
        """
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'(?:embed\/)([0-9A-Za-z_-]{11})',
            r'(?:v\/)([0-9A-Za-z_-]{11})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None
    
    def get_video_title(self, video_id):
        """
        Get video title using yt-dlp.
        
        Args:
            video_id (str): YouTube video ID
            
        Returns:
            str: Video title or video ID if title unavailable
        """
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                title = info.get('title', video_id)
                # Clean title for filename
                title = re.sub(r'[<>:"/\\|?*]', '_', title)
                return title[:100]  # Limit length
        except Exception as e:
            print(f"Warning: Could not fetch title for {video_id}: {e}")
            return video_id
    
    def extract_transcript(self, video_id):
        """
        Extract transcript for a single video.
        
        Args:
            video_id (str): YouTube video ID
            
        Returns:
            str: Transcript text or None if unavailable
        """
        try:
            # Try to get transcript in preferred languages
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Try to get manually created transcript first
            try:
                transcript = transcript_list.find_manually_created_transcript(['en'])
            except:
                # Fall back to auto-generated transcript
                try:
                    transcript = transcript_list.find_generated_transcript(['en'])
                except:
                    # Try any available transcript
                    transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
            
            transcript_data = transcript.fetch()
            
            # Combine all text segments
            full_text = []
            for entry in transcript_data:
                text = entry['text'].strip()
                if text:
                    full_text.append(text)
            
            return ' '.join(full_text)
            
        except Exception as e:
            print(f"Error extracting transcript for {video_id}: {e}")
            return None
    
    def save_transcript(self, transcript, filename):
        """
        Save transcript to file.
        
        Args:
            transcript (str): Transcript text
            filename (str): Output filename
        """
        filepath = self.output_dir / filename
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(transcript)
            print(f"✓ Transcript saved: {filepath}")
        except Exception as e:
            print(f"✗ Error saving transcript to {filepath}: {e}")
    
    def process_video(self, url, custom_filename=None):
        """
        Process a single YouTube video.
        
        Args:
            url (str): YouTube video URL
            custom_filename (str, optional): Custom output filename
            
        Returns:
            bool: True if successful, False otherwise
        """
        video_id = self.extract_video_id(url)
        if not video_id:
            print(f"✗ Invalid YouTube URL: {url}")
            return False
        
        print(f"Processing video: {video_id}")
        
        # Get transcript
        transcript = self.extract_transcript(video_id)
        if not transcript:
            print(f"✗ No transcript available for video: {video_id}")
            return False
        
        # Determine filename
        if custom_filename:
            filename = custom_filename if custom_filename.endswith('.txt') else f"{custom_filename}.txt"
        else:
            title = self.get_video_title(video_id)
            filename = f"{title}_{video_id}.txt"
        
        # Save transcript
        self.save_transcript(transcript, filename)
        return True
    
    def process_multiple_videos(self, urls, output_dir=None):
        """
        Process multiple YouTube videos.
        
        Args:
            urls (list): List of YouTube video URLs
            output_dir (str, optional): Output directory override
        """
        if output_dir:
            original_output_dir = self.output_dir
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(exist_ok=True)
        
        successful = 0
        total = len(urls)
        
        print(f"Processing {total} videos...")
        
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{total}] {url}")
            if self.process_video(url.strip()):
                successful += 1
        
        print(f"\n{'='*50}")
        print(f"Completed: {successful}/{total} videos processed successfully")
        
        if output_dir:
            self.output_dir = original_output_dir


def main():
    """Main function to handle command line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract transcripts from YouTube videos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single video
  python yt_transcript_extractor.py -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  
  # Single video with custom filename
  python yt_transcript_extractor.py -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ" -f "my_transcript.txt"
  
  # Multiple videos from file
  python yt_transcript_extractor.py -i urls.txt -o ./output
  
  # Multiple videos from command line
  python yt_transcript_extractor.py -m "url1" "url2" "url3"
        """
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-u", "--url", help="Single YouTube video URL")
    group.add_argument("-i", "--input-file", help="File containing YouTube URLs (one per line)")
    group.add_argument("-m", "--multiple", nargs="+", help="Multiple YouTube URLs")
    
    parser.add_argument("-o", "--output-dir", default="./transcripts", 
                       help="Output directory for transcript files (default: ./transcripts)")
    parser.add_argument("-f", "--filename", help="Custom filename for single video (only with -u)")
    
    args = parser.parse_args()
    
    # Initialize extractor
    extractor = YouTubeTranscriptExtractor(args.output_dir)
    
    try:
        if args.url:
            # Single video
            success = extractor.process_video(args.url, args.filename)
            sys.exit(0 if success else 1)
            
        elif args.input_file:
            # Multiple videos from file
            if not os.path.exists(args.input_file):
                print(f"✗ Input file not found: {args.input_file}")
                sys.exit(1)
            
            with open(args.input_file, 'r') as f:
                urls = [line.strip() for line in f.readlines() if line.strip()]
            
            if not urls:
                print("✗ No URLs found in input file")
                sys.exit(1)
            
            extractor.process_multiple_videos(urls)
            
        elif args.multiple:
            # Multiple videos from command line
            extractor.process_multiple_videos(args.multiple)
        
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()