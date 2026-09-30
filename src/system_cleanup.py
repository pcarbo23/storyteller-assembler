"""
System & Memory Cleanup Utilities for Storyteller Assembler.
Provides Docker hypervisor VM cache dropping, container pruning, and Python garbage collection.
"""

import gc
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def flush_docker_vm_cache(container_image: str = "node:alpine") -> bool:
    """
    Instructs the Docker LinuxKit hypervisor VM kernel to flush filesystem page caches,
    dentries, and inodes back to available RAM via /proc/sys/vm/drop_caches.
    """
    cmd = [
        "docker", "run", "--rm", "--privileged",
        "-e", "HTTP_PROXY=", "-e", "HTTPS_PROXY=",
        "-e", "http_proxy=", "-e", "https_proxy=",
        container_image,
        "sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            logger.info("Successfully dropped Docker VM page cache and inode buffers.")
            return True
        else:
            logger.debug(f"Docker cache flush returned code {res.returncode}: {res.stderr.strip()}")
            return False
    except Exception as e:
        logger.debug(f"Docker VM memory flush skipped or timed out: {e}")
        return False


def prune_docker_resources() -> bool:
    """
    Removes stopped containers and dangling build artifacts to prevent disk/memory leaks.
    """
    try:
        subprocess.run(["docker", "container", "prune", "-f"], capture_output=True, text=True, timeout=10)
        return True
    except Exception as e:
        logger.debug(f"Docker container prune skipped: {e}")
        return False


def cleanup_python_memory() -> int:
    """
    Forces Python garbage collection and attempts to release PyTorch / TTS memory.
    """
    collected = gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass
    return collected


def reset_pipeline_environment(container_image: str = "node:alpine") -> None:
    """
    Executes a complete system sanitation pass: Python GC, Docker VM cache drop, and container pruning.
    """
    logger.debug("Executing system and Docker VM memory cleanup...")
    cleanup_python_memory()
    flush_docker_vm_cache(container_image=container_image)
    prune_docker_resources()
