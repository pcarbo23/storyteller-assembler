# Project Handoff & Architecture Guide: Storyteller Assembler

**To:** M2 Apple Silicon Development Team / AI Agent
**From:** Lead Architect & Project Manager (Intel Baseline Team)
**Date:** September 30, 2026
**Subject:** System Architecture, M2 Optimization Strategy, and AWS Migration Path

## 1. Executive Summary
The **Storyteller Assembler** is a sophisticated, zero-state Python pipeline designed to automate the production of highly regulated, ANSI/NISO Z39.86-2002 compliant Digital Talking Books (DTB) and EPUB3 Media Overlays. 

Currently, the system is fully functional on an Intel Mac baseline (`v1.0.2`). Your immediate mandate on the new M2 Mac is to optimize this software to produce a batch of **1,500 DTBs** at maximum efficiency by tapping into Apple Silicon’s hardware acceleration. 

The M2 is a prototype/production bridge. The **ultimate long-term goal** is to migrate this system to AWS (e.g., EC2/ECS with CUDA or AWS Batch) for infinite scalability.

---

## 2. The Branching Strategy: Why `m2-production`?
You will be working on a dedicated branch named `m2-production`. **Do not alter the `main` branch or the `v1.0.2` tag.**

*   **Intel Mac Safety:** The Intel Mac is our safe, working fallback. It relies on a Dockerized version of the alignment tool. It must remain untouched so we can produce materials instantly if the M2 encounters downtime.
*   **M2 Optimization Freedom:** A dedicated branch gives you full freedom to refactor `src/align_runner.py` for native macOS execution, bypassing Docker entirely to unlock the M2's Neural Engine and Metal GPU.
*   **Shared Codebase Integrity:** 95% of this codebase (TTS, packaging, database, validation) is hardware-agnostic. A branch prevents the nightmare of maintaining two separate hard-forked repositories while isolating hardware-specific execution logic.

---

## 3. System Architecture & Pipeline Stages
The pipeline is event-driven via `scripts/run_ingest_watcher.py` or a Streamlit GUI. It processes raw assets through 7 distinct stages:

1.  **Ingestion (`src/ingestion.py`):** Scans for directories containing exactly one EPUB and its corresponding audio narration.
2.  **Forced Alignment (`src/align_runner.py`):** The core bottleneck. Currently uses `@storyteller-platform/align` (a Node.js wrapper for `whisper.cpp`) to perform speech-to-text and Levenshtein distance matching against the EPUB XHTML, generating synchronized SMIL files.
3.  **Metadata Enrichment (`src/prod_id_manager.py`, `src/external/metadata_client.py`):** Leases sequential `dbXXXXXX` IDs and fetches bibliographic data via Libex, Audnexus, Open Library, etc.
4.  **Neural TTS Generation (`src/tts_generator.py`):** Generates mandatory NLS announcements (e.g., phonetically spelling author names). Uses a **Two-Pass Convergence Algorithm** to ensure exact 5-minute rounding compliance for audio durations.
5.  **Master DTB & EPUB3 Packaging (`src/dtb_converter.py`, `src/epub_nls_editor.py`):** Transcodes all audio to 44.1kHz WAV, builds strict Z39.86-2002 OPF/NCX/SMIL manifests, and strict EPUB3 Media Overlays (`epub_MED_015` compliance).
6.  **Compliance Verification (`AllVal.jar`):** Executes Java-based `ZedVal` and `NlsVal2` compliance checks, generating XML reports.
7.  **Audit Tracking (`src/tracker.py`):** Logs the entire run, durations, and compliance states to SQLite and CSV.

---

## 4. Repository Structure & Zero-State Design
The project uses a **Zero-State Architecture**. No proprietary data, test books, databases (`*.db`), or output packages are stored in Git.

*   `src/`: Core Python pipeline modules.
*   `scripts/`: Entry points (`run_ingest_watcher.py`, `test_post_storyteller.py`).
*   `docker/`: Legacy Dockerfiles (currently used by Intel/Linux for alignment).
*   `config/`, `design_docs/`: Configuration and architecture references.
*   `data/`: **(Ignored in Git)** The working directory. Contains `/ingest`, `/processing`, `/output`, `/reports`, and `production_history.db`. The DB and folders are auto-initialized on the first run.

---

## 5. Technology Stack
*   **Core Logic:** Python 3.9+
*   **Alignment Engine:** Node.js, `@storyteller-platform/align` / `ghost-story` (utilizing Whisper.cpp).
*   **Media Processing:** FFmpeg (required on host machine).
*   **Validation:** Java (JRE required for `AllVal.jar`).
*   **Data Storage:** SQLite3 (Local tracker) & CSV.
*   **UI:** Streamlit.

---

## 6. The Immediate M2 Challenge: Bypassing Docker
**The Problem:** The Intel machine runs the aligner inside a Linux Docker container (`auto_story_pipe_aligner:latest`). On an M2 Mac, Docker runs inside a Linux virtual machine. Apple does **not** expose the Apple Neural Engine (ANE) or Metal GPU to Linux VMs. Consequently, the M2 is forced into emulated CPU execution (taking ~491 seconds per book instead of an expected ~45 seconds).

**Your First Task on the M2:**
1.  **Install Host Dependencies:** Ensure Node.js 20/24+, FFmpeg, and Java are installed natively via Homebrew.
2.  **Global NPM Install (With Scripts Allowed):**
    In npm v11/v12, `--allow-scripts` requires an explicit package list (without semver ranges) or global configuration. Do **not** pass bare `--allow-scripts <pkg@^semver>` because npm treats the package argument as the script list, causing an `ENOENT: package.json` failure.

    Use either of the following commands:
    ```bash
    # Method A: Set the allow-scripts config for storyteller dependencies (Recommended)
    npm config set allow-scripts=@storyteller-platform/align,esbuild,onnxruntime-node,protobufjs --location=user
    npm install -g @storyteller-platform/align@0.2.4

    # Method B: One-liner allowing script execution for this install
    npm install -g --dangerously-allow-all-scripts @storyteller-platform/align@0.2.4
    ```

    **Verification Step on M2:**
    Verify the CLI is installed and responsive:
    ```bash
    align --help
    ```
3.  **Refactor `src/align_runner.py` (Dual-Mode):**
    Modify the Python code to dynamically check if it is running on macOS (`sys.platform == 'darwin'`) with Node installed. If so, execute `npx @storyteller-platform/align` natively via `subprocess`. 
    When run natively on the M2, `ghost-story` will automatically download the `darwin-arm64-coreml` Whisper binary and the ANE Core ML models. This skips Docker entirely, utilizing the 16-Core ANE and 38-Core GPU, slashing alignment time by 10x.

---

## 7. The AWS Long-Term Vision
Do not hardcode macOS-only logic in a way that breaks Linux compatibility. 
By creating a "Dual-Mode" `AlignRunner` (Native vs. Docker), you are actually building the exact adapter pattern we need for AWS. 
When we move to AWS (e.g., an EC2 `g4dn` instance with an NVIDIA GPU):
*   The system will detect Linux and fallback to Docker or a Native CUDA execution path.
*   The runner abstraction will effortlessly swap `darwin-arm64-coreml` commands for AWS `linux-x64-cuda` commands.

Keep the pipeline modular. Optimize aggressively for the M2's hardware right now, but maintain the architectural boundaries that make this system cloud-ready. 

Good luck with the 1,500 DTB production run.
