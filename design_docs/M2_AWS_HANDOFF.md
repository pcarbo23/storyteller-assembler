# Project Handoff & Architecture Guide: Storyteller Assembler (M2 & Cloud Production)

**To:** Incoming AI Engineering Agent / Development Team  
**From:** Antigravity AI Agent & M2 Lead Architect  
**Date:** October 5, 2026  
**Subject:** M2 Apple Silicon Production Status, Bug Fixes, Compliance Engine, and AWS Roadmap  
**Repository Branch:** `m2-production` (Tracking `origin/m2-production`)  

---

## 1. Executive Summary & Critical Context

The **Storyteller Assembler** is an event-driven Python pipeline that ingests source trade EPUBs and audiobook narration files to produce dual, highly regulated deliverables:
1. **ANSI/NISO Z39.86-2002 Digital Talking Book (DTB)**: Master 44.1kHz WAV package (`data/output/<prod_id>.dtb/`) with strict SMIL 1.0 synchronization, hierarchical NCX navigation, and OPF manifest.
2. **EPUB 3.0 Media Overlay Package**: Conforming EPUB 3 (`data/output/<prod_id>.epub`) with spine-ordered SMIL overlays, refined `us-nls-dbXXXXXX` identifiers, and synchronized navigation.

### Current Operating State (as of October 5, 2026)
- The pipeline on branch **`m2-production`** is **fully operational, optimized, and verified** on Apple Silicon M2.
- **Hardware Acceleration**: Alignment execution time dropped from **12 minutes (Intel baseline) to ~2 minutes (M2 native)** via Metal GPU/ANE acceleration.
- **Bug Fixes Applied**:
  - TTS deadlock & thread freezing resolved via subprocess isolation.
  - Tagless WAV duration truncation bug resolved via standard `wave` library parsing.
  - Multi-element composite chapter headings bug resolved in DTB and EPUB navigation.
- **Compliance Validation**: Dual validation (`ZedVal` & `NlsVal2` v4.08) runs automatically on all productions, producing 100% clean passes (`<pass>true</pass>`) with reports archived to `data/reports/`.
- **Machine Rebuild Alert**: This M2 machine is scheduled for an ITS rebuild. **All code, tests, documentation, and configuration have been committed and pushed to GitHub on branch `m2-production`**.

---

## 2. Onboarding on a Fresh / Rebuilt Machine

If you are a new AI instance resuming work on a freshly rebuilt Mac (or remote workstation), follow these exact onboarding steps:

### Step 1: Clone and Checkout Branch
```bash
git clone git@github.com:pcarbo23/storyteller-assembler.git
cd storyteller-assembler
git checkout m2-production
```

### Step 2: Install System Dependencies via Homebrew
```bash
brew install ffmpeg espeak-ng openjdk node
```

### Step 3: Install Native Aligner CLI Globally
```bash
# Allow script execution for storyteller's binary dependencies
npm install -g --dangerously-allow-all-scripts @storyteller-platform/align@0.2.4

# Verify CLI is responsive
align --help
```

### Step 4: Configure Validator Environment Variable
The software standardizes on **`NLS_VALIDATOR_JAR`** for the proprietary NLS validation suite (`AllVal.jar`):
```bash
# Append to shell profile
echo 'export NLS_VALIDATOR_JAR="/Users/phca/validators/AllVal.jar"' >> ~/.zshrc
export NLS_VALIDATOR_JAR="/Users/phca/validators/AllVal.jar"
```
*(Note: If `AllVal.jar` is missing, the pipeline gracefully skips compliance verification and records status as `"skipped"` without failing production).*

### Step 5: Run Automated Environment Setup
```bash
./setup_env.sh
```
This script audits Python, initializes `.venv`, installs `requirements.txt`, checks system binaries (`ffmpeg`, `espeak-ng`, `java`, `docker`), and verifies `NLS_VALIDATOR_JAR`.

### Step 6: Verify Test Suite
```bash
.venv/bin/pytest
```
**Expected baseline:** 36 passed, 7 skipped (skipped tests require ~37GB external test materials).

---

## 3. Key Architecture & Recent Bug Fixes

### A. Dual-Mode Forced Alignment (`src/align_runner.py`)
- **macOS (Native Mode)**: When running on macOS (`sys.platform == 'darwin'`) with `align` or `npx` available, `AlignRunner` invokes `align` directly on the host. This taps directly into Apple Silicon's 16-Core Neural Engine (ANE) and Metal GPU, executing alignment in ~2 minutes per book.
- **Linux/CI Fallback (Docker Mode)**: When running on Linux, it automatically launches transient containers using `@storyteller-platform/align` inside Docker.
- **Watcher & Dashboard Integration**: `scripts/run_ingest_watcher.py` and `scripts/dashboard.py` check `is_native_align_mode()`; if native alignment is ready, the system reports status as `online` even if Docker Desktop is stopped.

### B. Subprocess TTS Worker & Timeout Guard (`src/tts_generator.py`, `scripts/generate_tts_audio.py`)
- **Prior Issue**: During prolonged batch runs, Coqui TTS / PyTorch synthesis occasionally locked up during closing credits rendering, causing the watcher thread to hang indefinitely.
- **Resolution**: TTS audio generation is isolated into `scripts/generate_tts_audio.py` executed via `subprocess.run` with a configurable timeout (180s) and automatic retry fallback.

