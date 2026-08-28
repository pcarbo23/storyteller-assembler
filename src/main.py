import os
import sys
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion import BookPairDetector
from src.tts_generator import TTSGenerator, extract_metadata_from_opf, render_announcement_text, format_spelled_author, calculate_audio_duration, format_copyright_year
from src.dtb_converter import DTBConverter, EPUBOverlayExtractor, calculate_file_md5
from src.epub_nls_editor import NLSEPUBEditor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pipeline_main")


def process_aligned_epub(
    epub_path: Path,
    prod_id: str,
    tts_gen: TTSGenerator,
    output_dir: Path,
    work_dir: Path,
    raw_audio_dir: Optional[Path] = None
) -> Path:
    """Process a pre-aligned Media Overlay EPUB3 audiobook into a full NLS Z39.86 Master WAV DTB."""
    # Build converter first to normalize 5-digit prod_id and prefix
    temp_converter = DTBConverter(prod_id=prod_id, work_dir=work_dir / prod_id)
    full_id = temp_converter.prod_id_full
    dtb_folder_name = f"{full_id}.dtb"

    logger.info(f"=== Processing aligned EPUB: {epub_path.name} (ID: {full_id}) ===")

    book_work_dir = work_dir / full_id
    dtb_dir = book_work_dir / dtb_folder_name
    dtb_dir.mkdir(parents=True, exist_ok=True)

    # 1. Extract EPUB overlay metadata, NCX navigation, and SMIL segments
    extractor = EPUBOverlayExtractor(epub_path)
    epub_data = extractor.extract()

    extracted_meta = epub_data["metadata"]

    # ISBN Extraction & API Metadata Enrichment via Libex / Audnexus
    from src.external.metadata_client import extract_isbns_from_sources, BookMetadataFetcher

    if not raw_audio_dir:
        raw_audio_dir = None
    
    raw_files = []
    if raw_audio_dir and raw_audio_dir.exists():
        for ext in [".flac", ".mp3", ".wav", ".opus"]:
            raw_files.extend(list(raw_audio_dir.glob(f"*{ext}")))

    audio_files_paths = [Path(p) for p in epub_data.get("audio_order", [])] + raw_files
    extracted_isbns = extract_isbns_from_sources(
        folder_path=raw_audio_dir if (raw_audio_dir and raw_audio_dir.exists()) else epub_path.parent,
        file_paths=audio_files_paths,
        manifest_or_opf_text=str(extracted_meta)
    )

    api_meta = {}
    if extracted_isbns:
        logger.info(f"Extracting external metadata for ISBN candidates: {extracted_isbns}")
        fetcher = BookMetadataFetcher()
        epub_title = extracted_meta.get("title") or epub_path.stem
        api_meta = fetcher.fetch_all_for_isbns(extracted_isbns, title=epub_title)

    title = api_meta.get("title") or extracted_meta.get("title") or epub_path.stem
    creator = api_meta.get("author_names") or extracted_meta.get("creator") or "Unknown Author"
    publisher = "National Library Service for the Blind and Physically Handicapped, Library of Congress"
    date = extracted_meta.get("date", "2026")
    narrator = api_meta.get("narrator_name") or extracted_meta.get("narrator")
    if not narrator or narrator == "Narrator(s) Unknown":
        narrator = extracted_meta.get("narrator") or "Narrator(s) Unknown"
    description = api_meta.get("description") or extracted_meta.get("description") or ""
    print_publisher = api_meta.get("print_publisher") or ""
    recording_agency = api_meta.get("recording_agency_name") or "NLS Automated Pipeline"
    subjects = api_meta.get("subjects") or []

    author_spoken, author_spelled = format_spelled_author(creator)

    # Build NLS script metadata
    converter = DTBConverter(prod_id=full_id, work_dir=dtb_dir)
    metadata_nls = extract_metadata_from_opf("", full_id, audio_files=[])
    metadata_nls.update({
        "title": title,
        "author_names": creator,
        "publisher_info": print_publisher if print_publisher else publisher,
        "print_publisher": print_publisher,
        "recording_agency_name": recording_agency,
        "copyright_date_and_holders": format_copyright_year(date),
        "narrator_name": narrator,
        "description": description,
        "has_annotation": bool(description.strip()),
        "nls_annotation": description.strip(),
        "subjects": subjects,
        "author_names_and_spelling": f"{author_spoken}, {author_spelled}",
        "author_spelling_only": author_spelled,
        "navigation_levels": converter.calculate_max_depth(converter.prune_nav_tree(epub_data.get("nav_tree", []), epub_data.get("smil_segments", [])))
    })



    # 2. Pass 1: Compute preliminary body duration and generate Closing announcement WAV
    closing_steps = render_announcement_text(metadata_nls, "4.2 Closing")
    closing_wav = book_work_dir / "closing.wav"
    closing_timing = tts_gen.generate_speech_file(closing_steps, closing_wav)

    # Estimate preliminary total reading time for Opening announcement
    opening_wav = book_work_dir / "opening.wav"

    # Calculate initial reading time directly from SMIL segment durations
    body_seconds = sum(max(0.0, seg.get("duration", 0.0)) for seg in epub_data.get("smil_segments", []))
    h_init, m_init = calculate_audio_duration(body_seconds)
    metadata_nls["reading_hours"] = h_init
    metadata_nls["reading_minutes"] = m_init

    opening_steps = render_announcement_text(metadata_nls, "4.1 Opening")
    opening_timing = tts_gen.generate_speech_file(opening_steps, opening_wav)

    # Pass 2: Measure exact WAV durations and audit 5-minute rounding convergence
    op_len = opening_timing.get("_total_duration", 25.0) if opening_timing else 25.0
    cl_len = closing_timing.get("_total_duration", 35.0) if closing_timing else 35.0

    # Body total seconds
    body_seconds = 0.0
    for seg in epub_data.get("smil_segments", []):
        body_seconds += max(0.0, seg.get("duration", 0.0))

    total_exact_seconds = op_len + body_seconds + cl_len
    h_final, m_final = calculate_audio_duration(total_exact_seconds)

    # Re-render opening if reading time rounded hours/minutes changed after exact audit
    if (h_final != h_init or m_final != m_init):
        logger.info(f"Pass 2 Reading Time convergence update: {h_init}h {m_init}m -> {h_final}h {m_final}m")
        metadata_nls["reading_hours"] = h_final
        metadata_nls["reading_minutes"] = m_final
        opening_steps = render_announcement_text(metadata_nls, "4.1 Opening")
        opening_timing = tts_gen.generate_speech_file(opening_steps, opening_wav)

    # 3. Convert all audio to WAV and build Z39 DTB package (OPF, NCX, SMIL)
    converter.generate_z39_package(
        epub_data=epub_data,
        metadata_nls=metadata_nls,
        opening_wav=opening_wav,
        closing_wav=closing_wav,
        opening_timing=opening_timing,
        closing_timing=closing_timing
    )

    # 3b. Generate conforming NLS EPUB Media Overlay package (<prod_id>.epub) parallel to Z39 OPF
    try:
        nls_editor = NLSEPUBEditor()
        nls_epub_path = dtb_dir / f"{full_id}.epub"
        logger.info(f"Generating conforming NLS EPUB: {nls_epub_path}")
        nls_editor.edit_aligned_epub(
            input_epub=epub_path,
            output_epub=nls_epub_path,
            prod_id=full_id
        )
    except Exception as e:
        logger.error(f"Failed to generate conforming NLS EPUB for {full_id}: {e}")
        raise

    # 4. Deliver Master DTB Directory to Output Location
    output_dir.mkdir(parents=True, exist_ok=True)
    final_dtb_destination = output_dir / dtb_folder_name
    if final_dtb_destination.exists():
        shutil.rmtree(final_dtb_destination)
    shutil.copytree(dtb_dir, final_dtb_destination)

    # 5. Clean up temporary working directory to preserve disk space
    shutil.rmtree(book_work_dir, ignore_errors=True)
    logger.info(f"Cleaned up temporary working directory: {book_work_dir}")

    logger.info(f"=== Successfully completed master WAV DTB pipeline for '{title}'! Deliverable: {final_dtb_destination} ===")
    return final_dtb_destination




