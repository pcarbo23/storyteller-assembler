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