### C. TTS Audio Duration & Proportional Drift Fix (`src/tts_generator.py`)
- **Prior Issue**: Uncompressed PCM WAV files generated by `ffmpeg` have no ID3 tags. `mutagen.File(wav_path)` returned a `mutagen.wave.WAVE` object which evaluated to `False` in boolean contexts (`if audio and audio.info:`). As a result, total audio duration defaulted to `5.0s`, compressing announcement step boundaries by ~30x (e.g. `docTitle` 21ms, `docAuthor` 74ms).
- **Resolution**:
  - Replaced mutagen WAV duration calculation with Python's standard `wave` module (`wave.open`).
  - Synthesizes announcement steps with explicit millisecond duration tracking and 400ms inter-step silence buffers, guaranteeing mathematically exact `clipBegin` and `clipEnd` boundaries in DTB NCX navigation.

### D. Multi-Element Chapter Headings Bug Fix (`src/dtb_converter.py`, `src/epub_nls_editor.py`)
- **Prior Issue**: When publishers structure chapter headings across multiple HTML tags (e.g., `<h1 class="chap_num">Chapter 1</h1>` followed by `<h1 class="chap_head">GET FIT WITH SANTA!</h1>`), the aligner created separate sentence spans for each. Previously, `resolve_node_audio` matched only the first span (`Chapter 1`), truncating the audio clip before the chapter title was spoken, and leaving navigation labels incomplete.
- **Resolution**:
  - In `src/dtb_converter.py`: Discovers adjacent multi-span heading elements at the start of chapter sections, merges them into composite labels (e.g., `"Chapter 1: Get Fit With Santa!"`), and extends the audio clip from the start of the first span (`clipBegin`) to the end of the last span (`clipEnd`).
  - In `src/epub_nls_editor.py`: Added `_synchronize_navigation(temp_dir)` to update both `toc.ncx` and `nav.xhtml` inside conforming EPUB deliverables with composite chapter titles.

### E. Dual Deliverables Structure & NlsVal2 Extraneous File Fix (`src/main.py`)
- **Prior Issue**: The conforming EPUB was being written to `dtb_dir / f"{full_id}.epub"` (inside the DTB folder). When `NlsVal2` inspected the DTB package against its OPF manifest, it failed with:
  `nlsext_opf_extraneousFile: File named "dbXXXXXX.epub" exists in the input but is not listed in the manifest.`
- **Resolution**:
  - In `src/main.py`, the conforming EPUB is output to `output_dir / f"{full_id}.epub"`, **parallel** to `output_dir / f"{full_id}.dtb/`.
  - Result: Both `ZedVal` and `NlsVal2` pass with `<pass>true</pass>` and zero errors across all productions.

---

## 4. Pipeline Configuration & Data Stores

| Component | Location | Description |
| :--- | :--- | :--- |
| **Production ID Leaser** | `config/production_config.json` | Controls sequential ID leasing (`prefix: "db"`, `next_value: 100106`). |
| **Audit Database** | `data/production_history.db` | SQLite archive auto-migrated on first run. Logs IDs, titles, ISBNs, `zedval_status`, `nlsval_status`, and `validator_version`. |
| **Flat Audit Log** | `data/production_log.csv` | Append-only CSV mirror of production runs. |
| **Validation Reports** | `data/reports/` | Preserves `<prod_id>_ZedVal.xml`, `<prod_id>_ZedVal.log`, `<prod_id>_NlsVal2.xml`, `<prod_id>_NlsVal2.log`. |
| **Input Queue** | `data/ingest/` | Drop folder for incoming unaligned book pairs (`.epub` + audio files). |
| **Deliverables** | `data/output/` | Final deliverables: `<prod_id>.dtb/` and `<prod_id>.epub`. |
| **Archived Holdings** | `~/nlsbpd/output_holding/` | Holds legacy/backfilled runs (`db100065`–`db100080`). |

---

## 5. Execution Modes

### 1. Ingestion Watcher (Daemon)
Monitors `data/ingest/` continuously and processes books through alignment, TTS synthesis, packaging, and validation:
```bash
source .venv/bin/activate
python scripts/run_ingest_watcher.py
```

### 2. Streamlit Web Dashboard (GUI)
Interactive dashboard for monitoring the live queue, inspecting production history, and starting/stopping the watcher:
```bash
source .venv/bin/activate
streamlit run scripts/dashboard.py
```
*(Or double-click `launch_dashboard.command` in macOS Finder).*

### 3. Post-Alignment Test Tool
Runs DTB conversion, NLS announcements, and compliance validation directly on pre-aligned EPUBs without re-running alignment:
```bash
source .venv/bin/activate
python scripts/test_post_storyteller.py -e "<path_to_aligned.epub>" -s "<path_to_source_dir>" -p "dbXXXXXX"
```

---

## 6. AWS Cloud Migration Roadmap

When migrating from this M2 prototype environment to AWS (EC2/ECS or AWS Batch):
1. **Container Alignment**:
   - `src/align_runner.py` already includes Docker execution logic (`_align_docker`).
   - For GPU-accelerated cloud alignment, configure an NVIDIA CUDA container image with `whisper.cpp` (`linux-x64-cuda`).
2. **Validator Distribution**:
   - Follow **Strategy 1** in [design_docs/VALIDATOR_DISTRIBUTION_STRATEGIES.md](file:///Users/phca/dev_projects/storyteller-assembler/design_docs/VALIDATOR_DISTRIBUTION_STRATEGIES.md) to bootstrap `AllVal.jar` from private S3 storage (`s3://<bucket>/validators/AllVal.jar`).
3. **Storage Tiering**:
   - Replace local `data/ingest/` and `data/output/` mounts with S3 bucket triggers (e.g., S3 event notifications -> SQS queue -> worker instance).
   - Migrate `data/production_history.db` to Amazon RDS PostgreSQL or DynamoDB for distributed production tracking.
