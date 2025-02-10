from youtube_downloader import download_and_extract_audio
from transcriber import WhisperTranscriber
import os
from tqdm import tqdm

def transcribe_youtube(url):
    print("Downloading audio...")
    audio_path = download_and_extract_audio(url)
    
    print("Transcribing...")
    transcriber = WhisperTranscriber(model_name="base")
    
    with tqdm(desc="Transcribing", unit=" segments") as pbar:
        segments = transcriber.transcribe(audio_path)
        pbar.update(len(segments))
    
    print("Saving transcripts...")
    output_base = os.path.splitext(audio_path)[0]
    transcriber.save_transcript(segments, output_base)
    
    return segments

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python main.py <youtube_url>")
        sys.exit(1)
        
    url = sys.argv[1]
    segments = transcribe_youtube(url)
    print("Done! Check the data directory for output files.") 