import os
from pathlib import Path
from src.main import process_single_book
from src.tts_generator import TTSGenerator


def test_micro_integration_pipeline(tmp_path):
    # Find Of Mice and Men from test_material
    test_material_dir = Path(__file__).parent.parent / "test_material" / "Of Mice and Men"
    epub_path = test_material_dir / "Of Mice and Men.epub"
    audio_dir = test_material_dir / "Of Mice and Men"
    audio_paths = sorted(list(audio_dir.glob("*.mp3")))[:2]  # Take first 2 tracks for fast micro test

    assert epub_path.exists()
    assert len(audio_paths) > 0

    book_job = {
        "title": "Of Mice and Men",
        "prod_id": "154321",
        "epub_path": epub_path,
        "audio_paths": audio_paths
    }

    output_dir = tmp_path / "output"
    work_dir = tmp_path / "work"
    tts_gen = TTSGenerator(use_coqui=False)

    dtb_destination = process_single_book(
        book_job=book_job,
        storyteller=None,
        tts_gen=tts_gen,
        output_dir=output_dir,
        work_dir=work_dir,
        enable_storyteller=False
    )

    assert dtb_destination.exists()
    assert dtb_destination.is_dir()
    assert dtb_destination.name == "db154321.dtb"

    dtb_files = [f.name for f in dtb_destination.iterdir()]
    assert "db154321.opf" in dtb_files
    assert "db154321.ncx" in dtb_files
    assert "db154321-0001.smil" in dtb_files
    assert any(f.endswith(".wav") for f in dtb_files)
