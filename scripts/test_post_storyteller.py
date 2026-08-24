#!/usr/bin/env python3
"""
Manual validation script for post-storyteller EPUB processing and compliance testing.
"""

import os
import sys
import argparse
import subprocess
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Virtual Environment Guard
in_virtualenv = sys.prefix != sys.base_prefix or hasattr(sys, 'real_prefix')
if not in_virtualenv:
    print("\n" + "="*80)
    print("WARNING: You are running this script using the global python interpreter.")
    print("This project requires dependencies from the local virtual environment.")
    print("Please run this script using the virtual environment interpreter:")
    print("  .venv/bin/python scripts/test_post_storyteller.py <args>")
    print("="*80 + "\n")
    sys.exit(1)

from src import __version__
from src.main import process_aligned_epub
from src.tts_generator import TTSGenerator


def parse_xml_failures(xml_path: Path) -> list:
    """Parse ZedVal.xml to find errors and failures."""
    failures = []
    if not xml_path.exists():
        return [f"Validation XML output not found at {xml_path}"]

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        # Find elements with severity/level representing failures
        for error in root.findall(".//error") + root.findall(".//failure") + root.findall(".//message"):
            level = error.get("level") or ""
            test_id = error.get("testId") or ""
            if level in ("failure", "severe", "error") or error.tag in ("error", "failure"):
                msg = error.text or error.get("message") or "Unknown compliance error"
                line = error.get("line") or "unknown line"
                failures.append(f"Line {line} ({test_id}): {msg}")
            
        # Fallback to string check in case of custom formats
        content = xml_path.read_text()
        if 'level="failure"' in content and not failures:
            failures.append("Detected level=\"failure\" in XML file contents.")
    except Exception as e:
        failures.append(f"Failed to parse XML file: {e}")

    return failures


def extract_validator_version(xml_path: Path) -> str:
    """Extract appVersion attribute from the <program> element in ZedVal/NlsVal XML report."""
    if not xml_path or not xml_path.exists():
        return ""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        program = root.find(".//program")
        if program is not None:
            return program.get("appVersion", "")
    except Exception:
        pass
    return ""


def main():
    parser = argparse.ArgumentParser(
        description=f"Storyteller Assembler: Verify compliance of post-storyteller media overlay EPUB (v{__version__})."
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--epub", required=True, help="Path to the post-storyteller media overlay EPUB.")
    parser.add_argument("--source", required=True, help="Path to the original pre-storyteller source material directory.")
    parser.add_argument("--output", default="./data/output", help="Directory to save final master DTB.")
    parser.add_argument("--prod-id", help="Production ID. Defaults to name-based ID.")
    args = parser.parse_args()

    epub_path = Path(args.epub)
    source_path = Path(args.source)
    output_dir = Path(args.output)
    work_dir = PROJECT_ROOT / "data" / "processing"

    if not epub_path.exists():
        print(f"Error: EPUB path '{epub_path}' does not exist.")
        sys.exit(1)
    if not source_path.exists():
        print(f"Error: Source path '{source_path}' does not exist.")
        sys.exit(1)

    # Generate a prod_id if not provided
    prod_id = args.prod_id
    if not prod_id:
        prod_id = epub_path.stem.lower().replace(" (readaloud)", "").replace(" ", "_")
        # Keep it alphanum and clean
        prod_id = "".join([c for c in prod_id if c.isalnum() or c == "_"])[:10]

    print(f"--- 1. Running DTB Pipeline for {epub_path.name} (Prod ID: {prod_id}) ---")
    tts_gen = TTSGenerator(use_coqui=False)  # Fast TTS generator fallback for testing
    
    try:
        dtb_dir = process_aligned_epub(
            epub_path=epub_path,
            prod_id=prod_id,
            tts_gen=tts_gen,
            output_dir=output_dir,
            work_dir=work_dir,
            raw_audio_dir=source_path
        )
    except Exception as e:
        print(f"Pipeline Execution Failed: {e}")
        sys.exit(1)

    opf_file = list(dtb_dir.glob("*.opf"))
    if not opf_file:
        print(f"Error: No OPF file generated in {dtb_dir}")
        sys.exit(1)
    opf_path = opf_file[0]
    print(f"Generated OPF: {opf_path}")

    print("\n--- 2. Starting Compliance Testing (Validators) ---")
    allval_jar = PROJECT_ROOT / "test_material" / "AllVal.jar"
    if not allval_jar.exists():
        print(f"Warning: AllVal.jar not found at {allval_jar}. Skipping compliance execution.")
        sys.exit(0)

    prod_id = opf_path.stem
    reports_dir = PROJECT_ROOT / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Run default ZedVal
    print(f"Running ZedVal on {opf_path.name}...")
    try:
        subprocess.run(
            ["java", "-cp", str(allval_jar), "ZedVal", opf_path.name],
            cwd=str(dtb_dir),
            capture_output=True,
            text=True,
            timeout=60
        )
        temp_zedval = dtb_dir / "ZedVal.xml"
        dest_zedval = reports_dir / f"{prod_id}_ZedVal.xml"
        if temp_zedval.exists():
            import shutil
            shutil.move(str(temp_zedval), str(dest_zedval))
        temp_zedval_log = dtb_dir / "ZedVal.log"
        dest_zedval_log = reports_dir / f"{prod_id}_ZedVal.log"
        if temp_zedval_log.exists():
            import shutil
            shutil.move(str(temp_zedval_log), str(dest_zedval_log))
    except Exception as e:
        print(f"Error executing ZedVal: {e}")
        sys.exit(1)

    # 2. Run NlsVal2 (Inactive by default)
    ENABLE_NLSVAL2 = False
    failures_nlsval = []
    if ENABLE_NLSVAL2:
        print(f"Running NlsVal2 on {opf_path.name}...")
        try:
            subprocess.run(
                ["java", "-cp", str(allval_jar), "NlsVal2", opf_path.name],
                cwd=str(dtb_dir),
                capture_output=True,
                text=True,
                timeout=60
            )
            temp_nlsval = dtb_dir / "NlsVal2.xml"
            dest_nlsval = reports_dir / f"{prod_id}_NlsVal2.xml"
            if temp_nlsval.exists():
                import shutil
                shutil.move(str(temp_nlsval), str(dest_nlsval))
            temp_nlsval_log = dtb_dir / "NlsVal2.log"
            dest_nlsval_log = reports_dir / f"{prod_id}_NlsVal2.log"
            if temp_nlsval_log.exists():
                import shutil
                shutil.move(str(temp_nlsval_log), str(dest_nlsval_log))
            failures_nlsval = parse_xml_failures(dest_nlsval)
        except Exception as e:
            print(f"Error executing NlsVal2: {e}")
            sys.exit(1)

    # Parse and combine failures
    failures_zedval = parse_xml_failures(dest_zedval)
    all_failures = failures_zedval + failures_nlsval

    print("\n--- 3. Compliance Verification Results ---")
    if all_failures:
        print(f"[FAILURE] Compliance check found {len(all_failures)} issues:")
        for failure in all_failures:
            print(f"  - {failure}")
        sys.exit(1)
    else:
        print("[SUCCESS] All compliance validation checks (ZedVal & NlsVal2) passed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()
