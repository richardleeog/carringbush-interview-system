"""
Translation service using LibreTranslate API.

Provides language detection and translation capabilities with fallback
support when the service is unavailable.
"""

import json
import logging
from typing import Optional, Dict
from urllib import request, parse
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)


class TranslationService:
    """Service for translating text and detecting languages using LibreTranslate."""

    def __init__(self, config=None):
        """
        Initialise the translation service.

        Args:
            config: Configuration object with LIBRETRANSLATE_URL setting.
                   Defaults to "http://localhost:5000" if not provided.
        """
        self.config = config
        self.base_url = getattr(
            config,
            'LIBRETRANSLATE_URL',
            'http://localhost:5000'
        ) if config else 'http://localhost:5000'
        self.base_url = self.base_url.rstrip('/')

    def _make_request(self, endpoint: str, data: Dict) -> Optional[Dict]:
        """
        Make a request to the LibreTranslate API.

        Args:
            endpoint: API endpoint (e.g., 'translate', 'detect')
            data: Dictionary of request parameters

        Returns:
            Parsed JSON response or None if request failed
        """
        url = f'{self.base_url}/api/{endpoint}'
        json_data = json.dumps(data).encode('utf-8')

        try:
            req = request.Request(
                url,
                data=json_data,
                headers={'Content-Type': 'application/json'}
            )
            with request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        except HTTPError as e:
            logger.error(f'LibreTranslate API error ({e.code}): {e.reason}')
            return None
        except URLError as e:
            logger.warning(f'LibreTranslate service unavailable: {e.reason}')
            return None
        except Exception as e:
            logger.error(f'Translation request error: {e}')
            return None

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str
    ) -> str:
        """
        Translate text from source language to target language.

        Args:
            text: Text to translate
            source_lang: ISO 639-1 source language code (e.g., 'en', 'es')
            target_lang: ISO 639-1 target language code

        Returns:
            Translated text, or original text with a note if service unavailable
        """
        if not text or not text.strip():
            return text

        # Normalise language codes to lowercase
        source_lang = source_lang.lower() if source_lang else 'auto'
        target_lang = target_lang.lower() if target_lang else 'en'

        # If source and target are the same, return original text
        if source_lang != 'auto' and source_lang == target_lang:
            return text

        data = {
            'q': text,
            'source': source_lang,
            'target': target_lang
        }

        result = self._make_request('translate', data)

        if result and 'translatedText' in result:
            logger.info(f'Translated text from {source_lang} to {target_lang}')
            return result['translatedText']
        else:
            logger.warning(
                f'Translation service unavailable for {source_lang} -> {target_lang}'
            )
            return f'{text}\n[Translation to {target_lang} unavailable]'

    def detect_language(self, text: str) -> Dict[str, str]:
        """
        Detect the language of given text.

        Args:
            text: Text to detect language for

        Returns:
            Dictionary with keys:
                - language: Detected ISO 639-1 language code (lowercase)
                - confidence: Confidence level (0-1) if available, else 'unknown'
        """
        if not text or not text.strip():
            return {'language': 'unknown', 'confidence': 'unknown'}

        data = {'q': text}
        result = self._make_request('detect', data)

        if result:
            # LibreTranslate returns a list of results
            if isinstance(result, list) and len(result) > 0:
                detected = result[0]
                return {
                    'language': detected.get('language', 'unknown').lower(),
                    'confidence': str(detected.get('confidence', 'unknown'))
                }

        logger.warning('Language detection service unavailable')
        return {'language': 'unknown', 'confidence': 'unknown'}

    def get_supported_languages(self) -> Dict[str, str]:
        """
        Get list of supported languages from the API.

        Returns:
            Dictionary mapping language codes to language names,
            or empty dict if service unavailable
        """
        result = self._make_request('languages', {})

        if result and isinstance(result, list):
            languages = {}
            for lang in result:
                code = lang.get('code', '').lower()
                name = lang.get('name', '')
                if code and name:
                    languages[code] = name
            return languages

        logger.warning('Could not retrieve supported languages list')
        return {}
