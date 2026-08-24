import logging
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

class AlignRunner:
    """
    Runner for executing `@storyteller-platform/align` CLI inside a transient node:alpine container.
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
        Executes the forced alignment using node:alpine docker container.
        """
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Map host paths to container /data mounted paths
        data_dir = self.project_root / "data"

        def to_container_path(p: Path) -> str:
            try:
                rel = p.resolve().relative_to(data_dir.resolve())
                return f"/data/{rel}"
            except ValueError:
                raise ValueError(f"Path {p} must be located inside project data directory {data_dir}")
        # Check if source EPUB is legacy EPUB 2; if so, upgrade it to EPUB 3 before aligning
        from src.epub_upgrader import is_epub2, upgrade_epub2_to_epub3
        actual_epub_path = epub_path
        if is_epub2(epub_path):
            upgraded_epub = output_path.parent / f"upgraded_{epub_path.name}"
            logger.info(f"Detected EPUB 2 publication: '{epub_path.name}'. Automatically upgrading to EPUB 3 standard...")
            actual_epub_path = upgrade_epub2_to_epub3(epub_path, upgraded_epub)

        container_epub = to_container_path(actual_epub_path)
        container_audiobook = to_container_path(audiobook_dir)
        container_output = to_container_path(output_path)

        import shlex
        npx_args = [
            "npx", "--yes", "@storyteller-platform/align",
            "--epub", container_epub,
            "--audiobook", container_audiobook,
            "--output", container_output,
            "--engine", engine,
            "--model", model,
            "--log-level", log_level
        ]
        escaped_npx_args = " ".join(shlex.quote(arg) for arg in npx_args)

        prod_id = output_path.name.split("_")[0]
        cmd = [
            "docker", "run", "--rm",
            "--name", f"align_{prod_id}",
            "-v", f"{data_dir.resolve()}:/data",
            "node:slim",
            "sh", "-c", f"apt-get update && apt-get install -y --no-install-recommends ffmpeg && {escaped_npx_args}"
        ]

        logger.info(f"Running transient docker aligner: {' '.join(cmd)}")
        
        # Run command and capture output
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # Print output in real-time
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                print(f"[ALIGNER] {line.strip()}")
                
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(f"Alignment failed with exit code {process.returncode}")

        # Clean up temporary upgraded EPUB if one was created
        if actual_epub_path != epub_path and actual_epub_path.exists():
            actual_epub_path.unlink(missing_ok=True)

        # Post-condition verification: Ensure aligned EPUB output was actually created
        if not output_path.exists():
            raise RuntimeError(f"Alignment failed: Aligned EPUB output file was not created at {output_path}")

        logger.info("Alignment finished successfully.")
