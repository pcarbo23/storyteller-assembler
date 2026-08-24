#!/usr/bin/env python3
"""
Active folder Ingestion Watcher daemon with Storyteller health checking and E2E progress monitoring.
"""

import os
import sys
import time
import json
import logging
import subprocess
import threading

# Suppress PyTorch OpenMP warnings
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"
from pathlib import Path
from datetime import datetime

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Add common macOS paths to environment PATH for GUI environment support (like AppleScript App launches)
for path in ["/usr/local/bin", "/opt/homebrew/bin", "/Applications/Docker.app/Contents/Resources/bin"]:
    if path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{path}:{os.environ.get('PATH', '')}"

# Virtual Environment Guard
in_virtualenv = sys.prefix != sys.base_prefix or hasattr(sys, 'real_prefix')
if not in_virtualenv:
    print("\n" + "="*80)
    print("WARNING: You are running this script using the global python interpreter.")
    print("This project requires dependencies from the local virtual environment.")
    print("Please run this script using the virtual environment interpreter:")
    print("  .venv/bin/python scripts/run_ingest_watcher.py")
    print("="*80 + "\n")
    sys.exit(1)

from src.ingestion import IngestionWatcher
from src.align_runner import AlignRunner
from src.tts_generator import TTSGenerator, extract_metadata_from_opf
from src.main import process_single_book
from src.prod_id_manager import ProdIDManager
from src.tracker import ProductionTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_watcher")


def send_macos_notification(title: str, message: str):
    """Send native macOS desktop notification."""
    try:
        title_escaped = title.replace('"', '\\"')
        message_escaped = message.replace('"', '\\"')
        cmd = [
            "osascript", "-e",
            f'display notification "{message_escaped}" with title "{title_escaped}"'
        ]
        subprocess.run(cmd, capture_output=True, text=True)
    except Exception as e:
        logger.debug(f"Failed to send macOS notification: {e}")


def write_heartbeat():
    """Write daemon liveness heartbeat."""
    heartbeat_file = PROJECT_ROOT / "data" / "watcher_heartbeat.json"
    heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        heartbeat_file.write_text(json.dumps({
            "status": "running",
            "last_heartbeat": datetime.now().isoformat(),
            "pid": os.getpid()
        }, indent=2))
    except Exception as e:
        logger.debug(f"Failed to write heartbeat file: {e}")


def check_docker_health() -> bool:
    """Check if Docker service is running on host."""
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def write_storyteller_status(status: str):
    """Write the current storyteller docker status to a shared JSON file."""
    status_file = PROJECT_ROOT / "data" / "storyteller_status.json"
    status_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        status_file.write_text(json.dumps({
            "status": status,
            "timestamp": datetime.now().isoformat()
        }, indent=2))
    except Exception as e:
        logger.debug(f"Failed to write storyteller status file: {e}")


def write_job_status(prod_id: str, title: str, status: str, elapsed_seconds: float = 0.0, error: str = None, start_time: float = None):
    """Write active book processing status to a local tracking JSON file."""
    status_file = PROJECT_ROOT / "data" / "processing" / f"{prod_id}_status.json"
    status_file.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "title": title,
        "prod_id": prod_id,
        "status": status,
        "time_elapsed_seconds": round(elapsed_seconds, 1),
        "last_update": datetime.now().isoformat()
    }
    if error:
        data["error"] = error
    if start_time:
        data["start_time"] = datetime.fromtimestamp(start_time).isoformat()
        
    try:
        status_file.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.debug(f"Failed to write job status file for {prod_id}: {e}")


def prune_completed_status_files(keep_recent: int = 20):
    """Prune older completed status JSON files, keeping only the latest records for live dashboard monitoring."""
    work_dir = PROJECT_ROOT / "data" / "processing"
    if not work_dir.exists():
        return
    try:
        completed_files = []
        for sf in work_dir.glob("*_status.json"):
            try:
                data = json.loads(sf.read_text())
                if data.get("status") == "completed":
                    completed_files.append((sf, data.get("last_update", "")))
            except Exception:
                continue
        # Sort descending by last_update
        completed_files.sort(key=lambda x: x[1], reverse=True)
        for sf, _ in completed_files[keep_recent:]:
            try:
                sf.unlink()
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Failed to prune completed status files: {e}")


