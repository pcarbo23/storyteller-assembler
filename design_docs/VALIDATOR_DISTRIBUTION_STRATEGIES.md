# NLS Validator (`AllVal.jar`) Distribution Strategies for Fresh Clones

## Overview

The NLS Compliance Validator Suite (`AllVal.jar`, incorporating `ZedVal` and `NlsVal2`) is a proprietary binary asset owned by the National Library Service for the Blind and Print Disabled (NLS), Library of Congress. Because of intellectual property and licensing restrictions, the JAR file cannot be committed into public or semi-public version control repositories.

Currently, `storyteller-assembler` relies on the `NLS_VALIDATOR_JAR` environment variable:
- If `NLS_VALIDATOR_JAR` points to a valid local JAR, `ZedVal` and `NlsVal2` compliance verification executes automatically, outputting XML and log reports to `data/reports/`.
- If `NLS_VALIDATOR_JAR` is unset or points to a non-existent file, validation is safely bypassed, logging a warning and marking validation as `"skipped"` in `data/production_history.db` without failing the pipeline.

When onboarding new workstations, CI/CD pipelines, or deployment targets, an automated provisioning strategy will be desirable. This document captures four candidate strategies for future implementation.

---

## Strategy 1: Authenticated Cloud Storage Download (`setup_validators.sh`)

### Concept
Host the authorized `AllVal.jar` binary (and any accompanying calibration assets) in an access-controlled cloud object bucket (e.g., AWS S3, Google Cloud Storage, or an internal HTTP artifact repository). Provide a pre-flight bootstrapping script that fetches the binary onto the local host if missing.

### Workflow
1. A setup script (e.g., `scripts/setup_validators.sh` or a hook in virtual environment creation) checks if `NLS_VALIDATOR_JAR` exists.
2. If absent, the script uses the operator's existing cloud credentials (`aws s3 cp` or `gcloud storage cp` or signed HTTPS URL with short-lived tokens):
   ```bash
   mkdir -p ~/validators
   aws s3 cp s3://nls-internal-tools/validators/AllVal.jar ~/validators/AllVal.jar
   export NLS_VALIDATOR_JAR="$HOME/validators/AllVal.jar"
   ```
3. The script verifies the SHA-256 checksum of the downloaded file against a pinned hash stored in `config/validator_manifest.json` before enabling execution.

### Advantages
- Minimal repository footprint; zero binary artifacts in Git.
- Leverages existing organizational IAM roles and access controls (AWS IAM, GCP IAM).
- Easy to rotate or update `AllVal.jar` versions globally by updating the S3 object and version manifest.

### Considerations
- Requires operators/agents to have cloud credentials configured prior to running the setup script.
- Cannot run fully offline without a local cache.

---

## Strategy 2: Private Git Submodule / Separate Repository Dependency

### Concept
Maintain proprietary binaries and NLS-internal test suites in a separate, access-restricted GitHub/GitLab repository (e.g., `git@github.com:nlsbpd/nls-proprietary-tools.git`). Reference it from `storyteller-assembler` as an optional Git submodule.

### Workflow
1. The repository includes an optional submodule configured at `tools/validators`:
   ```bash
   git submodule add git@github.com:nlsbpd/nls-proprietary-tools.git tools/validators
   ```
2. Authorized operators clone with submodules or initialize on-demand:
   ```bash
   git submodule update --init --recursive
   ```
3. If an unauthorized user or public fork clones without access, the submodule directory remains empty, triggering the fallback behavior (`skipped` status).

### Advantages
- Native Git-based versioning and change tracking.
- Cryptographic commit pinning ensures exact validator versions are tied to assembler releases.
- Native support in CI/CD environments with deploy keys or personal access tokens.

### Considerations
- Bloats Git repository history over time as binaries are revised (unless Git LFS is utilized).
- Operators without repository access will encounter submodule initialization prompts or warnings unless marked optional.

---

## Strategy 3: Containerized / Volume-Mounted Validator Infrastructure

### Concept
Encapsulate the Java runtime and `AllVal.jar` into a private, pre-configured container image (e.g., hosted on AWS ECR or GitHub Container Registry `ghcr.io/nlsbpd/allval:4.08`), similar to how `@storyteller-platform/align` runs via a transient Docker container.

### Workflow
1. `src/align_runner.py` pattern is replicated for validation:
   ```python
   docker run --rm \
     -v "/path/to/dbXXXXXX.dtb:/workspace/dtb" \
     -v "/path/to/data/reports:/workspace/reports" \
     nls-allval:4.08 \
     ZedVal /workspace/dtb/dbXXXXXX.opf
   ```
2. The host machine does not require Java JRE or local `AllVal.jar` binaries installed; only Docker Engine is required.
3. For local host runs, a volume mount can pass host-cached JAR files into the container.

### Advantages
- Completely eliminates host Java JRE dependencies (matches the zero-host-node philosophy of Docker align).
- Perfect reproducibility across macOS, Linux, and Windows WSL2 environments.
- Consistent Java version, JVM heap flags, and locale settings.

### Considerations
- Slightly higher process invocation overhead (container spinning up for ~1-2 seconds per book).
- Requires Docker daemon access and private registry authentication.

---

## Strategy 4: Guided Host Environment Setup Script (`setup_env.sh`)

### Concept
An interactive, automated onboarding script included in the repository that walks new developers or operators through local configuration during initial project setup.

### Workflow
1. The developer executes `./scripts/setup_env.sh` after cloning.
2. The script audits the machine for prerequisites:
   - Python version & virtualenv
   - Docker daemon availability
   - Homebrew / system libraries (`ffmpeg`, `espeak-ng`, `openjdk`)
   - `NLS_VALIDATOR_JAR` variable
3. If `NLS_VALIDATOR_JAR` is not detected:
   - The script prompts: *"Enter the full filesystem path to your local AllVal.jar (or press Enter to skip):"*
   - Tests the user-provided path with `java -cp <path> ZedVal -v` to ensure valid execution and report validator version.
   - Automatically appends `export NLS_VALIDATOR_JAR="..."` to the user's active shell profile (`~/.zshrc` or `~/.bashrc`).

### Advantages
- Simple, transparent, and completely decoupled from cloud storage or private repository infrastructure.
- Immediately informs operators of missing dependencies before they attempt production runs.
- Works offline and in air-gapped environments.

### Considerations
- Requires manual operator interaction during initial workstation setup.
- Does not automatically download the file; the operator must possess `AllVal.jar` locally.

---

## Architectural Comparison Matrix

| Strategy | Auto-Download? | Secret / Credential Required? | Eliminates Host Java? | Offline Friendly? | Best Suited For |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **1. Cloud Storage (S3/GCS)** | Yes | Yes (Cloud IAM) | No | No (after initial fetch: Yes) | Cloud CI/CD & Automated Dev Workstations |
| **2. Private Git Submodule** | Yes | Yes (SSH/Git Deploy Key) | No | Yes | Organizations with unified GitHub/GitLab orgs |
| **3. Containerized Image** | Yes | Yes (Container Registry Auth) | **Yes** | Yes (cached image) | Heterogeneous OS environments & Docker-first pipelines |
| **4. Guided Setup Script** | No | No | No | **Yes** | Standalone developer laptops & air-gapped workstations |

---

## Current Status & Next Actions

- **Current State**: `NLS_VALIDATOR_JAR` environment variable with graceful degradation (`skipped` status when missing).
- **Target Trigger**: When multi-developer scaling, remote AWS EC2 deployment, or automated GitHub Actions CI/CD pipelines are commissioned, evaluate and implement Strategy 1 or Strategy 3.
