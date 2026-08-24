import os
from pathlib import Path
from src.dtb_converter import DTBConverter


def test_dtb_converter_file_naming(tmp_path):
    converter = DTBConverter(prod_id="db154321", work_dir=tmp_path)
    assert converter.prod_id_full == "db154321"
    assert converter.prod_id_base == "154321"
    assert converter.uid == "us-nls-db154321"


def test_z39_xml_generation(tmp_path):
    converter = DTBConverter(prod_id="db154321", work_dir=tmp_path)
    metadata = {
        "title": "Test Book",
        "author_names": "Test Author",
        "reading_hours": 1,
        "reading_minutes": 30,
        "narrator_name": "Test Narrator",
        "copyright_date_and_holders": "2026",
        "navigation_levels": 1,
        "author_names_and_spelling": "Test Author",
        "author_spelling_only": "T. E. S. T.",
        "recording_agency_name": "Test Agency"
    }

    epub_data = {
        "epub_path": tmp_path / "dummy.epub",
        "metadata": {
            "title": "Test Book",
            "creator": "Test Author"
        },
        "nav_tree": [
            {
                "id": "nav-1",
                "label": "Chapter 1",
                "src": "chapter1.xhtml",
                "audio": "chapter1.wav",
                "audio_src": "chapter1.wav",
                "children": []
            }
        ],
        "smil_segments": [
            {
                "smil_id": "smil-1",
                "src": "chapter1.smil",
                "audio": "chapter1.wav",
                "audio_zip_path": "chapter1.wav",
                "text_id": "txt-1",
                "duration": 60.0,
                "clip_begin": 0.0,
                "clip_end": 60.0,
                "text_src": "chapter1.xhtml",
                "audio_order": ["chapter1.wav"]
            }
        ],
        "audio_order": ["chapter1.wav"]
    }

    dummy_wav = tmp_path / "dummy.wav"
    wav_content = b"RIFF\x64\x9c\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x40\x1f\x00\x00\x01\x00\x08\x00data\x40\x9c\x00\x00" + b"\x80" * 1000
    dummy_wav.write_bytes(wav_content)

    import zipfile
    with zipfile.ZipFile(tmp_path / "dummy.epub", "w") as z:
        z.writestr("chapter1.wav", wav_content)

    # Put chapter1.wav in work_dir so converter can process/copy it
    chapter_wav = tmp_path / "chapter1.wav"
    import shutil
    shutil.copy(dummy_wav, chapter_wav)

    dtb_dir = converter.generate_z39_package(
        epub_data=epub_data,
        metadata_nls=metadata,
        opening_wav=dummy_wav,
        closing_wav=dummy_wav
    )

    opf_file = tmp_path / "db154321.opf"
    assert opf_file.exists()

    opf_content = opf_file.read_text()
    assert "ANSI/NISO Z39.86-2002" in opf_content
    assert "us-nls-db154321" in opf_content
    assert "National Library Service" in opf_content

