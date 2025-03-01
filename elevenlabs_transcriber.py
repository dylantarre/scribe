#!/usr/bin/env python3

import os
import json
import sqlite3
import requests
import re
import random
from datetime import datetime
from dotenv import load_dotenv
import textwrap
from elevenlabs.client import ElevenLabs
from io import BytesIO
from pydub import AudioSegment
import math
from pydub.silence import detect_silence

# Try to import NLP libraries, but provide fallback if not available
try:
    import nltk
    from nltk.tokenize import sent_tokenize
    NLTK_AVAILABLE = True
    # Download necessary NLTK data if not already present
    try:
        nltk.data.find('tokenizers/punkt_tab')
    except LookupError:
        print("Downloading NLTK punkt_tab tokenizer...")
        nltk.download('punkt_tab', quiet=True)
except ImportError:
    NLTK_AVAILABLE = False
    print("NLTK not available. Using regex-based text processing instead.")

class ElevenLabsTranscriber:
    def __init__(self, model_name="scribe_v1"):
        """
        Initialize ElevenLabs transcriber
        
        Args:
            model_name (str): Model name to use for transcription (default: scribe_v1)
                Options: scribe_v1, scribe_v1_base
        """
        load_dotenv()
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise ValueError("ElevenLabs API key not found. Please set ELEVENLABS_API_KEY in your .env file.")
        
        # Initialize client
        self.client = ElevenLabs(api_key=self.api_key)
        self.model_name = model_name
        self.max_duration = 480  # Maximum duration in seconds for diarization
        
        # Patterns for detecting topic changes and paragraph breaks
        self.topic_change_phrases = re.compile(
            r'\b(moving on|next|let\'s talk about|turning to|switching to|'
            r'on another note|speaking of|as for|regarding|concerning|'
            r'with respect to|when it comes to|let\'s move on to|'
            r'shifting gears|changing topics|also|additionally)\b',
            re.IGNORECASE
        )
        
        # Improved regex for sentence splitting
        self.sentence_pattern = re.compile(r'(?<=[.!?])\s+')
        
        # Filler word pattern for manual filtering
        self.filler_pattern = re.compile(
            r'\b(?:um+|uh+|er+|ah+|mm+|hm+|like|you\s+know|i\s+mean|kind\s+of|sort\s+of|'
            r'basically|literally|actually|anyway|anyhow|so|well|right|okay|now)\b',
            re.IGNORECASE
        )
        
        # Cleanup patterns for regex-based text cleanup
        self.cleanup_patterns = [
            (r'\(\s*\)', ''),  # Empty parentheses
            (r'\([^)]*(?:laugh|sigh|cough|breath|inaudible|unclear)[^)]*\)', ''),  # Non-verbal indicators
            (r'\s+([.,!?;:])', r'\1'),  # Spaces before punctuation
            (r'([.,!?;:])\1+', r'\1'),  # Repeated punctuation
            (r'[.,!?;:]{2,}', '.'),  # Multiple different punctuation
            (r'([.,!?;:])([a-zA-Z])', r'\1 \2'),  # Missing spaces after punctuation
            (r'\b(\w+)(?:\s+\1\b)+', r'\1'),  # Repeated words
            (r'\b(\w+\s+\w+)(?:\s+\1\b)+', r'\1'),  # Repeated phrases
            (r'\b(I|i)(?:\s+\1\b)+', r'I'),  # Repeated I's
            (r'\b(the|The)(?:\s+\1\b)+', r'the'),  # Repeated the's
            (r'\b(a|A)(?:\s+\1\b)+', r'a'),  # Repeated a's
            (r'\b(and|And)(?:\s+\1\b)+', r'and'),  # Repeated and's
            (r'\b(but|But)(?:\s+\1\b)+', r'but'),  # Repeated but's
            (r'\b(that|That)(?:\s+\1\b)+', r'that'),  # Repeated that's
            (r'\b(this|This)(?:\s+\1\b)+', r'this'),  # Repeated this's
            (r'\b(it|It)(?:\s+\1\b)+', r'it'),  # Repeated it's
            (r'\b(in|In)(?:\s+\1\b)+', r'in'),  # Repeated in's
            (r'\b(on|On)(?:\s+\1\b)+', r'on'),  # Repeated on's
            (r'\b(with|With)(?:\s+\1\b)+', r'with'),  # Repeated with's
            (r'\b(for|For)(?:\s+\1\b)+', r'for'),  # Repeated for's
            (r'\b(to|To)(?:\s+\1\b)+', r'to'),  # Repeated to's
            (r'\b(of|Of)(?:\s+\1\b)+', r'of'),  # Repeated of's
            (r'\b(is|Is)(?:\s+\1\b)+', r'is'),  # Repeated is's
            (r'\b(was|Was)(?:\s+\1\b)+', r'was'),  # Repeated was's
            (r'\b(were|Were)(?:\s+\1\b)+', r'were'),  # Repeated were's
            (r'\b(are|Are)(?:\s+\1\b)+', r'are'),  # Repeated are's
            (r'\b(have|Have)(?:\s+\1\b)+', r'have'),  # Repeated have's
            (r'\b(has|Has)(?:\s+\1\b)+', r'has'),  # Repeated has's
            (r'\b(had|Had)(?:\s+\1\b)+', r'had'),  # Repeated had's
            (r'\b(will|Will)(?:\s+\1\b)+', r'will'),  # Repeated will's
            (r'\b(would|Would)(?:\s+\1\b)+', r'would'),  # Repeated would's
            (r'\b(could|Could)(?:\s+\1\b)+', r'could'),  # Repeated could's
            (r'\b(should|Should)(?:\s+\1\b)+', r'should'),  # Repeated should's
            (r'\b(can|Can)(?:\s+\1\b)+', r'can'),  # Repeated can's
            (r'\b(may|May)(?:\s+\1\b)+', r'may'),  # Repeated may's
            (r'\b(might|Might)(?:\s+\1\b)+', r'might'),  # Repeated might's
            (r'\b(must|Must)(?:\s+\1\b)+', r'must'),  # Repeated must's
            (r'\b(shall|Shall)(?:\s+\1\b)+', r'shall'),  # Repeated shall's
            (r'\b(should|Should)(?:\s+\1\b)+', r'should'),  # Repeated should's
            (r'(?:^|\s),(?:\s|$)', ' '),  # Remove standalone commas
            (r',\s*,', ','),  # Remove double commas
            (r',\s*\.', '.'),  # Remove comma before period
            (r'\s*,\s*$', ''),  # Remove trailing comma
            (r'^\s*,\s*', ''),  # Remove leading comma
            (r'\s+', ' '),  # Normalize spaces
            (r'^\s+|\s+$', ''),  # Trim
            (r'\s*([.!?])\s*$', r'\1'),  # Clean ending punctuation
            (r'(?<=[.!?])\s+([a-z])', lambda m: ' ' + m.group(1).upper()),  # Capitalize after sentence
            (r'\s+\.\s+', '. '),  # Fix spaces around periods
            (r'\s+as\s+\.\s+', ' as '),  # Fix rogue periods after "as" but keep "as"
            (r'\s+as\s+\.\s*([A-Z])', r' as. \1'),  # Fix rogue periods after "as" followed by capital letter
            (r'\s+LP\s+as\s+\.\s+', ' LP as '),  # Fix specific case for "LP as ." but keep "as"
            (r'\s+(\w+)\s+as\s+\.\s+', r' \1 as ')  # Fix word followed by "as ." but keep both words
        ]

    def split_audio(self, audio_file_path):
        """
        Split audio file into chunks of max_duration seconds
        
        Args:
            audio_file_path (str): Path to the audio file
            
        Returns:
            list: List of temporary file paths containing the audio chunks
        """
        print(f"Loading audio file: {audio_file_path}")
        audio = AudioSegment.from_mp3(audio_file_path)
        duration_ms = len(audio)
        chunk_size_ms = self.max_duration * 1000
        chunks = []
        
        # Calculate number of chunks needed
        num_chunks = math.ceil(duration_ms / chunk_size_ms)
        print(f"Splitting audio into {num_chunks} chunks...")
        
        # Create temporary directory for chunks if it doesn't exist
        temp_dir = os.path.join(os.path.dirname(audio_file_path), "temp_chunks")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Split audio into chunks
        for i in range(num_chunks):
            start_ms = i * chunk_size_ms
            end_ms = min((i + 1) * chunk_size_ms, duration_ms)
            
            chunk = audio[start_ms:end_ms]
            chunk_path = os.path.join(temp_dir, f"chunk_{i}.mp3")
            chunk.export(chunk_path, format="mp3")
            chunks.append(chunk_path)
        
        return chunks

    def split_audio_at_silence(self, audio_file_path):
        """
        Split audio file at silence points to avoid cutting words
        """
        print(f"Loading audio file: {audio_file_path}")
        audio = AudioSegment.from_mp3(audio_file_path)
        duration_ms = len(audio)
        max_chunk_ms = self.max_duration * 1000
        chunks = []
        
        # Create temporary directory for chunks
        temp_dir = os.path.join(os.path.dirname(audio_file_path), "temp_chunks")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Parameters for silence detection
        silence_thresh = -40  # dB
        min_silence_len = 500  # ms
        
        # Find silence points
        print("Detecting silence points for intelligent splitting...")
        silence_points = [0]  # Start with beginning of audio
        
        # Find silence points that would create chunks of appropriate size
        current_pos = 0
        while current_pos < duration_ms:
            target_pos = current_pos + max_chunk_ms
            if target_pos >= duration_ms:
                silence_points.append(duration_ms)
                break
            
            # Look for silence in a window around the target position
            window_start = max(0, target_pos - 10000)  # 10 seconds before target
            window_end = min(duration_ms, target_pos + 10000)  # 10 seconds after target
            window = audio[window_start:window_end]
            
            # Find silence points in the window
            silence_ranges = detect_silence(
                window, min_silence_len=min_silence_len, silence_thresh=silence_thresh
            )
            
            if silence_ranges:
                # Find silence closest to target position
                closest_silence = min(silence_ranges, key=lambda x: abs((x[0] + window_start) - target_pos))
                silence_point = closest_silence[0] + window_start
                silence_points.append(silence_point)
                current_pos = silence_point
            else:
                # If no silence found, just use the target position
                silence_points.append(target_pos)
                current_pos = target_pos
        
        # Create chunks based on silence points
        print(f"Splitting audio at {len(silence_points)-1} detected silence points...")
        for i in range(len(silence_points) - 1):
            start_ms = silence_points[i]
            end_ms = silence_points[i + 1]
            
            chunk = audio[start_ms:end_ms]
            chunk_path = os.path.join(temp_dir, f"chunk_{i}.mp3")
            chunk.export(chunk_path, format="mp3")
            chunks.append(chunk_path)
        
        return chunks

    def transcribe(self, audio_file_path, filter_filler_words=False, add_paragraphs=True):
        """
        Transcribe an audio file using ElevenLabs API
        
        Args:
            audio_file_path (str): Path to the audio file
            filter_filler_words (bool): Whether to filter out filler words
            add_paragraphs (bool): Whether to add paragraph breaks to the text
            
        Returns:
            dict: Transcription result with segments
        """
        if not os.path.exists(audio_file_path):
            raise FileNotFoundError(f"Audio file not found: {audio_file_path}")
        
        print(f"Transcribing audio file: {audio_file_path}")
        print(f"Using model: {self.model_name}")
        
        try:
            # Split audio into chunks
            chunk_paths = self.split_audio_at_silence(audio_file_path)
            full_text = []
            all_segments = []
            
            # Process each chunk
            for i, chunk_path in enumerate(chunk_paths):
                print(f"Processing chunk {i+1}/{len(chunk_paths)}...")
                
                # Read the audio chunk
                with open(chunk_path, "rb") as audio_file:
                    audio_data = BytesIO(audio_file.read())
                
                # Transcribe the chunk
                chunk_transcription = self.client.speech_to_text.convert(
                    file=audio_data,
                    model_id=self.model_name,
                    tag_audio_events=True,
                    language_code="eng",
                    diarize=True
                )
                
                # Get the chunk text
                chunk_text = chunk_transcription.text
                chunk_text = self._clean_text(chunk_text)
                
                if filter_filler_words:
                    chunk_text = self._filter_filler_words(chunk_text)
                
                full_text.append(chunk_text)
                
                # Process segments if available
                if hasattr(chunk_transcription, "segments"):
                    for segment in chunk_transcription.segments:
                        segment_text = segment.text
                        segment_text = self._clean_text(segment_text)
                        if filter_filler_words:
                            segment_text = self._filter_filler_words(segment_text)
                        
                        # Adjust segment timing based on chunk position
                        start_time = getattr(segment, "start", 0) + (i * self.max_duration)
                        end_time = getattr(segment, "end", 0) + (i * self.max_duration)
                        
                        all_segments.append({
                            "text": segment_text,
                            "start": start_time,
                            "end": end_time,
                            "speaker": getattr(segment, "speaker", "unknown")
                        })
            
            # Combine all text
            combined_text = " ".join(full_text)
            
            # Add paragraph breaks if requested
            if add_paragraphs:
                combined_text = self._add_paragraph_breaks(combined_text)
            
            # Clean up temporary files
            for chunk_path in chunk_paths:
                try:
                    os.remove(chunk_path)
                except Exception as e:
                    print(f"Warning: Could not remove temporary file {chunk_path}: {e}")
            try:
                os.rmdir(os.path.dirname(chunk_paths[0]))
            except Exception as e:
                print(f"Warning: Could not remove temporary directory: {e}")
            
            # Create the final transcription result
            result = {
                "text": combined_text,
                "segments": all_segments,
                "language": "eng",
                "model": self.model_name,
                "duration": len(all_segments) * self.max_duration if all_segments else 0,
                "filler_words_filtered": filter_filler_words,
                "paragraphs_added": add_paragraphs
            }
            
            return result
            
        except Exception as e:
            print(f"Error during transcription: {e}")
            raise
    
    def _filter_filler_words(self, text):
        """
        Filter out filler words from text
        
        Args:
            text (str): Text to filter
            
        Returns:
            str: Text with filler words removed
        """
        if not text:
            return text
        
        # Replace filler words with empty string
        filtered_text = self.filler_pattern.sub('', text)
        
        # Clean up any double spaces and normalize whitespace
        filtered_text = re.sub(r'\s+', ' ', filtered_text)
        
        return filtered_text.strip()
    
    def _clean_text(self, text):
        """Apply regex-based text cleanup without using OpenRouter"""
        if not text:
            return text
        
        # Apply all cleanup patterns with regex
        for pattern, replacement in self.cleanup_patterns:
            text = re.sub(pattern, replacement, text)
        
        # Additional cleanup for repeated words and phrases
        # Fix repeated single words
        text = re.sub(r'\b(\w+)(?:\s+\1\b)+', r'\1', text)
        
        # Fix repeated phrases (2-3 words)
        text = re.sub(r'\b(\w+\s+\w+)(?:\s+\1\b)+', r'\1', text)
        text = re.sub(r'\b(\w+\s+\w+\s+\w+)(?:\s+\1\b)+', r'\1', text)
        
        # Remove filler words
        filler_words = [r'\bum+\b', r'\buh+\b', r'\ber+\b', r'\bah+\b', r'\bmm+\b', r'\bhm+\b']
        for filler in filler_words:
            text = re.sub(filler, '', text, flags=re.IGNORECASE)
        
        # Fix spacing and punctuation
        text = re.sub(r'\s+', ' ', text)  # Normalize spaces
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)  # Remove spaces before punctuation
        text = re.sub(r'([.,!?;:])([a-zA-Z])', r'\1 \2', text)  # Add spaces after punctuation
        
        # Capitalize first letter of sentences
        text = re.sub(r'(?<=[.!?])\s+([a-z])', lambda m: ' ' + m.group(1).upper(), text)
        
        # Final cleanup for any remaining issues
        text = re.sub(r'\s+', ' ', text)  # Normalize spaces again
        text = text.strip()
        
        return text
    
    def _add_paragraph_breaks(self, text):
        """Add paragraph breaks to improve readability."""
        if NLTK_AVAILABLE:
            try:
                # Use NLTK's sentence tokenizer
                sentences = sent_tokenize(text)
                # Group sentences into paragraphs (every 3-5 sentences)
                paragraphs = []
                current_paragraph = []
                
                for i, sentence in enumerate(sentences):
                    current_paragraph.append(sentence)
                    # Create a new paragraph every 3-5 sentences
                    if (i + 1) % random.randint(3, 5) == 0 and i < len(sentences) - 1:
                        paragraphs.append(' '.join(current_paragraph))
                        current_paragraph = []
                
                # Add any remaining sentences
                if current_paragraph:
                    paragraphs.append(' '.join(current_paragraph))
                
                # Ensure each paragraph starts with a capital letter
                capitalized_paragraphs = []
                for paragraph in paragraphs:
                    if paragraph and paragraph[0].islower():
                        paragraph = paragraph[0].upper() + paragraph[1:]
                    capitalized_paragraphs.append(paragraph)
                
                return '\n\n'.join(capitalized_paragraphs)
            except Exception as e:
                print(f"Error tokenizing sentences with NLTK: {str(e)}")
                print("Falling back to regex-based sentence tokenization")
        
        # Fallback to regex-based sentence splitting
        sentences = re.split(r'(?<=[.!?])\s+', text)
        paragraphs = []
        current_paragraph = []
        
        for i, sentence in enumerate(sentences):
            current_paragraph.append(sentence)
            # Create a new paragraph every 3-5 sentences
            if (i + 1) % random.randint(3, 5) == 0 and i < len(sentences) - 1:
                paragraphs.append(' '.join(current_paragraph))
                current_paragraph = []
        
        # Add any remaining sentences
        if current_paragraph:
            paragraphs.append(' '.join(current_paragraph))
        
        # Ensure each paragraph starts with a capital letter
        capitalized_paragraphs = []
        for paragraph in paragraphs:
            if paragraph and paragraph[0].islower():
                paragraph = paragraph[0].upper() + paragraph[1:]
            capitalized_paragraphs.append(paragraph)
        
        return '\n\n'.join(capitalized_paragraphs)
    
    def save_transcript(self, transcription, output_dir, filename_base, video_metadata=None):
        """
        Save transcription to various file formats
        
        Args:
            transcription (dict): Transcription result
            output_dir (str): Directory to save files
            filename_base (str): Base filename without extension
            video_metadata (dict): Optional metadata about the video
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # Get the text and segments
        text = transcription.get("text", "")
        segments = transcription.get("segments", [])
        
        # Save as JSON
        json_path = os.path.join(output_dir, f"{filename_base}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(transcription, f, indent=2, ensure_ascii=False)
        
        # Save as plain text
        txt_path = os.path.join(output_dir, f"{filename_base}.txt")
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(text)
        
        # Save as markdown with metadata
        md_path = os.path.join(output_dir, f"{filename_base}.md")
        with open(md_path, 'w', encoding='utf-8') as f:
            # Add title if available
            if video_metadata and 'title' in video_metadata:
                f.write(f"# {video_metadata['title']}\n\n")
            
            # Add metadata
            if video_metadata:
                f.write(f"**Channel:** {video_metadata.get('channel', 'Unknown')}\n")
                f.write(f"**Video ID:** {video_metadata.get('video_id', 'Unknown')}\n")
            
            # Add transcription date
            f.write(f"**Transcription Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Add notes about processing
            if transcription.get("filler_words_filtered", False):
                f.write("*Note: Filler words have been filtered from this transcription.*\n\n")
            
            if transcription.get("paragraphs_added", False):
                f.write("*Note: Paragraph breaks have been automatically added for readability.*\n\n")
            
            # Add transcription header
            f.write("## Transcription\n\n")
            
            # Add the transcription text
            f.write(text)
        
        print(f"Transcripts saved to {output_dir}")
        
        # Update database with transcription info
        self._update_database(transcription, filename_base, video_metadata)
    
    def _update_database(self, transcription, video_id, video_metadata=None):
        """
        Update the database with transcription information
        
        Args:
            transcription (dict): Transcription result
            video_id (str): Video ID
            video_metadata (dict): Optional metadata about the video
        """
        try:
            # Connect to the database
            conn = sqlite3.connect('transcriptions.db')
            cursor = conn.cursor()
            
            # Check if the language column exists
            cursor.execute("PRAGMA table_info(transcriptions)")
            columns = [column[1] for column in cursor.fetchall()]
            
            # Create table if it doesn't exist or alter it if needed
            if 'transcriptions' not in columns:
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS transcriptions (
                    video_id TEXT PRIMARY KEY,
                    channel TEXT,
                    title TEXT,
                    transcription_date TEXT,
                    duration REAL,
                    model TEXT,
                    filler_words_filtered INTEGER,
                    paragraphs_added INTEGER
                )
                ''')
            
            # Add language column if it doesn't exist
            if 'language' not in columns:
                try:
                    cursor.execute('ALTER TABLE transcriptions ADD COLUMN language TEXT')
                    print("Added language column to transcriptions table")
                except sqlite3.OperationalError:
                    # Column might have been added in another process
                    pass
            
            # Check if the video already exists
            cursor.execute("SELECT video_id FROM transcriptions WHERE video_id = ?", (video_id,))
            result = cursor.fetchone()
            
            # Prepare data
            channel = video_metadata.get('channel', 'unknown') if video_metadata else 'unknown'
            title = video_metadata.get('title', 'unknown') if video_metadata else 'unknown'
            
            if result:
                # Update existing record
                cursor.execute('''
                UPDATE transcriptions SET
                    channel = ?,
                    title = ?,
                    transcription_date = ?,
                    duration = ?,
                    model = ?,
                    filler_words_filtered = ?,
                    paragraphs_added = ?,
                    language = ?
                WHERE video_id = ?
                ''', (
                    channel,
                    title,
                    datetime.now().isoformat(),
                    transcription.get('duration', 0),
                    transcription.get('model', ''),
                    1 if transcription.get('filler_words_filtered', False) else 0,
                    1 if transcription.get('paragraphs_added', False) else 0,
                    transcription.get('language', ''),
                    video_id
                ))
            else:
                # Insert new record
                cursor.execute('''
                INSERT INTO transcriptions (
                    video_id,
                    channel,
                    title,
                    transcription_date,
                    duration,
                    model,
                    filler_words_filtered,
                    paragraphs_added,
                    language
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    video_id,
                    channel,
                    title,
                    datetime.now().isoformat(),
                    transcription.get('duration', 0),
                    transcription.get('model', ''),
                    1 if transcription.get('filler_words_filtered', False) else 0,
                    1 if transcription.get('paragraphs_added', False) else 0,
                    transcription.get('language', '')
                ))
            
            conn.commit()
            conn.close()
            
            print(f"Database updated for video ID: {video_id}")
        except Exception as e:
            print(f"Error updating database: {e}")
            # Print more detailed error information
            import traceback
            traceback.print_exc()

# For testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python elevenlabs_transcriber.py <audio_file_path>")
        sys.exit(1)
    
    audio_file_path = sys.argv[1]
    
    transcriber = ElevenLabsTranscriber()
    transcription = transcriber.transcribe(audio_file_path, filter_filler_words=True, add_paragraphs=True)
    
    # Print the transcription
    print(json.dumps(transcription, indent=2)) 