def process_book_job(pair: dict, align_runner: AlignRunner, tts_gen: TTSGenerator, id_manager: ProdIDManager, tracker: ProductionTracker):
    """Handle the full end-to-end sync, TTS generation, packaging, and validation."""
    title = pair["title"]
    epub_path = pair["epub_path"]
    audio_paths = pair["audio_paths"]
    
    start_time = time.time()
    
    # Thread-safely lease a sequential production ID (e.g. db100000)
    try:
        prod_id = id_manager.lease_id()
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] Failed to lease Production ID: {e}")
        return
        
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] [DETECTED] Found new book set: '{title}' ({len(audio_paths)} audio tracks) -> Leased ID: {prod_id}")
    write_job_status(prod_id, title, "starting", start_time=start_time)

    # Step 1 & 2: Local Forced Alignment via node:alpine container
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [ALIGNER] Starting local forced alignment...")
    write_job_status(prod_id, title, "aligning", time.time() - start_time, start_time=start_time)
    send_macos_notification("Book Detected", f"Started aligning '{title}' (ID: {prod_id})")
    
    work_dir = PROJECT_ROOT / "data" / "processing"
    aligned_epub_path = work_dir / f"{prod_id}_aligned.epub"
    
    try:
        audiobook_dir = audio_paths[0].parent
        align_runner.align(
            epub_path=epub_path,
            audiobook_dir=audiobook_dir,
            output_path=aligned_epub_path,
            model="tiny.en"
        )
    except Exception as e:
        err_msg = f"Alignment failed: {e}"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] {err_msg}")
        write_job_status(prod_id, title, "failed_alignment", time.time() - start_time, error=err_msg, start_time=start_time)
        send_macos_notification("Pipeline Failed", f"Alignment failed for '{title}': {e}")
        return

    # Step 4: Run TTS Generation, Conversion, and Package Build
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [TTS & CONVERSION] Generating TTS announcements and building Z39.86 DTB...")
    write_job_status(prod_id, title, "processing_dtb", time.time() - start_time, start_time=start_time)
    send_macos_notification("Processing", f"Generating TTS & packaging NLS DTB for '{title}'")
    
    output_dir = PROJECT_ROOT / "data" / "output"
    try:
        dtb_dir = process_single_book(
            book_job={
                "title": title,
                "prod_id": prod_id,
                "epub_path": aligned_epub_path,
                "audio_paths": audio_paths
            },
            storyteller=None,
            tts_gen=tts_gen,
            output_dir=output_dir,
            work_dir=work_dir,
            enable_storyteller=False
        )
    except Exception as e:
        err_msg = f"Conversion or TTS generation failed: {e}"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] {err_msg}")
        write_job_status(prod_id, title, "failed_conversion", time.time() - start_time, error=err_msg, start_time=start_time)
        send_macos_notification("Pipeline Failed", f"Conversion failed for '{title}': {e}")
        return

    # Step 5: Compliance Check (ZedVal & NlsVal2)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [VALIDATION] Running ZedVal & NlsVal2 compliance verification...")
    write_job_status(prod_id, title, "validating", time.time() - start_time, start_time=start_time)
    
    allval_jar = PROJECT_ROOT / "test_material" / "AllVal.jar"
    zedval_status = "pass"
    nlsval_status = "pass"
    val_version = ""
    failures_zedval = []
    failures_nlsval = []
    
    if allval_jar.exists():
        import shutil
        reports_dir = PROJECT_ROOT / "data" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        opf_file = list(dtb_dir.glob("*.opf"))[0]
        
        # 1. Run ZedVal
        subprocess.run(
            ["java", "-cp", str(allval_jar), "ZedVal", opf_file.name],
            cwd=str(dtb_dir),
            capture_output=True,
            text=True
        )
        temp_zedval = dtb_dir / "ZedVal.xml"
        dest_zedval = reports_dir / f"{prod_id}_ZedVal.xml"
        if temp_zedval.exists():
            shutil.move(str(temp_zedval), str(dest_zedval))
        temp_zedval_log = dtb_dir / "ZedVal.log"
        dest_zedval_log = reports_dir / f"{prod_id}_ZedVal.log"
        if temp_zedval_log.exists():
            shutil.move(str(temp_zedval_log), str(dest_zedval_log))
            
        # 2. Run NlsVal2 (Inactive by default)
        ENABLE_NLSVAL2 = False
        if ENABLE_NLSVAL2:
            subprocess.run(
                ["java", "-cp", str(allval_jar), "NlsVal2", opf_file.name],
                cwd=str(dtb_dir),
                capture_output=True,
                text=True
            )
            temp_nlsval = dtb_dir / "NlsVal2.xml"
            dest_nlsval = reports_dir / f"{prod_id}_NlsVal2.xml"
            if temp_nlsval.exists():
                shutil.move(str(temp_nlsval), str(dest_nlsval))
            temp_nlsval_log = dtb_dir / "NlsVal2.log"
            dest_nlsval_log = reports_dir / f"{prod_id}_NlsVal2.log"
            if temp_nlsval_log.exists():
                shutil.move(str(temp_nlsval_log), str(dest_nlsval_log))
                
            # Parse XMLs
            from scripts.test_post_storyteller import parse_xml_failures, extract_validator_version
            failures_nlsval = parse_xml_failures(dest_nlsval)
            if failures_nlsval:
                nlsval_status = "fail"
        else:
            nlsval_status = "pending"
            
        # Parse XMLs
        from scripts.test_post_storyteller import parse_xml_failures, extract_validator_version
        failures_zedval = parse_xml_failures(dest_zedval)
        val_version = extract_validator_version(dest_zedval)
        
        if failures_zedval:
            zedval_status = "fail"
            
        if failures_zedval or failures_nlsval:
            err_msg = f"Compliance checks failed. ZedVal: {failures_zedval}. NlsVal2: {failures_nlsval}"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] {err_msg}")
            
            # Log failure to tracking database
            tracker.log_production(
                prod_id=prod_id,
                opf_path=opf_file,
                isbn_epub=pair.get("isbn_epub", "Unknown"),
                isbn_audio=pair.get("isbn_audio", "Unknown"),
                zedval_status=zedval_status,
                nlsval_status=nlsval_status,
                validator_version=val_version
            )
            
            write_job_status(prod_id, title, "failed_validation", time.time() - start_time, error=err_msg, start_time=start_time)
            send_macos_notification("Validation Failed", f"Compliance checks failed for '{title}'")
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] [WATCHER] Ready and waiting for next book...")
            return

    total_time = time.time() - start_time
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [SUCCESS] Finished processing: '{title}' in {int(total_time)}s! Deliverable: {dtb_dir.name}")
    
    # Extract OPF file path for tracking database
    try:
        opf_file = list(dtb_dir.glob("*.opf"))[0]
    except Exception as e:
        opf_file = None
        logger.debug(f"Failed to locate OPF file: {e}")

    # Track output in SQLite and CSV
    if opf_file:
        tracker.log_production(
            prod_id=prod_id,
            opf_path=opf_file,
            isbn_epub=pair.get("isbn_epub", "Unknown"),
            isbn_audio=pair.get("isbn_audio", "Unknown"),
            zedval_status=zedval_status,
            nlsval_status=nlsval_status,
            validator_version=val_version
        )

    # Clean up intermediate build artifacts from data/processing/
    try:
        if aligned_epub_path.exists():
            aligned_epub_path.unlink()
        upgraded_epub = work_dir / f"upgraded_{epub_path.name}"
        if upgraded_epub.exists():
            upgraded_epub.unlink()
        temp_dir = work_dir / prod_id
        if temp_dir.exists() and temp_dir.is_dir():
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:
        logger.debug(f"Failed to delete intermediate processing artifact: {e}")

    write_job_status(prod_id, title, "completed", total_time)
    
    # Prune old completed status JSON files (retaining latest 20 for live dashboard)
    prune_completed_status_files(keep_recent=20)
    
    send_macos_notification("Success!", f"Successfully processed '{title}' in {int(total_time)}s.")
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] [WATCHER] Ready and waiting for next book...")


