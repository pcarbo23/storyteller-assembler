import sys
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
import mutagen


logger = logging.getLogger(__name__)

# NLS 1202:2025 Script Templates JSON definition
SCRIPT_TEMPLATES = [
    {"step_id": "opening_01_title", "section": "4.1 Opening", "template": "{title}", "condition": "always"},
    {"step_id": "opening_02_author", "section": "4.1 Opening", "template": "By {author_names}", "condition": "always"},
    {"step_id": "opening_03_db_id", "section": "4.1 Opening", "template": "D. B. {production_identifier}", "condition": "always"},
    {"step_id": "opening_03b_commercial_adaptation", "section": "4.1 Opening", "template": "{publisher_info} originally produced this unabridged recording for the commercial market. It has been adapted for the NLS talking-book program. Elements from the original recording—including music, sound effects, announcements, or other additional material—may be present. Traditional NLS talking-book announcements have been added. Please note that, although this recording is unabridged, some information—such as photo captions, end notes, bibliographies, appendices, or other supplementary material—may have been omitted by the audio publisher. This recording is used courtesy of {publisher_info}.", "condition": "always"},
    {"step_id": "opening_04_copyright", "section": "4.1 Opening", "template": "copy-right {copyright_date_and_holders}.", "condition": "always"},
    {"step_id": "opening_05_new_recording", "section": "4.1 Opening", "template": "This is a new recording of {book_number}.", "condition": "is_new_recording"},
    {"step_id": "opening_06_narrator", "section": "4.1 Opening", "template": "Red by {narrator_name}.", "condition": "always"},
    {"step_id": "opening_07_pages", "section": "4.1 Opening", "template": "This book contains {page_count} pages.", "condition": "has_numbered_pages"},
    {"step_id": "opening_08_reading_time", "section": "4.1 Opening", "template": "Approximate reading time: {reading_hours} hours, {reading_minutes} minutes.", "condition": "always"},
    {
        "step_id": "opening_09_navigation_level_1",
        "section": "4.1 Opening",
        "template": "This book contains markers allowing direct access to the {book_items_level_1}.",
        "condition": "navigation_levels == 1",
        "modifier": "If has_numbered_pages is true, append '... and the pages.' to this string."
    },
    {
        "step_id": "opening_09_navigation_multi_level",
        "section": "4.1 Opening",
        "template": "This book contains markers allowing direct access to: at level 1 the {book_items_level_1}, at level 2 the {book_items_level_2}, ... and at level {lowest_hierarchical_level} the {book_items_lowest_level}.",
        "condition": "navigation_levels > 1",
        "modifier": "If has_numbered_pages is true, append '... and the pages.' to this string."
    },
    {"step_id": "opening_10a_annotation_heading", "section": "4.1 Opening", "template": "Library of Congress annotation.", "condition": "has_annotation"},
    {"step_id": "opening_10b_annotation_body", "section": "4.1 Opening", "template": "{nls_annotation}", "condition": "has_annotation"},

    {"step_id": "opening_11_book_jacket", "section": "4.1 Opening", "template": "From the book jacket: {book_jacket_info}", "condition": "has_book_jacket"},
    {"step_id": "opening_12_about_author", "section": "4.1 Opening", "template": "About the author. {about_author_info}", "condition": "has_about_author"},
    {"step_id": "opening_13_other_books", "section": "4.1 Opening", "template": "Other books by {author_names}. {other_books_info}", "condition": "has_other_books"},
    {"step_id": "opening_14_introductory_items", "section": "4.1 Opening", "template": "{introductory_items_and_toc}", "condition": "has_introductory_items"},
    {"step_id": "closing_01_end_of_title", "section": "4.2 Closing", "template": "End of {title} by {author_names}.", "condition": "always"},
    {"step_id": "closing_01b_spelling", "section": "4.2 Closing", "template": "{author_spelling_only}", "condition": "always"},
    {"step_id": "closing_02_recording_info", "section": "4.2 Closing", "template": "Red by {narrator_name} in the studios of {recording_agency_name}, for the Library of Congress, {month_and_year}.", "condition": "always"},
    {"step_id": "closing_03_publisher_info", "section": "4.2 Closing", "template": "Published by: {publisher_info}. Further reproduction or distribution in other than an accessible format is prohibited.", "condition": "always"},
    {"step_id": "closing_04_defective_book", "section": "4.2 Closing", "template": "If you found this book to be defective, please contact your cooperating network library.", "condition": "always"}
]


