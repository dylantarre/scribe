import whisper
import torch
from pathlib import Path
import json

class WhisperTranscriber:
    def __init__(self, model_name="base"):
        """Initialize Whisper model
        model_name options: tiny, base, small, medium, large
        """
        if torch.cuda.is_available():
            self.device = "cuda"
            print(f"Using CUDA device: {torch.cuda.get_device_name(0)}")
        else:
            self.device = "cpu"
            print("Using CPU for transcription")
            
        try:
            self.model = whisper.load_model(model_name).to(self.device)
        except Exception as e:
            print(f"Error loading model {model_name}: {str(e)}")
            raise
        
    def transcribe(self, audio_path, chunk_duration=30):
        """
        Transcribe audio file
        Returns: List of {text, start, end} dictionaries
        """
        try:
            result = self.model.transcribe(
                audio_path,
                task="transcribe",
                language="en",
                verbose=True,
                initial_prompt="This is a music review video.",
                condition_on_previous_text=True,
                temperature=0.0  # Use greedy decoding
            )
            
            return result["segments"]
            
        except Exception as e:
            print(f"Error transcribing {audio_path}: {str(e)}")
            raise
    
    def save_transcript(self, segments, output_path):
        """Save transcript in multiple formats"""
        base_path = Path(output_path).with_suffix('')
        
        # Save raw JSON
        with open(f"{base_path}.json", 'w') as f:
            json.dump(segments, f, indent=2)
            
        # Save TXT format
        with open(f"{base_path}.txt", 'w') as f:
            for seg in segments:
                f.write(f"{seg['text'].strip()}\n")
            
        # Save SRT format
        with open(f"{base_path}.srt", 'w') as f:
            for i, seg in enumerate(segments, 1):
                f.write(f"{i}\n")
                f.write(f"{self._format_timestamp(seg['start'])} --> {self._format_timestamp(seg['end'])}\n")
                f.write(f"{seg['text'].strip()}\n\n")
                
    def _format_timestamp(self, seconds):
        """Convert seconds to SRT timestamp format"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        msecs = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{msecs:03d}" 