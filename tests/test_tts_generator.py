import pytest
from src.tts_generator import format_spelled_author, render_announcement_text, extract_metadata_from_opf


def test_format_spelled_author():
    raw_author = "Madeleine L'Engle"
    formatted = format_spelled_author(raw_author)
    assert "Madeleine L'Engle" in formatted[0]
    assert "M. A. D. E. L. E. I. N. E." in formatted[1]
    assert "L. '. E. N. G. L. E." in formatted[1]


def test_render_announcement_text():
    metadata = {
        "title": "Of Mice and Men",
        "author_names": "John Steinbeck",
        "production_identifier": "154321",
        "copyright_date_and_holders": "1937",
        "is_new_recording": False,
        "narrator_name": "Test Voice",
        "has_numbered_pages": True,
        "page_count": 107,
        "reading_hours": 3,
        "reading_minutes": 15,
        "navigation_levels": 1,
        "book_items_level_1": "chapters",
        "author_names_and_spelling": "John Steinbeck, J. O. H. N. ... S. T. E. I. N. B. E. C. K.",
        "author_spelling_only": "J. O. H. N. ... S. T. E. I. N. B. E. C. K.",
        "recording_agency_name": "NLS Studio",
        "month_and_year": "July 2026",
        "publisher_info": "Penguin Books"
    }

    opening = render_announcement_text(metadata, "4.1 Opening")
    closing = render_announcement_text(metadata, "4.2 Closing")

    assert "Of Mice and Men" in opening[0]["text"]
    assert "By John Steinbeck" in opening[1]["text"]
    assert "D. B. 154321" in opening[2]["text"]
    # Check conditional modifier "... and the pages."
    nav_line = [line["text"] for line in opening if "markers allowing direct access" in line["text"]][0]
    assert "... and the pages." in nav_line

    assert any("End of Of Mice and Men by John Steinbeck" in line["text"] for line in closing)
    assert any("Published by: Penguin Books" in line["text"] for line in closing)


def test_get_audio_duration_seconds(tmp_path):
    import wave
    from src.tts_generator import get_audio_duration_seconds, calculate_audio_duration

    # Generate a genuine WAV file with 1 second of audio (44100 frames at 44100 Hz, 16-bit mono)
    wav_path = tmp_path / "test_1sec.wav"
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 44100)

    dur = get_audio_duration_seconds(wav_path)
    assert dur is not None
    assert round(dur, 2) == 1.00

    # Test 5-minute rounding
    # 3600 seconds = 1 hour, 0 minutes
    h, m = calculate_audio_duration(3600)
    assert h == 1 and m == 0
    # 3900 seconds = 1 hour, 5 minutes
    h, m = calculate_audio_duration(3900)
    assert h == 1 and m == 5

