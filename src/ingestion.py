import os
import time
import logging
from pathlib import Path
from typing import List, Dict, Generator, Optional, Any
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)


class BookPairDetector:
    """Detects matching EPUB and audio file sets within an input directory."""

    SUPPORTED_AUDIO_EXTENSIONS = (".mp3", ".m4b", ".wav", ".opus", ".flac")

    def __init__(self, input_dir: Path):
        self.input_dir = Path(input_dir)
        self.input_dir.mkdir(parents=True, exist_ok=True)

    def _find_audio_files(self, search_dir: Path) -> List[Path]:
        """Finds all supported audio files within a directory matching SUPPORTED_AUDIO_EXTENSIONS."""
        audio_files = []
        for ext in self.SUPPORTED_AUDIO_EXTENSIONS:
            audio_files.extend(search_dir.glob(f"*{ext}"))
        return audio_files

    def scan_for_completed_pairs(self) -> List[Dict[str, Any]]:
        """Scans directory for completed book sets (1 EPUB + audio file(s))."""
        pairs = []
        if not self.input_dir.exists():
            return pairs

        epubs = list(self.input_dir.glob("*.epub")) + list(self.input_dir.glob("*/*.epub"))
        for epub in epubs:
            parent_dir = epub.parent
            stem = epub.stem

            # Find matching audio files in same directory or subfolder
            audio_files = self._find_audio_files(parent_dir)
            if not audio_files and (parent_dir / stem).is_dir():
                audio_files = self._find_audio_files(parent_dir / stem)
            
            # Fallback: search any immediate subdirectory for audio files if named match fails
            if not audio_files:
                for sub in parent_dir.iterdir():
                    if sub.is_dir() and not sub.name.startswith("."):
                        sub_audio = self._find_audio_files(sub)
                        if sub_audio:
                            audio_files = sub_audio
                            break

            if audio_files:
                isbn_epub = stem.split("-")[-1] if "-" in stem else "Unknown"
                
                audio_dir_name = audio_files[0].parent.name
                isbn_audio = audio_dir_name.split("-")[-1] if "-" in audio_dir_name else "Unknown"

                pairs.append({
                    "title": stem,
                    "prod_id": stem.lower().replace(" ", "_"),
                    "epub_path": epub,
                    "audio_paths": sorted(audio_files),
                    "isbn_epub": isbn_epub,
                    "isbn_audio": isbn_audio
                })

        return pairs


class IngestionWatcher:
    """Watcher service that polls or monitors input path for ready ingestion jobs."""

    def __init__(self, input_dir: Path, poll_interval: int = 5):
        self.detector = BookPairDetector(input_dir)
        self.poll_interval = poll_interval

    def start_polling(self) -> Generator[Dict[str, Any], None, None]:
        """Continuously yields complete book jobs as they arrive."""
        processed = set()
        logger.info(f"Ingestion watcher started on: {self.detector.input_dir}")

        while True:
            pairs = self.detector.scan_for_completed_pairs()
            for pair in pairs:
                key = str(pair["epub_path"])
                if key not in processed:
                    processed.add(key)
                    logger.info(f"Ingestion detected new book set: '{pair['title']}' ({len(pair['audio_paths'])} audio tracks)")
                    yield pair
            time.sleep(self.poll_interval)
