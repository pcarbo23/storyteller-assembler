"""
Unit tests for AlignRunner (src/align_runner.py).
"""

import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.align_runner import AlignRunner, is_aligner_image_available, build_aligner_image, ensure_aligner_image


class TestAlignRunner(unittest.TestCase):

    def setUp(self):
        self.project_root = Path(__file__).resolve().parent.parent
        self.runner = AlignRunner(self.project_root)

    @patch("src.align_runner.subprocess.run")
    def test_is_aligner_image_available_true(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(is_aligner_image_available("auto_story_pipe_aligner:latest"))

    @patch("src.align_runner.subprocess.run")
    def test_is_aligner_image_available_false(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        self.assertFalse(is_aligner_image_available("nonexistent_image"))

    @patch("src.align_runner.is_aligner_image_available")
    def test_ensure_aligner_image_when_available(self, mock_avail):
        mock_avail.return_value = True
        img = ensure_aligner_image(self.project_root)
        self.assertEqual(img, "auto_story_pipe_aligner:latest")

    @patch("src.align_runner.ensure_aligner_image")
    @patch("src.align_runner.subprocess.Popen")
    def test_align_exit_code_137_raises_descriptive_error(self, mock_popen, mock_ensure_img):
        mock_ensure_img.return_value = "auto_story_pipe_aligner:latest"
        mock_process = MagicMock()
        mock_process.stdout = iter(["[Aligner output line]"])
        mock_process.wait.return_value = None
        mock_process.returncode = 137
        mock_popen.return_value = mock_process

        epub = self.project_root / "data" / "test.epub"
        audio_dir = self.project_root / "data" / "audio"
        out_epub = self.project_root / "data" / "processing" / "test_aligned.epub"

        with self.assertRaises(RuntimeError) as ctx:
            self.runner.align(epub, audio_dir, out_epub)

        self.assertIn("137", str(ctx.exception))
        self.assertIn("Out of Memory", str(ctx.exception))

    @patch("src.align_runner.ensure_aligner_image")
    @patch("src.align_runner.subprocess.Popen")
    def test_align_default_ctc_command_construction(self, mock_popen, mock_ensure_img):
        mock_ensure_img.return_value = "auto_story_pipe_aligner:latest"
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = None
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        epub = self.project_root / "data" / "test.epub"
        audio_dir = self.project_root / "data" / "audio"
        out_epub = self.project_root / "data" / "processing" / "test_aligned.epub"

        with patch.object(Path, "exists", return_value=True), patch("sys.platform", "linux"):
            self.runner.align(epub, audio_dir, out_epub)

        cmd = mock_popen.call_args[0][0]
        image_idx = cmd.index("auto_story_pipe_aligner:latest")
        container_args = cmd[image_idx + 1:]

        self.assertIn("--ctc", container_args)
        self.assertIn("--model", container_args)
        self.assertEqual(container_args[container_args.index("--model") + 1], "quartznet15x5")
        self.assertIn("--language", container_args)
        self.assertEqual(container_args[container_args.index("--language") + 1], "en")
        self.assertIn("--device", container_args)
        self.assertEqual(container_args[container_args.index("--device") + 1], "auto")
        # Ensure Whisper-only flags are omitted when --ctc is active
        self.assertNotIn("-e", container_args)
        self.assertNotIn("-m", container_args)
        self.assertNotIn("whisper.cpp", container_args)

    @patch("src.align_runner.subprocess.Popen")
    @patch("src.align_runner.shutil.which", side_effect=lambda name: "/opt/homebrew/bin/align" if name == "align" else None)
    def test_align_native_ctc_quartznet_with_options(self, mock_which, mock_popen):
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = None
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        epub = self.project_root / "data" / "test.epub"
        audio_dir = self.project_root / "data" / "audio"
        out_epub = self.project_root / "data" / "processing" / "test_aligned.epub"
        emissions_dir = self.project_root / "data" / "processing" / "emissions"

        with patch.object(Path, "exists", return_value=True), patch.object(Path, "mkdir"), patch("sys.platform", "darwin"):
            self.runner.align(
                epub,
                audio_dir,
                out_epub,
                ctc=True,
                model="quartznet15x5",
                device="mlx",
                language="en",
                gap_seconds=3.5,
                emissions_dir=emissions_dir,
            )

        cmd = mock_popen.call_args[0][0]
        self.assertEqual(cmd[0], "align")
        self.assertIn("--ctc", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "quartznet15x5")
        self.assertEqual(cmd[cmd.index("--device") + 1], "mlx")
        self.assertEqual(cmd[cmd.index("--language") + 1], "en")
        self.assertEqual(cmd[cmd.index("--gap-seconds") + 1], "3.5")
        self.assertEqual(cmd[cmd.index("--emissions") + 1], str(emissions_dir.resolve()))
        self.assertNotIn("-e", cmd)
        self.assertNotIn("-m", cmd)

    @patch("src.align_runner.ensure_aligner_image")
    @patch("src.align_runner.subprocess.Popen")
    def test_align_command_construction(self, mock_popen, mock_ensure_img):
        mock_ensure_img.return_value = "auto_story_pipe_aligner:latest"
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = None
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        epub = self.project_root / "data" / "test.epub"
        audio_dir = self.project_root / "data" / "audio"
        out_epub = self.project_root / "data" / "processing" / "test_aligned.epub"

        # Mock out_epub.exists() so post-condition check passes
        with patch.object(Path, "exists", return_value=True), patch("sys.platform", "linux"):
            self.runner.align(epub, audio_dir, out_epub, engine="whisper.cpp", model="tiny.en")

        cmd = mock_popen.call_args[0][0]
        image_idx = cmd.index("auto_story_pipe_aligner:latest")
        container_args = cmd[image_idx + 1:]

        # Verify 'align' subcommand is NOT in the container arguments
        self.assertNotIn("align", container_args)
        # Verify -e whisper.cpp and -m tiny.en are passed to the container
        self.assertIn("-e", container_args)
        self.assertEqual(container_args[container_args.index("-e") + 1], "whisper.cpp")
        self.assertIn("-m", container_args)
        self.assertEqual(container_args[container_args.index("-m") + 1], "tiny.en")


if __name__ == "__main__":
    unittest.main()