def process_single_book(
    book_job: Dict[str, Any],
    storyteller: Optional[Any],
    tts_gen: TTSGenerator,
    output_dir: Path,
    work_dir: Path,
    enable_storyteller: bool = True
) -> Path:
    """End-to-end driver: syncs epub + audio via Storyteller (if enabled) and converts to NLS DTB."""
    prod_id = book_job["prod_id"]
    title = book_job["title"]
    epub_path = Path(book_job["epub_path"])
    audio_paths = [Path(p) for p in book_job["audio_paths"]]

    if enable_storyteller and storyteller:
        logger.info(f"Triggering Storyteller alignment for '{title}' (ID: {prod_id})")
        book_id = storyteller.create_book(title)
        storyteller.upload_epub(book_id, epub_path)
        storyteller.upload_audio(book_id, audio_paths)
        storyteller.trigger_sync(book_id)
        # Poll status
        storyteller.poll_job_status(book_id)
        # Download synced epub
        aligned_epub_path = work_dir / f"{prod_id}_aligned.epub"
        storyteller.download_synced_epub(book_id, aligned_epub_path)
        # Cleanup book on server
        storyteller.delete_book(book_id)
        
        epub_to_process = aligned_epub_path
    else:
        epub_to_process = epub_path

    # Determine raw audio directory to pass for ISBN detection
    raw_audio_dir = audio_paths[0].parent if audio_paths else epub_path.parent

    return process_aligned_epub(
        epub_path=epub_to_process,
        prod_id=prod_id,
        tts_gen=tts_gen,
        output_dir=output_dir,
        work_dir=work_dir,
        raw_audio_dir=raw_audio_dir
    )


if __name__ == "__main__":
    test_dir = Path("./test_material/aligned")
    output_dir = Path("./data/output")
    work_dir = Path("./data/processing")

    aligned_epubs = list(test_dir.glob("*.epub"))
    if not aligned_epubs:
        logger.info(f"No aligned EPUBs found in {test_dir}.")
    else:
        tts_gen = TTSGenerator(use_coqui=True)
        for i, epub in enumerate(aligned_epubs):
            prod_id = f"100{i+1}"
            process_aligned_epub(epub, prod_id, tts_gen, output_dir, work_dir)

