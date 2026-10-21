import argparse
import logging
import subprocess
import shutil
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

ALIGNER_IMAGE = "auto_story_pipe_aligner:latest"
FALLBACK_BASE_IMAGE = "registry.gitlab.com/storyteller-platform/storyteller:latest"

VALID_CTC_MODELS = ("mms", "quartznet15x5", "citrinet256", "citrinet512", "citrinet1024")
VALID_CTC_DEVICES = ("auto", "cpu", "webgpu", "dml", "cuda", "mlx")
LANGUAGE_REQUIRED_CTC_MODELS = ("quartznet15x5", "citrinet256", "citrinet512", "citrinet1024")


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
    Runner for executing `@storyteller-platform/align` CLI natively on macOS (Apple Silicon MLX)
    or inside a dedicated, pre-built Docker container.
    """
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)

    def _build_pipeline_flags(
        self,
        ctc: bool = True,
        engine: Optional[str] = None,
        model: str = "quartznet15x5",
        device: str = "auto",
        language: Optional[str] = "en",
        gap_seconds: Optional[float] = None,
        emissions_path: Optional[str] = None,
        audio_chapter_seconds: Optional[float] = None,
        drop_unread: bool = False,
        granularity: Optional[str] = None,
        log_level: str = "info",
    ) -> List[str]:
        """Construct the mode-specific CLI arguments for `@storyteller-platform/align`."""
        use_ctc = ctc and (engine in (None, "ctc", "ctc-local"))
        flags: List[str] = []

        if use_ctc:
            flags.append("--ctc")
            ctc_model = model
            if ctc_model not in VALID_CTC_MODELS:
                logger.warning(
                    f"Model '{ctc_model}' is not a valid CTC model {VALID_CTC_MODELS}; defaulting to 'quartznet15x5'."
                )
                ctc_model = "quartznet15x5"
            flags.extend(["--model", ctc_model])

            if device:
                flags.extend(["--device", device])

            effective_language = language
            if ctc_model in LANGUAGE_REQUIRED_CTC_MODELS and not effective_language:
                effective_language = "en"
                logger.info(f"CTC model '{ctc_model}' requires --language; defaulting to '{effective_language}'.")

            if effective_language:
                flags.extend(["--language", effective_language])

            if emissions_path:
                flags.extend(["--emissions", emissions_path])
        else:
            whisper_engine = engine if (engine and engine not in ("ctc", "ctc-local")) else "whisper.cpp"
            whisper_model = "tiny.en" if model in VALID_CTC_MODELS else model
            flags.extend(["-e", whisper_engine, "-m", whisper_model])
            if language:
                flags.extend(["--language", language])

        if gap_seconds is not None:
            flags.extend(["--gap-seconds", str(gap_seconds)])

        if audio_chapter_seconds is not None:
            flags.extend(["--audio-chapter-seconds", str(audio_chapter_seconds)])

        if drop_unread:
            flags.append("--drop-unread")

        if granularity:
            flags.extend(["--granularity", granularity])

        flags.extend(["--log-level", log_level])
        return flags

    def align(
        self,
        epub_path: Path,
        audiobook_dir: Path,
        output_path: Path,
        ctc: bool = True,
        engine: Optional[str] = None,
        model: str = "quartznet15x5",
        device: str = "auto",
        language: Optional[str] = "en",
        gap_seconds: Optional[float] = None,
        emissions_dir: Optional[Path] = None,
        audio_chapter_seconds: Optional[float] = None,
        drop_unread: bool = False,
        granularity: Optional[str] = None,
        log_level: str = "info"
    ) -> None:
        """
        Executes forced alignment using either native node (on macOS) or Docker (fallback).
        Defaults to the CTC forced-alignment pipeline (`--ctc --model quartznet15x5 --language en --device auto`).
        """
        epub_path = Path(epub_path)
        audiobook_dir = Path(audiobook_dir)
        output_path = Path(output_path)
        if emissions_dir is not None:
            emissions_dir = Path(emissions_dir)

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
            self._align_native(
                actual_epub_path,
                audiobook_dir,
                output_path,
                ctc=ctc,
                engine=engine,
                model=model,
                device=device,
                language=language,
                gap_seconds=gap_seconds,
                emissions_dir=emissions_dir,
                audio_chapter_seconds=audio_chapter_seconds,
                drop_unread=drop_unread,
                granularity=granularity,
                log_level=log_level,
            )
        else:
            logger.info("Running via Docker fallback.")
            self._align_docker(
                actual_epub_path,
                audiobook_dir,
                output_path,
                ctc=ctc,
                engine=engine,
                model=model,
                device=device,
                language=language,
                gap_seconds=gap_seconds,
                emissions_dir=emissions_dir,
                audio_chapter_seconds=audio_chapter_seconds,
                drop_unread=drop_unread,
                granularity=granularity,
                log_level=log_level,
            )

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
        ctc: bool = True,
        engine: Optional[str] = None,
        model: str = "quartznet15x5",
        device: str = "auto",
        language: Optional[str] = "en",
        gap_seconds: Optional[float] = None,
        emissions_dir: Optional[Path] = None,
        audio_chapter_seconds: Optional[float] = None,
        drop_unread: bool = False,
        granularity: Optional[str] = None,
        log_level: str = "info"
    ) -> None:
        # Use globally installed align if available, else npx
        base_cmd = ["align"] if shutil.which("align") else ["npx", "--no-install", "@storyteller-platform/align"]

        emissions_path_str: Optional[str] = None
        if emissions_dir is not None:
            emissions_dir.mkdir(parents=True, exist_ok=True)
            emissions_path_str = str(emissions_dir.resolve())

        pipeline_flags = self._build_pipeline_flags(
            ctc=ctc,
            engine=engine,
            model=model,
            device=device,
            language=language,
            gap_seconds=gap_seconds,
            emissions_path=emissions_path_str,
            audio_chapter_seconds=audio_chapter_seconds,
            drop_unread=drop_unread,
            granularity=granularity,
            log_level=log_level,
        )

        cmd = base_cmd + [
            "--epub", str(epub_path.resolve()),
            "--audiobook", str(audiobook_dir.resolve()),
            "--output", str(output_path.resolve()),
            *pipeline_flags,
        ]

        logger.info(f"Running native macOS aligner: {' '.join(cmd)}")
        self._run_process(cmd)

    def _align_docker(
        self,
        epub_path: Path,
        audiobook_dir: Path,
        output_path: Path,
        ctc: bool = True,
        engine: Optional[str] = None,
        model: str = "quartznet15x5",
        device: str = "auto",
        language: Optional[str] = "en",
        gap_seconds: Optional[float] = None,
        emissions_dir: Optional[Path] = None,
        audio_chapter_seconds: Optional[float] = None,
        drop_unread: bool = False,
        granularity: Optional[str] = None,
        log_level: str = "info"
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
        container_emissions: Optional[str] = None
        if emissions_dir is not None:
            emissions_dir.mkdir(parents=True, exist_ok=True)
            container_emissions = to_container_path(emissions_dir)

        # Ensure container image is available
        image_name = ensure_aligner_image(self.project_root)

        prod_id = output_path.name.split("_")[0]
        pipeline_flags = self._build_pipeline_flags(
            ctc=ctc,
            engine=engine,
            model=model,
            device=device,
            language=language,
            gap_seconds=gap_seconds,
            emissions_path=container_emissions,
            audio_chapter_seconds=audio_chapter_seconds,
            drop_unread=drop_unread,
            granularity=granularity,
            log_level=log_level,
        )

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
            *pipeline_flags,
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute @storyteller-platform/align with CTC forced alignment (default) or Whisper fallback."
    )
    parser.add_argument("--epub", required=True, type=Path, help="Path to input EPUB file.")
    parser.add_argument("--audiobook", required=True, type=Path, help="Path to directory of audiobook tracks.")
    parser.add_argument("--output", required=True, type=Path, help="Path for output aligned EPUB.")
    parser.add_argument(
        "--ctc",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use CTC forced alignment pipeline (enabled by default; pass --no-ctc for Whisper).",
    )
    parser.add_argument(
        "--engine",
        default=None,
        help="Transcription engine when not using CTC (e.g., whisper.cpp).",
    )
    parser.add_argument(
        "--model",
        "-m",
        default="quartznet15x5",
        help=f"CTC model family {VALID_CTC_MODELS} (default: quartznet15x5) or Whisper model when --no-ctc is set.",
    )
    parser.add_argument(
        "--device",
        "-d",
        default="auto",
        choices=VALID_CTC_DEVICES,
        help="Inference device for CTC model (default: auto; resolves to mlx on Apple Silicon).",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="BCP 47 language code (default: en); required for quartznet15x5 and citrinet* models.",
    )
    parser.add_argument(
        "--gap-seconds",
        type=float,
        default=None,
        help="Stretches of audio longer than this without matching text become audio-only media overlay entries.",
    )
    parser.add_argument(
        "--emissions",
        type=Path,
        default=None,
        help="Optional directory path to cache/reuse CTC emission files.",
    )
    parser.add_argument(
        "--audio-chapter-seconds",
        type=float,
        default=None,
        help="Audio-only stretches between chapters at least this long become their own chapters.",
    )
    parser.add_argument(
        "--drop-unread",
        action="store_true",
        default=False,
        help="Give sentences the narrator did not read no audio instead of an interpolated clip.",
    )
    parser.add_argument(
        "--granularity",
        "-g",
        choices=("sentence", "word"),
        default=None,
        help="Alignment granularity (sentence or word).",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=("silent", "debug", "info", "warn", "error"),
        help="Log level for align CLI (default: info).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parent.parent
    runner = AlignRunner(project_root)
    runner.align(
        epub_path=args.epub,
        audiobook_dir=args.audiobook,
        output_path=args.output,
        ctc=args.ctc,
        engine=args.engine,
        model=args.model,
        device=args.device,
        language=args.language,
        gap_seconds=args.gap_seconds,
        emissions_dir=args.emissions,
        audio_chapter_seconds=args.audio_chapter_seconds,
        drop_unread=args.drop_unread,
        granularity=args.granularity,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