def heartbeat_thread_target():
    """Background heartbeat loop."""
    while True:
        write_heartbeat()
        docker_ok = check_docker_health()
        write_storyteller_status("online" if docker_ok else "offline")
        time.sleep(5)


def main():
    ingest_dir = PROJECT_ROOT / "data" / "ingest"
    watcher = IngestionWatcher(ingest_dir, poll_interval=5)
    align_runner = AlignRunner(PROJECT_ROOT)
    tts_gen = TTSGenerator(use_coqui=True)
    
    # Initialize production configurations and trackers
    config_path = PROJECT_ROOT / "config" / "production_config.json"
    db_path = PROJECT_ROOT / "data" / "production_history.db"
    csv_path = PROJECT_ROOT / "data" / "production_log.csv"
    
    id_manager = ProdIDManager(config_path)
    tracker = ProductionTracker(db_path, csv_path)
    
    print(f"=== Starting Ingestion Watcher Daemon ===")
    print(f"Monitoring folder: {ingest_dir}")
    print(f"Waiting for books...")
    
    # Start heartbeat thread
    h_thread = threading.Thread(target=heartbeat_thread_target, daemon=True)
    h_thread.start()
    
    was_online = None
    
    # Watch and process incoming books
    for pair in watcher.start_polling():
        # Check Docker service health before processing
        is_online = check_docker_health()
        
        if not is_online:
            if was_online is not False:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [WARNING] Docker daemon is offline.")
                print(f"Ingestion is paused. Please start Docker.")
                write_storyteller_status("offline")
                send_macos_notification("Docker Offline", "Docker daemon is offline. Ingestion paused.")
                was_online = False
            time.sleep(10)
            continue
        
        if was_online is False:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO] Docker service is online. Resuming ingestion.")
            write_storyteller_status("online")
            send_macos_notification("Docker Online", "Docker daemon is online. Resuming ingestion.")
            was_online = True
            
        process_book_job(pair, align_runner, tts_gen, id_manager, tracker)


if __name__ == "__main__":
    main()