def format_db_id(prod_id: str) -> str:
    """Format DB production identifier so digits are read individually, e.g., '54321' -> '5, 4, 3, 2, 1'."""
    clean_digits = [char for char in str(prod_id) if char.isdigit()]
    return ", ".join(clean_digits)


def format_copyright_year(date_str: str) -> str:
    """Extract 4-digit year from ISO date strings (e.g. '2026-02-17T00:00:00.000Z' -> '2026')."""
    if not date_str:
        return "2026"
    import re
    match = re.search(r"\b(19\d\d|20\d\d)\b", date_str)
    if match:
        return match.group(1)
    return date_str.split("-")[0].strip()


def format_spelled_author(author_name: str) -> tuple[str, str]:
    """
    Format author name for spoken and spelled-out presentation per NLS 1202:2025.
    Separates spelled letters with periods and spaces for clear, deliberate, slow recitation.
    Returns (spoken_name, spelled_only_string).
    """
    if not author_name:
        return "", ""
    words = author_name.split()
    spelled_words = []
    for word in words:
        spelled = ". ".join([char.upper() for char in word]) + "."
        spelled_words.append(spelled)
    spelled_full = " ... ".join(spelled_words)
    return author_name, spelled_full


def calculate_audio_duration(audio_files_or_seconds: Any) -> tuple[int, int]:
    """Calculate total reading time in hours and minutes (rounded to nearest 5 mins)."""
    if isinstance(audio_files_or_seconds, (int, float)):
        total_seconds = float(audio_files_or_seconds)
    else:
        total_seconds = 0.0
        for audio_file in audio_files_or_seconds:
            try:
                audio = mutagen.File(str(audio_file))
                if audio and audio.info:
                    total_seconds += audio.info.length
            except Exception as e:
                logger.warning(f"Could not read audio length for {audio_file}: {e}")

    hours = int(total_seconds // 3600)
    minutes = int(round((total_seconds % 3600) / 60.0 / 5.0) * 5)
    if minutes == 60:
        hours += 1
        minutes = 0
    return hours, minutes


def extract_metadata_from_opf(opf_content: str, prod_id: str, audio_files: List[Path]) -> Dict[str, Any]:
    """Extract metadata dictionary from OPF XML content."""
    soup = BeautifulSoup(opf_content, "xml")

    title_elem = soup.find("dc:title") or soup.find("title")
    title = title_elem.text.strip() if title_elem else "Unknown Title"

    author_elem = soup.find("dc:creator") or soup.find("creator")
    author = author_elem.text.strip() if author_elem else "Unknown Author"

    pub_elem = soup.find("dc:publisher") or soup.find("publisher")
    publisher = pub_elem.text.strip() if pub_elem else "National Library Service for the Blind and Physically Handicapped"

    date_elem = soup.find("dc:date") or soup.find("date")
    raw_date = date_elem.text.strip() if date_elem else "2026"
    copyright_date = format_copyright_year(raw_date)

    hours, minutes = calculate_audio_duration(audio_files)

    clean_id = prod_id.lower().replace("db", "")

    author_spoken, author_spelled = format_spelled_author(author)

    spaced_db_id = format_db_id(clean_id)

    metadata = {
        "title": title,
        "author_names": author,
        "production_identifier": spaced_db_id,
        "copyright_date_and_holders": copyright_date,
        "is_new_recording": False,
        "book_number": spaced_db_id,
        "narrator_name": "Narrator(s) Unknown",
        "has_numbered_pages": False,
        "page_count": 0,
        "reading_hours": hours,
        "reading_minutes": minutes,
        "navigation_levels": 1,
        "book_items_level_1": "chapters",
        "book_items_level_2": "sections",
        "lowest_hierarchical_level": 1,
        "book_items_lowest_level": "chapters",
        "has_annotation": False,
        "nls_annotation": "",
        "has_book_jacket": False,
        "book_jacket_info": "",
        "has_about_author": False,
        "about_author_info": "",
        "has_other_books": False,
        "other_books_info": "",
        "has_introductory_items": False,
        "introductory_items_and_toc": "",
        "author_names_and_spelling": f"{author_spoken}, {author_spelled}",
        "author_spelling_only": author_spelled,
        "recording_agency_name": "NLS Automated Pipeline",
        "month_and_year": "July 2026",
        "publisher_info": publisher
    }
    return metadata


def render_announcement_text(metadata: Dict[str, Any], section_prefix: str) -> List[Dict[str, str]]:
    """Render ordered list of text step objects (with step_id and text) for opening or closing announcements."""
    rendered_steps = []

    for item in SCRIPT_TEMPLATES:
        if not item["section"].startswith(section_prefix):
            continue

        cond = item["condition"]
        should_include = False

        if cond == "always":
            should_include = True
        elif cond == "is_new_recording":
            should_include = metadata.get("is_new_recording", False)
        elif cond == "has_numbered_pages":
            should_include = metadata.get("has_numbered_pages", False)
        elif cond == "navigation_levels == 1":
            should_include = metadata.get("navigation_levels", 1) == 1
        elif cond == "navigation_levels > 1":
            should_include = metadata.get("navigation_levels", 1) > 1
        elif cond.startswith("has_"):
            should_include = metadata.get(cond, False)

        if should_include:
            text = item["template"].format(**metadata)
            if "modifier" in item and metadata.get("has_numbered_pages"):
                text += " ... and the pages."
            rendered_steps.append({"step_id": item["step_id"], "text": text})

    return rendered_steps



class TTSGenerator:
    """Generates WAV announcement audio files using Coqui TTS engine."""

    def __init__(self, model_name: str = "tts_models/en/ljspeech/vits", use_coqui: bool = True):
        self.use_coqui = use_coqui
        self.tts = None
        if not use_coqui:
            logger.info("Initializing TTSGenerator in MOCK mode (use_coqui=False)")
            return
        try:
            from TTS.api import TTS
            self.tts = TTS(model_name=model_name)
            logger.info(f"Initialized Coqui TTS engine with model {model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Coqui TTS: {e}")
            raise RuntimeError(f"Coqui TTS initialization failed: {e}")

    def generate_speech_file(self, text_steps: List[Any], output_path: Path, force_direct: bool = False) -> Dict[str, Any]:
        """Synthesize text steps into a single audio file using Coqui TTS and return step timing dictionary."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # To prevent OpenMP / PyTorch multiprocessing deadlocks on macOS when sub-processes (like docker aligner) 
        # have been spawned earlier in the watcher loop, run Coqui TTS in an isolated python process.
        if self.use_coqui and not force_direct:
            serialized_steps = json.dumps(text_steps)
            helper_script = Path(__file__).resolve().parent.parent / "scripts" / "generate_tts_audio.py"
            timing_file = output_path.parent / f"{output_path.name}.timing.json"
            if timing_file.exists():
                timing_file.unlink(missing_ok=True)

            cmd = [sys.executable, str(helper_script), str(output_path), serialized_steps]
            
            logger.info(f"Delegating TTS generation to isolated subprocess for: {output_path.name}")
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                err_msg = res.stderr.strip() or res.stdout.strip() or f"Process exited with code {res.returncode}"
                logger.error(f"TTS subprocess execution failed for {output_path.name}: {err_msg}")
                raise RuntimeError(f"TTS audio synthesis failed for '{output_path.name}': {err_msg}")

            timing_info = None
            if timing_file.exists():
                try:
                    timing_info = json.loads(timing_file.read_text(encoding="utf-8"))
                    timing_file.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Could not read timing sidecar file: {e}")

            if not timing_info and "__TIMING_START__" in res.stdout:
                try:
                    raw_json = res.stdout.split("__TIMING_START__")[1].split("__TIMING_END__")[0].strip()
                    timing_info = json.loads(raw_json)
                except Exception as e:
                    logger.warning(f"Could not extract timing from sentinel: {e}")

            if not timing_info:
                for line in reversed(res.stdout.strip().splitlines()):
                    clean_line = line.strip()
                    if clean_line.startswith("{") and clean_line.endswith("}"):
                        try:
                            timing_info = json.loads(clean_line)
                            break
                        except Exception:
                            pass

            if not timing_info:
                logger.error(f"Failed to parse timing JSON from TTS subprocess for {output_path.name}. Subprocess output:\n{res.stdout}")
                raise RuntimeError(f"TTS output parsing failed for '{output_path.name}': No valid timing JSON found in subprocess output. Subprocess output:\n{res.stdout}")

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError(f"TTS audio synthesis failed: Output file '{output_path.name}' was not created or is empty.")

            return timing_info

        # Extract text strings if passed dicts or strings
        step_items = []
        for step in text_steps:
            if isinstance(step, dict):
                step_items.append(step)
            else:
                step_items.append({"step_id": "step", "text": str(step)})

        text_strings = [s["text"] for s in step_items]
        full_text = " . ".join(text_strings)

        timing_info = {}

        if not self.use_coqui:
            # Mock mode: write a dummy WAV file and return default timing
            header = b"RIFF\x64\x9c\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x40\x1f\x00\x00\x01\x00\x08\x00data\x40\x9c\x00\x00"
            output_path.write_bytes(header + b"\x80" * 40000)
            return {"_total_duration": 25.0}

        if not self.tts:
            raise RuntimeError("Coqui TTS engine is not initialized.")

        # Generate audio using Coqui TTS
        temp_raw_wav = output_path.parent / f"coqui_raw_{output_path.name}"
        speaker = self.tts.speakers[1] if (hasattr(self.tts, "speakers") and self.tts.speakers and len(self.tts.speakers) > 1) else None
        if speaker:
            self.tts.tts_to_file(text=full_text, speaker=speaker, file_path=str(temp_raw_wav))
        else:
            self.tts.tts_to_file(text=full_text, file_path=str(temp_raw_wav))

        # Ensure output is converted to 44.1kHz 16-bit PCM WAV for NLS compliance
        cmd_ffmpeg = ["ffmpeg", "-y", "-i", str(temp_raw_wav), "-ar", "44100", "-acodec", "pcm_s16le", str(output_path)]
        res_ffmpeg = subprocess.run(cmd_ffmpeg, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        temp_raw_wav.unlink(missing_ok=True)

        if res_ffmpeg.returncode != 0:
            raise RuntimeError(f"ffmpeg conversion of Coqui TTS audio failed: {res_ffmpeg.stderr.decode()}")

        # Total duration of Coqui audio
        total_dur = 5.0
        try:
            audio = mutagen.File(str(output_path))
            if audio and audio.info:
                total_dur = audio.info.length
        except Exception:
            pass

        # Proportional step timing calculation based on generated Coqui audio
        total_chars = max(1, len(full_text))
        curr_time = 0.0
        for item in step_items:
            step_len = len(item["text"])
            step_dur = (step_len / total_chars) * total_dur
            start_t = curr_time
            end_t = curr_time + step_dur
            timing_info[item["step_id"]] = {"start": start_t, "end": end_t, "duration": step_dur}
            curr_time = end_t
        timing_info["_total_duration"] = total_dur

        logger.info(f"Generated Coqui TTS announcement audio file ({output_path.name}, total={timing_info.get('_total_duration', 0.0):.2f}s)")
        return timing_info



