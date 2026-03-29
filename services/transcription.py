"""
Transcription service for converting audio to text using OpenAI Whisper.

This module provides transcription capabilities with fallback support
for systems where Whisper is not available.
"""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Service for transcribing audio files to text using Whisper."""

    def __init__(self, config=None):
        """
        Initialise the transcription service.

        Args:
            config: Configuration object with WHISPER_MODEL_SIZE setting.
                   Defaults to "base" if not provided.
        """
        self.config = config
        self.model_size = getattr(config, 'WHISPER_MODEL_SIZE', 'base') if config else 'base'
        self._model = None
        self._whisper_available = self._check_whisper_availability()

    def _check_whisper_availability(self) -> bool:
        """Check if Whisper is installed and available."""
        try:
            import whisper
            return True
        except ImportError:
            logger.warning(
                'Whisper not installed. Transcription will return placeholder data. '
                'Install with: pip install openai-whisper'
            )
            return False

    def _load_model(self):
        """Lazily load the Whisper model on first use."""
        if self._model is None:
            if not self._whisper_available:
                return None

            try:
                import whisper
                logger.info(f'Loading Whisper model: {self.model_size}')
                self._model = whisper.load_model(self.model_size)
            except Exception as e:
                logger.error(f'Failed to load Whisper model: {e}')
                return None

        return self._model

    def transcribe(
        self,
        audio_file_path: str,
        language: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribe an audio file to text.

        Args:
            audio_file_path: Path to the audio file to transcribe.
            language: Optional ISO 639-1 language code (e.g., 'en', 'es', 'fr').
                     If None, Whisper will auto-detect the language.

        Returns:
            Dictionary with keys:
                - text: Transcribed text content
                - language: Detected or specified language code
                - segments: List of segment dictionaries with timing information
                          (empty list if Whisper unavailable)
        """
        # Fallback for when Whisper is not available
        if not self._whisper_available:
            logger.warning(f'Transcription unavailable for {audio_file_path}')
            return {
                'text': '[Transcription unavailable: Whisper not installed]',
                'language': language or 'unknown',
                'segments': []
            }

        try:
            model = self._load_model()
            if model is None:
                return {
                    'text': '[Transcription unavailable: Could not load model]',
                    'language': language or 'unknown',
                    'segments': []
                }

            # Transcribe with optional language specification
            transcription_kwargs = {}
            if language:
                transcription_kwargs['language'] = language

            logger.info(f'Transcribing audio file: {audio_file_path}')
            result = model.transcribe(audio_file_path, **transcription_kwargs)

            # Extract segments with timing information
            segments = []
            for segment in result.get('segments', []):
                segments.append({
                    'id': segment.get('id'),
                    'start': segment.get('start'),
                    'end': segment.get('end'),
                    'text': segment.get('text'),
                    'confidence': segment.get('confidence')
                })

            return {
                'text': result.get('text', ''),
                'language': result.get('language', language or 'unknown'),
                'segments': segments
            }

        except FileNotFoundError:
            logger.error(f'Audio file not found: {audio_file_path}')
            return {
                'text': f'[Error: Audio file not found at {audio_file_path}]',
                'language': language or 'unknown',
                'segments': []
            }
        except Exception as e:
            logger.error(f'Transcription error for {audio_file_path}: {e}')
            return {
                'text': f'[Transcription error: {str(e)}]',
                'language': language or 'unknown',
                'segments': []
            }
