"""
File management service for handling student profiles and session files.

Manages the folder structure and file operations for storing student data,
interview transcripts, generated documents, and audio recordings.

Folder structure:
    Students/
    ├── SURNAME_FirstName_ID/
    │   ├── student_profile.json
    │   ├── YYYY-MM-DD_Session_01/
    │   │   ├── transcript.txt
    │   │   ├── transcript_LANGUAGE.txt
    │   │   ├── audio.wav
    │   │   ├── CV_English.docx
    │   │   ├── CoverLetter_English.docx
    │   │   └── MeetingSummary_Student_English.docx
    │   └── YYYY-MM-DD_Session_02/
    │       └── ...
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class FileManager:
    """Manages student files and folder structure."""

    def __init__(self, config=None):
        """
        Initialise the file manager.

        Args:
            config: Configuration object with STUDENT_FILES_DIR setting.
                   Defaults to '/tmp/carringbush/students' if not provided.
        """
        self.config = config
        if isinstance(config, dict):
            self.base_dir = config.get('STUDENT_FILES_DIR', '/tmp/carringbush/students')
        else:
            self.base_dir = getattr(config, 'STUDENT_FILES_DIR', '/tmp/carringbush/students') if config else '/tmp/carringbush/students'

        # Create base directory if it doesn't exist
        Path(self.base_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f'File manager initialised with base directory: {self.base_dir}')

    def _sanitise_path(self, path_component: str) -> str:
        """
        Sanitise a path component to prevent directory traversal attacks.

        Args:
            path_component: Component of the path to sanitise

        Returns:
            Sanitised path component
        """
        # Remove any path separators and suspicious characters
        sanitised = re.sub(r'[/\\.\0]', '_', path_component)
        # Remove leading/trailing spaces and dots
        sanitised = sanitised.strip(' .')
        # Limit length
        sanitised = sanitised[:100]
        return sanitised

    def _get_student_folder_name(self, student: Dict[str, Any]) -> str:
        """
        Generate a safe student folder name.

        Args:
            student: Student dictionary with 'surname', 'first_name', 'id'

        Returns:
            Safe folder name in format: SURNAME_FirstName_ID
        """
        surname = self._sanitise_path(student.get('surname', 'Unknown'))
        first_name = self._sanitise_path(student.get('first_name', 'Unknown'))
        student_id = self._sanitise_path(str(student.get('id', 'unknown')))

        return f'{surname}_{first_name}_{student_id}'

    def _get_student_dir(self, student: Dict[str, Any]) -> str:
        """Get the full path to a student's folder."""
        folder_name = self._get_student_folder_name(student)
        return os.path.join(self.base_dir, folder_name)

    def _get_session_folder_name(self, session: Dict[str, Any]) -> str:
        """
        Generate a session folder name.

        Args:
            session: Session dictionary with 'date' and 'session_number'

        Returns:
            Folder name in format: YYYY-MM-DD_Session_NN
        """
        date = session.get('date', datetime.now().strftime('%Y-%m-%d'))
        session_num = session.get('session_number', 1)

        # Ensure date format is correct
        try:
            date_obj = datetime.fromisoformat(date)
            date = date_obj.strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            date = datetime.now().strftime('%Y-%m-%d')

        return f'{date}_Session_{session_num:02d}'

    def create_student_folder(self, student: Dict[str, Any]) -> str:
        """
        Create a student folder and initialise profile.

        Args:
            student: Student dictionary with keys:
                    - surname: Student surname
                    - first_name: Student first name
                    - id: Unique student ID
                    - email: Student email
                    - phone: Student phone number
                    - location: Student location

        Returns:
            Path to the created student folder
        """
        student_dir = self._get_student_dir(student)

        # Create directory
        Path(student_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f'Created student folder: {student_dir}')

        # Create student profile file
        profile_path = os.path.join(student_dir, 'student_profile.json')
        if not os.path.exists(profile_path):
            profile = {
                'id': student.get('id'),
                'surname': student.get('surname'),
                'first_name': student.get('first_name'),
                'email': student.get('email'),
                'phone': student.get('phone'),
                'location': student.get('location'),
                'created_at': datetime.now().isoformat(),
                'sessions': []
            }

            try:
                with open(profile_path, 'w', encoding='utf-8') as f:
                    json.dump(profile, f, indent=2, ensure_ascii=False)
                logger.info(f'Created student profile: {profile_path}')
            except Exception as e:
                logger.error(f'Failed to create student profile: {e}')

        return student_dir

    def create_session_folder(
        self,
        student: Dict[str, Any],
        session: Dict[str, Any]
    ) -> str:
        """
        Create a session folder for a student.

        Args:
            student: Student dictionary
            session: Session dictionary with 'date' and 'session_number'

        Returns:
            Path to the created session folder
        """
        student_dir = self._get_student_dir(student)
        session_folder_name = self._get_session_folder_name(session)
        session_dir = os.path.join(student_dir, session_folder_name)

        # Create directory
        Path(session_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f'Created session folder: {session_dir}')

        # Update student profile with session info
        profile_path = os.path.join(student_dir, 'student_profile.json')
        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile = json.load(f)

            if session not in profile['sessions']:
                profile['sessions'].append({
                    'date': session.get('date'),
                    'session_number': session.get('session_number'),
                    'folder': session_folder_name,
                    'created_at': datetime.now().isoformat()
                })

                with open(profile_path, 'w', encoding='utf-8') as f:
                    json.dump(profile, f, indent=2, ensure_ascii=False)
                logger.info(f'Updated student profile with new session')
        except Exception as e:
            logger.warning(f'Could not update student profile: {e}')

        return session_dir

    def save_transcript(
        self,
        student: Dict[str, Any],
        session: Dict[str, Any],
        transcript_text: str,
        language: str = 'en'
    ) -> Optional[str]:
        """
        Save interview transcript to file.

        Args:
            student: Student dictionary
            session: Session dictionary
            transcript_text: Transcribed text content
            language: ISO 639-1 language code (e.g., 'en', 'es')

        Returns:
            Path to saved transcript file, or None if failed
        """
        session_dir = self._get_session_folder_name(session)
        student_dir = self._get_student_dir(student)
        session_path = os.path.join(student_dir, session_dir)

        try:
            # Save language-specific transcript
            filename = f'transcript_{language.lower()}.txt'
            filepath = os.path.join(session_path, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(transcript_text)

            logger.info(f'Saved transcript: {filepath}')

            # Also save as generic transcript.txt if English
            if language.lower() in ['en', 'eng']:
                generic_path = os.path.join(session_path, 'transcript.txt')
                with open(generic_path, 'w', encoding='utf-8') as f:
                    f.write(transcript_text)
                logger.info(f'Saved generic transcript: {generic_path}')

            return filepath

        except Exception as e:
            logger.error(f'Failed to save transcript: {e}')
            return None

    def save_audio(
        self,
        student: Dict[str, Any],
        session: Dict[str, Any],
        audio_data: bytes,
        format: str = 'wav'
    ) -> Optional[str]:
        """
        Save audio file to session folder.

        Args:
            student: Student dictionary
            session: Session dictionary
            audio_data: Raw audio bytes
            format: Audio format (e.g., 'wav', 'mp3', 'webm')

        Returns:
            Path to saved audio file, or None if failed
        """
        session_dir = self._get_session_folder_name(session)
        student_dir = self._get_student_dir(student)
        session_path = os.path.join(student_dir, session_dir)

        try:
            filename = f'audio.{format.lower()}'
            filepath = os.path.join(session_path, filename)

            with open(filepath, 'wb') as f:
                f.write(audio_data)

            logger.info(f'Saved audio file: {filepath}')
            return filepath

        except Exception as e:
            logger.error(f'Failed to save audio file: {e}')
            return None

    def get_student_files(self, student: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get information about all files for a student.

        Args:
            student: Student dictionary

        Returns:
            Dictionary with student info and list of sessions with their files
        """
        student_dir = self._get_student_dir(student)

        if not os.path.exists(student_dir):
            logger.warning(f'Student folder not found: {student_dir}')
            return {'error': 'Student folder not found'}

        profile_path = os.path.join(student_dir, 'student_profile.json')
        student_info = {}

        # Load profile if available
        if os.path.exists(profile_path):
            try:
                with open(profile_path, 'r', encoding='utf-8') as f:
                    student_info = json.load(f)
            except Exception as e:
                logger.warning(f'Could not load student profile: {e}')

        # List all sessions
        sessions = []
        try:
            for entry in os.listdir(student_dir):
                entry_path = os.path.join(student_dir, entry)
                if os.path.isdir(entry_path) and '_Session_' in entry:
                    session_files = self._list_session_files(entry_path)
                    sessions.append({
                        'name': entry,
                        'files': session_files
                    })
        except Exception as e:
            logger.error(f'Failed to list session directories: {e}')

        return {
            'student_info': student_info,
            'sessions': sessions
        }

    def get_session_files(
        self,
        student: Dict[str, Any],
        session: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        Get all files in a specific session.

        Args:
            student: Student dictionary
            session: Session dictionary

        Returns:
            Dictionary mapping filenames to absolute paths
        """
        session_dir = self._get_session_folder_name(session)
        student_dir = self._get_student_dir(student)
        session_path = os.path.join(student_dir, session_dir)

        files = {}

        if not os.path.exists(session_path):
            logger.warning(f'Session folder not found: {session_path}')
            return files

        try:
            for filename in os.listdir(session_path):
                filepath = os.path.join(session_path, filename)
                if os.path.isfile(filepath):
                    files[filename] = filepath
        except Exception as e:
            logger.error(f'Failed to list session files: {e}')

        return files

    def _list_session_files(self, session_path: str) -> List[Dict[str, str]]:
        """
        List all files in a session directory.

        Args:
            session_path: Path to session directory

        Returns:
            List of dictionaries with file information
        """
        files = []

        try:
            for filename in os.listdir(session_path):
                filepath = os.path.join(session_path, filename)
                if os.path.isfile(filepath):
                    file_stat = os.stat(filepath)
                    files.append({
                        'name': filename,
                        'path': filepath,
                        'size': file_stat.st_size,
                        'modified': datetime.fromtimestamp(
                            file_stat.st_mtime
                        ).isoformat()
                    })
        except Exception as e:
            logger.error(f'Failed to list files in {session_path}: {e}')

        return files

    def delete_session_file(
        self,
        student: Dict[str, Any],
        session: Dict[str, Any],
        filename: str
    ) -> bool:
        """
        Delete a specific file from a session.

        Args:
            student: Student dictionary
            session: Session dictionary
            filename: Name of file to delete

        Returns:
            True if successful, False otherwise
        """
        session_files = self.get_session_files(student, session)

        if filename not in session_files:
            logger.warning(f'File not found: {filename}')
            return False

        filepath = session_files[filename]

        try:
            os.remove(filepath)
            logger.info(f'Deleted file: {filepath}')
            return True
        except Exception as e:
            logger.error(f'Failed to delete file: {e}')
            return False

    def get_student_profile(self, student: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Load student profile from JSON file.

        Args:
            student: Student dictionary with 'id', 'surname', 'first_name'

        Returns:
            Dictionary with student profile data, or None if not found
        """
        student_dir = self._get_student_dir(student)
        profile_path = os.path.join(student_dir, 'student_profile.json')

        if not os.path.exists(profile_path):
            logger.warning(f'Student profile not found: {profile_path}')
            return None

        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile = json.load(f)
            return profile
        except Exception as e:
            logger.error(f'Failed to load student profile: {e}')
            return None

    def update_student_profile(
        self,
        student: Dict[str, Any],
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update student profile with new information.

        Args:
            student: Student dictionary
            updates: Dictionary of fields to update

        Returns:
            True if successful, False otherwise
        """
        student_dir = self._get_student_dir(student)
        profile_path = os.path.join(student_dir, 'student_profile.json')

        if not os.path.exists(profile_path):
            logger.warning(f'Student profile not found: {profile_path}')
            return False

        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile = json.load(f)

            # Update allowed fields
            allowed_fields = ['email', 'phone', 'location', 'notes']
            for field in allowed_fields:
                if field in updates:
                    profile[field] = updates[field]

            profile['updated_at'] = datetime.now().isoformat()

            with open(profile_path, 'w', encoding='utf-8') as f:
                json.dump(profile, f, indent=2, ensure_ascii=False)

            logger.info(f'Updated student profile: {profile_path}')
            return True

        except Exception as e:
            logger.error(f'Failed to update student profile: {e}')
            return False
