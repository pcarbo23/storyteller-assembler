# Technical Implementation Plan & Architectural History

This document serves as both the implementation plan for the containerized CLI forced alignment strategy and a historical record of the architectural approaches attempted, detailing why previous designs were rejected or failed.

---

## Part 1: Architectural History & Rejections

### Attempt 1: Next.js API Server Model (API-v1 / API-v2)
* **Design**: Interacting with the self-hosted Storyteller Next.js server container over HTTP REST endpoints (`/api/books` and `/api/v2/books`).
* **Why it was a Deadend/Failure**:
  * **NextAuth Authentication**: The latest Storyteller images migrated to Next.js 15, which enforces strict session cookies, CSRF tokens, and user database permission layers (Auth.js/NextAuth). Programmatically logging in and obtaining tokens from a headless Python pipeline is extremely fragile.
  * **TUS Resumable Uploads**: Storyteller replaced standard HTTP uploads with the TUS protocol. Managing multi-step chunked uploads via TUS in Python added significant complexity and overhead.
  * **Lack of API Stability**: The HTTP routes are treated as internal browser-facing APIs by the maintainers. They change frequently between minor version updates, constantly breaking client-side integrations.
  * **Resource Exhaustion (OOM)**: Running a continuous Next.js 15 server container alongside SQLite/database migrations consumes substantial memory, leading to container exit status `137` (OOM Killer) on resource-limited sandboxes.

### Attempt 2: Local Aligner CLI on Host macOS
* **Design**: Running `npx @storyteller-platform/align` directly on the macOS host command line.
* **Why it was a Deadend/Failure**:
  * **Host Dependency Mismatch**: The user's host macOS system does not have Node.js or npm installed (`npx: command not found`). Requiring local Node.js installations on the sandbox host violates the portability constraint of the project.

### Attempt 3: Custom Node/Python Pipeline Image Build
* **Design**: Modifying the project's `Dockerfile` to install Node.js and the `@storyteller-platform/align` CLI, building a unified `auto_story_pipeline` image.
* **Why it was a Deadend/Failure**:
  * **Host Resource Depletion (Crashes)**: Compiling and installing Node/Debian packages during `docker build` is CPU/RAM intensive. Running the build on the sandboxed Mac host exhausted the system memory, repeatedly crashing the agent environment.

---

## Part 2: Approved Strategy: Transient `node:alpine` CLI Container

This strategy uses the official, pre-built **`node:alpine`** Docker image to run the aligner CLI as a transient (one-off) task.

### 1. Architectural Details
* **Zero Baseline Memory**: No Storyteller Next.js server container runs in the background. The server is deleted from `docker-compose.yml`.
* **Zero Host Builds**: We do not run any `docker build` commands. The Python daemon uses the official, pre-compiled `node:alpine` image.
* **Transient Execution**: When a book is detected, the Python watcher triggers a transient container that aligns the files on disk and shuts down immediately:
  ```bash
  docker run --rm -v "$(pwd)/data:/data" node:alpine npx --yes @storyteller-platform/align \
    --output /data/processing/{prod_id}_aligned.epub \
    --audiobook /data/ingest/{audio_folder} \
    --epub /data/ingest/{epub_file} \
    --engine whisper.cpp \
    --model tiny.en
  ```
* **Memory Safety**: Alpine containers consume minimal memory (~50MB) and release all resources back to the host system on exit.

---

## Part 3: Proposed Changes

### [Docker Environment]
#### [MODIFY] [docker-compose.yml](file:///Users/carbo/PycharmProjects/auto_story_pipe/docker-compose.yml)
* Delete the `storyteller` service and `storyteller_data` volume.
* Retain only the base `pipeline` definition.

---

### [Alignment Integration]
#### [NEW] [align_runner.py](file:///Users/carbo/PycharmProjects/auto_story_pipe/src/align_runner.py)
* A python script executing the `node:alpine` transient docker runner.
* Translates host paths to container-mounted `/data/` paths.
* Pipes execution logs for Streamlit dashboard rendering.

#### [DELETE] [storyteller_client.py](file:///Users/carbo/PycharmProjects/auto_story_pipe/src/storyteller_client.py)
* Remove the obsolete Next.js server client.

---

### [Ingestion Watcher]
#### [MODIFY] [run_ingest_watcher.py](file:///Users/carbo/PycharmProjects/auto_story_pipe/scripts/run_ingest_watcher.py)
* Replace Storyteller server checks and upload steps with a single call to `align_runner.py`.

---

## Part 4: Verification Plan
* Run `pytest` to ensure zero breakages in DTB packaging and validation.
* Ingest `A Mouthful of Dust` to verify the transient docker aligner executes successfully and generates compliance validation reports.
