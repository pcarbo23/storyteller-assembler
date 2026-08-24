import os
import shutil
import pytest
import subprocess
from pathlib import Path
from src.main import process_single_book

@pytest.mark.parametrize("epub_filename,prod_id", [
    ("A Mouthful of Dust.epub", "100001"),
    ("Agnes Aubert's Mystical Cat Shelter (readaloud).epub", "100002"),
    ("Of Mice and Men (readaloud).epub", "100003"),
])
def test_zedval_compliance_aligned_epubs(tmp_path, epub_filename, prod_id):
    project_root = Path(__file__).parent.parent
    aligned_dir = project_root / "test_material" / "aligned"
    input_epub = aligned_dir / epub_filename
    
    if not input_epub.exists():
        pytest.skip(f"Test EPUB not found: {input_epub}")
        
    base_out_dir = project_root / "test_material" / "aligned_output"
    work_dir = base_out_dir / "work"
    out_dir = base_out_dir / "out"
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    dummy_audio = tmp_path / "dummy.wav"
    with open(dummy_audio, "wb") as f:
        header = b"RIFF\x64\x9c\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x40\x1f\x00\x00\x01\x00\x08\x00data\x40\x9c\x00\x00"
        f.write(header + b"\x80" * 40000)
        
    title = input_epub.stem.replace(" (readaloud)", "")
    
    book_job = {
        "title": title,
        "prod_id": prod_id,
        "epub_path": str(input_epub),
        "audio_paths": [str(dummy_audio)]
    }
    
    class MockTTSGenerator:
        def generate_speech_file(self, text, output_path):
            shutil.copy(dummy_audio, output_path)
            
    # run pipeline
    dtb_dir = process_single_book(
        book_job,
        storyteller=None,
        tts_gen=MockTTSGenerator(),
        output_dir=out_dir,
        work_dir=work_dir,
        enable_storyteller=False
    )
    
    opf_files = list(dtb_dir.glob("*.opf"))
    assert opf_files, f"OPF file not found in {dtb_dir}"
    opf_file = opf_files[0]
    
    # Run ZedVal
    allval_jar = project_root / "test_material" / "AllVal.jar"
    if not allval_jar.exists():
        pytest.skip("AllVal.jar not found")
        
    result = subprocess.run(
        ["java", "-cp", str(allval_jar), "ZedVal", opf_file.name],
        cwd=str(dtb_dir),
        capture_output=True,
        text=True
    )
    
    from scripts.test_post_storyteller import parse_xml_failures
    xml_file = dtb_dir / "ZedVal.xml"
    assert xml_file.exists(), "ZedVal.xml was not generated"
    
    failures = parse_xml_failures(xml_file)
    if failures:
        pytest.fail(f"ZedVal reported compliance failures for {title}:\n" + "\n".join(failures))
