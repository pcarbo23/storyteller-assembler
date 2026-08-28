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

    ncx_file = tmp_path / "db154321.ncx"
    assert ncx_file.exists()
    ncx_content = ncx_file.read_text()
    assert '<meta name="dtb:depth" content="1"/>' in ncx_content


def test_dtb_depth_calculation_and_pruning(tmp_path):
    converter = DTBConverter(prod_id="db100039", work_dir=tmp_path)

    # Simulated tree: 1 valid chapter, 1 un-narrated preview with 2 nested levels
    nav_tree = [
        {"id": "c1", "title": "Chapter 1", "src": "c1.xhtml", "children": []},
        {
            "id": "p1",
            "title": "Preview",
            "src": "preview.xhtml",
            "children": [
                {
                    "id": "p1_1",
                    "title": "Preview Part 1",
                    "src": "p1_1.xhtml",
                    "children": [
                        {"id": "p1_1_a", "title": "Section A", "src": "p1_1_a.xhtml", "children": []}
                    ]
                }
            ]
        }
    ]

    # Only c1.xhtml has audio segments
    smil_segments = [
        {"text_src": "c1.xhtml", "audio_zip_path": "audio1.wav", "clip_begin": 0.0, "clip_end": 10.0}
    ]

    pruned = converter.prune_nav_tree(nav_tree, smil_segments)
    assert len(pruned) == 1
    assert pruned[0]["id"] == "c1"
    assert converter.calculate_max_depth(pruned) == 1

    # Test rendered NCX string depth calculation
    flat_ncx = """<?xml version="1.0" encoding="UTF-8"?>
    <ncx version="1.1.0">
      <head><meta name="dtb:depth" content="3"/></head>
      <navMap>
        <navPoint id="p1"><content src="s.smil#p1"/></navPoint>
        <navPoint id="p2"><content src="s.smil#p2"/></navPoint>
      </navMap>
    </ncx>"""
    assert converter.calculate_rendered_ncx_depth(flat_ncx) == 1

    nested_ncx = """<?xml version="1.0" encoding="UTF-8"?>
    <ncx version="1.1.0">
      <head><meta name="dtb:depth" content="1"/></head>
      <navMap>
        <navPoint id="p1">
          <content src="s.smil#p1"/>
          <navPoint id="p1_1">
            <content src="s.smil#p1_1"/>
            <navPoint id="p1_1_1"><content src="s.smil#p1_1_1"/></navPoint>
          </navPoint>
        </navPoint>
      </navMap>
    </ncx>"""
    assert converter.calculate_rendered_ncx_depth(nested_ncx) == 3


def test_boundary_inverted_clips_sanitization(tmp_path):
    converter = DTBConverter(prod_id="db100042", work_dir=tmp_path)

    # Simulated smil segments with inverted clip on track 1 followed by normal on track 2
    smil_segments = [
        {"par_id": "c9-s1", "text_src": "ch9.xhtml#s1", "audio_zip_path": "track1.wav", "clip_begin": 0.0, "clip_end": 10.0},
        {"par_id": "c10-s0", "text_src": "ch10.xhtml#s0", "audio_zip_path": "track1.wav", "clip_begin": 885.56, "clip_end": 883.152},  # Inverted!
        {"par_id": "c10-s1", "text_src": "ch10.xhtml#s1", "audio_zip_path": "track2.wav", "clip_begin": 0.0, "clip_end": 7.4}
    ]

    audio_map = {"track1.wav": "db100042-0012.wav", "track2.wav": "db100042-0013.wav"}
    par_map = converter.build_par_by_text_src(smil_segments, audio_map, "opening.wav")

    # ch10.xhtml should map to track 2 at 0.0s - 7.4s, NOT track 1
    assert "ch10.xhtml" in par_map
    assert par_map["ch10.xhtml"]["audio_src"] == "db100042-0013.wav"
    assert par_map["ch10.xhtml"]["clip_begin"] == "0:00:00.000"
    assert par_map["ch10.xhtml"]["clip_end"] == "0:00:07.400"



