"""
Tests for system & memory cleanup utilities (src/system_cleanup.py).
"""

import unittest
from unittest.mock import patch, MagicMock
from src.system_cleanup import flush_docker_vm_cache, prune_docker_resources, cleanup_python_memory, reset_pipeline_environment


class TestSystemCleanup(unittest.TestCase):

    @patch("src.system_cleanup.subprocess.run")
    def test_flush_docker_vm_cache_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = flush_docker_vm_cache(container_image="node:alpine")
        self.assertTrue(result)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("drop_caches", " ".join(cmd))
        self.assertIn("--privileged", cmd)

    @patch("src.system_cleanup.subprocess.run")
    def test_flush_docker_vm_cache_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        result = flush_docker_vm_cache(container_image="node:alpine")
        self.assertFalse(result)

    @patch("src.system_cleanup.subprocess.run")
    def test_prune_docker_resources(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = prune_docker_resources()
        self.assertTrue(result)
        mock_run.assert_called_once_with(["docker", "container", "prune", "-f"], capture_output=True, text=True, timeout=10)

    def test_cleanup_python_memory(self):
        collected = cleanup_python_memory()
        self.assertIsInstance(collected, int)

    @patch("src.system_cleanup.flush_docker_vm_cache")
    @patch("src.system_cleanup.prune_docker_resources")
    @patch("src.system_cleanup.cleanup_python_memory")
    def test_reset_pipeline_environment(self, mock_clean_py, mock_prune, mock_flush):
        reset_pipeline_environment(container_image="node:alpine")
        mock_clean_py.assert_called_once()
        mock_flush.assert_called_once_with(container_image="node:alpine")
        mock_prune.assert_called_once()


if __name__ == "__main__":
    unittest.main()
