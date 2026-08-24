import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tts_generator import TTSGenerator, extract_metadata_from_opf, render_announcement_text
from src.dtb_converter import EPUBOverlayExtractor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")

def run_sandbox():
    print("\n=======================================================")
    print("      TTS PRONUNCIATION & PACING ITERATION SANDBOX     ")
    print("=======================================================\n")

    # Target test material: Of Mice and Men
    epub_path = PROJECT_ROOT / "test_material/aligned/Agnes Aubert's Mystical Cat Shelter (readaloud).epub"
    if not epub_path.exists():
        print(f"Error: Sample EPUB not found at {epub_path}")
        return

    extractor = EPUBOverlayExtractor(epub_path)
    epub_data = extractor.extract()
    author_name = epub_data["metadata"].get("creator") or "Heather Fawcett"
    from src.tts_generator import format_spelled_author
    author_spoken, author_spelled = format_spelled_author(author_name)

    meta = extract_metadata_from_opf("", "1004", [])
    narrator = "Kristin Atherton"

    publisher = epub_data["metadata"].get("publisher") or "Random House Worlds"

    description_blurb = "Agnes Aubert moves to a small coastal town to take over a mysterious cat shelter, only to discover the felines possess magical abilities and hold the key to solving an ancient village mystery."

    meta["narrator_name"] = narrator
    meta.update({
        "title": epub_data["metadata"].get("title", "Agnes Aubert's Mystical Cat Shelter"),
        "author_names": author_name,
        "author_spelling_only": author_spelled,
        "author_names_and_spelling": f"{author_spoken}, {author_spelled}",
        "narrator_name": narrator,
        "publisher_info": publisher,
        "month_and_year": "July 2026",
        "description": description_blurb,
        "has_annotation": True,
        "nls_annotation": description_blurb
    })

    print(f"Loaded Sample Book: '{meta['title']}' by {meta['author_names']}")

    opening_steps = render_announcement_text(meta, "4.1 Opening")
    closing_steps = render_announcement_text(meta, "4.2 Closing")

    print("\n--- Rendered Opening Text Script ---")
    for s in opening_steps:
        print(f"  [{s['step_id']}]: \"{s['text']}\"")

    print("\n--- Rendered Closing Text Script ---")
    for s in closing_steps:
        print(f"  [{s['step_id']}]: \"{s['text']}\"")

    out_dir = PROJECT_ROOT / "data/tts_sandbox"
    out_dir.mkdir(parents=True, exist_ok=True)
    op_path = out_dir / "sandbox_opening.wav"
    cl_path = out_dir / "sandbox_closing.wav"

    print("\nSynthesizing speech via Coqui TTS...")
    gen = TTSGenerator(use_coqui=True)
    gen.generate_speech_file(opening_steps, op_path)
    gen.generate_speech_file(closing_steps, cl_path)

    print("\n=======================================================")
    print("SYNTHESIS COMPLETE! Click to listen & review audio:")
    print(f"  Opening Audio: file://{op_path.resolve()}")
    print(f"  Closing Audio: file://{cl_path.resolve()}")
    print("=======================================================\n")

if __name__ == "__main__":
    run_sandbox()
