import logging
import subprocess
import shutil
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

ALIGNER_IMAGE = "auto_story_pipe_aligner:latest"
FALLBACK_BASE_IMAGE = "registry.gitlab.com/storyteller-platform/storyteller:latest"


def is_aligner_image_available(image_name: str = ALIGNER_IMAGE) -> bool:
    """Check if the dedicated aligner Docker image is built and available locally."""
    try:
        res = subprocess.run(
            ["docker", "image", "inspect", image_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        return res.returncode == 0
    except Exception:
        return False


def build_aligner_image(project_root: Path, dockerfile_path: Optional[Path] = None) -> bool:
    """Build the dedicated auto_story_pipe_aligner Docker image."""
    root = Path(project_root)
    df = dockerfile_path or (root / "docker" / "Dockerfile.aligner")
    if not df.exists():
        logger.warning(f"Dockerfile not found at {df}; cannot build aligner image.")
        return False

    logger.info(f"Building dedicated aligner Docker image '{ALIGNER_IMAGE}' from {df.name}...")
    try:
        cmd = ["docker", "build", "-t", ALIGNER_IMAGE, "-f", str(df), str(root)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if res.returncode == 0:
            logger.info(f"Successfully built '{ALIGNER_IMAGE}'.")
            return True
        else:
            logger.error(f"Failed to build aligner image: {res.stderr}")
            return False
    except Exception as e:
        logger.error(f"Exception during aligner image build: {e}")
        return False


def ensure_aligner_image(project_root: Path) -> str:
    """Ensure the aligner image is ready; builds it if missing, or falls back gracefully."""
    if is_aligner_image_available(ALIGNER_IMAGE):
        return ALIGNER_IMAGE

    logger.info(f"Dedicated aligner image '{ALIGNER_IMAGE}' not found locally. Triggering automated build...")
    success = build_aligner_image(project_root)
    if success:
        return ALIGNER_IMAGE

    logger.warning(f"Could not build '{ALIGNER_IMAGE}'. Falling back to '{FALLBACK_BASE_IMAGE}'.")
    return FALLBACK_BASE_IMAGE


class AlignRunner:
    """
    Runner for executing `@storyteller-platform/align` CLI inside a dedicated, pre-built Docker container.
    """
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)

    def align(
        self,
        epub_path: Path,
        audiobook_dir: Path,
        output_path: Path,
        engine: str = "whisper.cpp",
        model: str = "tiny.en",
        log_level: str = "info"
    ) -> None:
        """
        Executes forced alignment using either native node (on macOS) or Docker (fallback).
        """
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if source EPUB is legacy EPUB 2; if so, upgrade it to EPUB 3 before aligning
        from src.epub_upgrader import is_epub2, upgrade_epub2_to_epub3
        actual_epub_path = epub_path
        if is_epub2(epub_path):
            upgraded_epub = output_path.parent / f"upgraded_{epub_path.name}"
            logger.info(f"Detected EPUB 2 publication: '{epub_path.name}'. Automatically upgrading to EPUB 3 standard...")
            actual_epub_path = upgrade_epub2_to_epub3(epub_path, upgraded_epub)

        is_macos = sys.platform == 'darwin'
        has_npx = shutil.which('npx') is not None
        has_align = shutil.which('align') is not None

        if is_macos and (has_npx or has_align):
            logger.info("Running natively on macOS to leverage hardware acceleration.")
            self._align_native(actual_epub_path, audiobook_dir, output_path, engine, model, log_level)
        else:
            logger.info("Running via Docker fallback.")
            self._align_docker(actual_epub_path, audiobook_dir, output_path, engine, model, log_level)

        # Clean up temporary upgraded EPUB if one was created
        if actual_epub_path != epub_path and actual_epub_path.exists():
            actual_epub_path.unlink(missing_ok=True)

        # Post-condition verification: Ensure aligned EPUB output was actually created
        if not output_path.exists():
            raise RuntimeError(f"Alignment failed: Aligned EPUB output file was not created at {output_path}")

        logger.info("Alignment finished successfully.")

    def _align_native(
        self,
        epub_path: Path,
        audiobook_dir: Path,
        output_path: Path,
        engine: str,
        model: str,
        log_level: str
    ) -> None:
        engine_args = ["--ctc"] if engine == "ctc" else ["-e", engine]
        
        # Use globally installed align if available, else npx
        base_cmd = ["align"] if shutil.which("align") else ["npx", "--no-install", "@storyteller-platform/align"]
        
        cmd = base_cmd + [
            "--epub", str(epub_path.resolve()),
            "--audiobook", str(audiobook_dir.resolve()),
            "--output", str(output_path.resolve()),
            *engine_args,
            "-m", model,
            "--log-level", log_level
        ]

        logger.info(f"Running native macOS aligner: {' '.join(cmd)}")
        self._run_process(cmd)

    def _align_docker(
        self,
        epub_path: Path,
        audiobook_dir: Path,
        output_path: Path,
        engine: str,
        model: str,
        log_level: str
    ) -> None:
        data_dir = self.project_root / "data"

        def to_container_path(p: Path) -> str:
            try:
                rel = p.resolve().relative_to(data_dir.resolve())
                return f"/data/{rel}"
            except ValueError:
                raise ValueError(f"Path {p} must be located inside project data directory {data_dir}")

        container_epub = to_container_path(epub_path)
        container_audiobook = to_container_path(audiobook_dir)
        container_output = to_container_path(output_path)

        # Ensure container image is available
        image_name = ensure_aligner_image(self.project_root)

        prod_id = output_path.name.split("_")[0]
        engine_args = ["--ctc"] if engine == "ctc" else ["-e", engine]
        cmd = [
            "docker", "run", "--rm",
            "--name", f"align_{prod_id}",
            "-v", f"{data_dir.resolve()}:/data",
            "-e", "HTTP_PROXY=",
            "-e", "HTTPS_PROXY=",
            "-e", "http_proxy=",
            "-e", "https_proxy=",
            image_name,
            "--epub", container_epub,
            "--audiobook", container_audiobook,
            "--output", container_output,
            *engine_args,
            "-m", model,
            "--log-level", log_level
        ]

        logger.info(f"Running dedicated docker aligner ({image_name}): {' '.join(cmd)}")
        self._run_process(cmd)

    def _run_process(self, cmd: List[str]) -> None:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        if process.stdout:
            if hasattr(process.stdout, "readline"):
                for line in iter(process.stdout.readline, ""):
                    print(f"[ALIGNER] {line.strip()}", flush=True)
            else:
                for line in process.stdout:
                    print(f"[ALIGNER] {line.strip()}", flush=True)
                
        process.wait()
        if process.returncode != 0:
            if process.returncode == 137:
                raise RuntimeError(
                    f"Alignment failed with exit code 137 (Out of Memory / SIGKILL). "
                    f"The memory limit was reached during model alignment. "
                )
            elif process.returncode == 100:
                raise RuntimeError(
                    f"Alignment failed with exit code 100 (Package manager / network failure)."
                )
            else:
                raise RuntimeError(f"Alignment failed with exit code {process.returncode}")
