#!/usr/bin/env python3
"""
Passive E2E Debug Tracker & Recursion Forensic Monitor.
Runs continuously in the background while the user operates the Streamlit dashboard
and Ingestion Watcher. Real-time monitors process memory, logs, job lifecycles, and
captures any RecursionError or pipeline failure with full stack traces into forensic_report.json.
"""

import os
import sys
import time
import json
import signal
import logging
import argparse
import threading
import psutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Debug directories and files
DEBUG_DIR = PROJECT_ROOT / "data" / "debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

TRACKER_LOG = DEBUG_DIR / "debug_tracker.log"
REPORT_JSON = DEBUG_DIR / "forensic_report.json"
WATCHER_LOG = PROJECT_ROOT / "data" / "watcher_daemon.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(TRACKER_LOG, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("debug_tracker")


class PassiveE2ETracker:
    def __init__(self):
        self.start_time = time.time()
        self.running = True
        self.events: List[Dict[str, Any]] = []
        self.recursion_errors: List[Dict[str, Any]] = []
        self.general_errors: List[Dict[str, Any]] = []
        self.job_transitions: List[Dict[str, Any]] = []
        self.telemetry_history: List[Dict[str, Any]] = []
        self.known_job_states: Dict[str, str] = {}
        
        # Signal handling
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        logger.info("\n🛑 Stop signal received. Saving final forensic report...")
        self.running = False
        self.save_report()
        sys.exit(0)

    def get_monitored_pids(self) -> Dict[str, List[psutil.Process]]:
        """Identify currently active watcher, streamlit, and docker processes."""
        processes = {"watcher": [], "streamlit": [], "docker_align": []}
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = " ".join(proc.info['cmdline'] or [])
                    if "run_ingest_watcher.py" in cmdline:
                        processes["watcher"].append(proc)
                    elif "streamlit" in cmdline and "dashboard.py" in cmdline:
                        processes["streamlit"].append(proc)
                    elif "docker" in cmdline and "align" in cmdline:
                        processes["docker_align"].append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass
        return processes

    def sample_telemetry(self) -> Dict[str, Any]:
        """Capture memory RSS and CPU for active components."""
        pids_dict = self.get_monitored_pids()
        telemetry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(time.time() - self.start_time, 1),
            "watcher_running": len(pids_dict["watcher"]) > 0,
            "watcher_rss_mb": round(sum(p.memory_info().rss for p in pids_dict["watcher"]) / (1024 * 1024), 2) if pids_dict["watcher"] else 0.0,
            "streamlit_running": len(pids_dict["streamlit"]) > 0,
            "streamlit_rss_mb": round(sum(p.memory_info().rss for p in pids_dict["streamlit"]) / (1024 * 1024), 2) if pids_dict["streamlit"] else 0.0,
            "active_aligners_count": len(pids_dict["docker_align"])
        }
        return telemetry

    def tail_watcher_log(self):
        """Continuously tails watcher_daemon.log and traps errors and recursions in real time."""
        curr_pos = 0
        if WATCHER_LOG.exists():
            # Start from the current end of file or 20KB before end
            curr_pos = max(0, WATCHER_LOG.stat().st_size - 20000)

        traceback_buffer: List[str] = []
        in_traceback = False

        while self.running:
            try:
                if WATCHER_LOG.exists():
                    with open(WATCHER_LOG, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(curr_pos)
                        lines = f.readlines()
                        curr_pos = f.tell()

                        for line in lines:
                            line_str = line.rstrip()
                            line_lower = line_str.lower()

                            # Track tracebacks
                            if "traceback (most recent call last):" in line_lower:
                                in_traceback = True
                                traceback_buffer = [line_str]
                                continue
                            elif in_traceback:
                                traceback_buffer.append(line_str)
                                if line_str and not line_str.startswith(" ") and not line_str.startswith("\t"):
                                    # End of traceback reached
                                    in_traceback = False
                                    tb_text = "\n".join(traceback_buffer)
                                    is_recursion = "recursionerror" in tb_text.lower() or "maximum recursion depth exceeded" in tb_text.lower()
                                    
                                    err_event = {
                                        "timestamp": datetime.now().isoformat(),
                                        "elapsed_seconds": round(time.time() - self.start_time, 1),
                                        "source": "watcher_daemon.log",
                                        "is_recursion": is_recursion,
                                        "summary": line_str,
                                        "full_traceback": tb_text,
                                        "telemetry_at_error": self.sample_telemetry()
                                    }
                                    
                                    if is_recursion:
                                        self.recursion_errors.append(err_event)
                                        logger.critical(f"\n🚨 [RECURSION ERROR CAPTURED IN WATCHER]\n{tb_text}\n")
                                    else:
                                        self.general_errors.append(err_event)
                                        logger.error(f"⚠️ [WATCHER EXCEPTION] {line_str}")
                                    
                                    self.save_report()
                                    traceback_buffer = []

                            # Direct recursion message check (even outside full traceback)
                            if ("recursionerror" in line_lower or "maximum recursion depth exceeded" in line_lower) and not in_traceback:
                                rec_event = {
                                    "timestamp": datetime.now().isoformat(),
                                    "elapsed_seconds": round(time.time() - self.start_time, 1),
                                    "source": "watcher_daemon.log",
                                    "is_recursion": True,
                                    "summary": line_str,
                                    "full_traceback": line_str,
                                    "telemetry_at_error": self.sample_telemetry()
                                }
                                self.recursion_errors.append(rec_event)
                                logger.critical(f"\n🚨 [RECURSION ERROR CAUGHT] {line_str}\n")
                                self.save_report()
            except Exception as e:
                logger.debug(f"Error reading watcher log: {e}")
            time.sleep(1.0)

    def monitor_processing_jobs(self):
        """Monitors status JSON files in data/processing."""
        processing_dir = PROJECT_ROOT / "data" / "processing"
        if not processing_dir.exists():
            return

        status_files = list(processing_dir.glob("*_status.json"))
        for sf in status_files:
            try:
                data = json.loads(sf.read_text())
                prod_id = data.get("prod_id", sf.stem.replace("_status", ""))
                status = data.get("status", "")
                title = data.get("title", "")
                elapsed = data.get("time_elapsed_seconds", 0.0)

                prev_status = self.known_job_states.get(prod_id)
                if prev_status != status:
                    self.known_job_states[prod_id] = status
                    transition = {
                        "timestamp": datetime.now().isoformat(),
                        "elapsed_seconds": round(time.time() - self.start_time, 1),
                        "prod_id": prod_id,
                        "title": title,
                        "from_status": prev_status,
                        "to_status": status,
                        "job_elapsed_seconds": elapsed
                    }
                    self.job_transitions.append(transition)
                    logger.info(f"📚 [JOB STATE CHANGE] `{prod_id}` ('{title}') -> Status: '{status}'")
                    self.save_report()
            except Exception:
                pass

    def save_report(self):
        """Save structured forensic report to JSON."""
        report_data = {
            "tracker_start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "last_updated": datetime.now().isoformat(),
            "total_monitoring_duration_seconds": round(time.time() - self.start_time, 1),
            "recursion_error_count": len(self.recursion_errors),
            "general_error_count": len(self.general_errors),
            "recursion_errors": self.recursion_errors,
            "general_errors": self.general_errors,
            "job_transitions": self.job_transitions,
            "latest_telemetry": self.sample_telemetry(),
            "telemetry_samples": self.telemetry_history[-50:]  # Keep last 50 samples
        }
        try:
            REPORT_JSON.write_text(json.dumps(report_data, indent=2))
        except Exception as e:
            logger.debug(f"Failed to write forensic report: {e}")

    def tail_dashboard_error_log(self):
        """Continuously tails dashboard_error.log and captures GUI exceptions directly into forensic_report.json."""
        dashboard_log = DEBUG_DIR / "dashboard_error.log"
        curr_pos = 0
        while self.running:
            try:
                if dashboard_log.exists():
                    with open(dashboard_log, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(curr_pos)
                        lines = f.readlines()
                        curr_pos = f.tell()

                        for line in lines:
                            line_str = line.rstrip()
                            line_lower = line_str.lower()
                            if not line_str:
                                continue

                            is_recursion = "recursionerror" in line_lower or "maximum recursion depth exceeded" in line_lower
                            err_event = {
                                "timestamp": datetime.now().isoformat(),
                                "elapsed_seconds": round(time.time() - self.start_time, 1),
                                "source": "dashboard_error.log",
                                "is_recursion": is_recursion,
                                "summary": line_str[:200],
                                "full_traceback": line_str,
                                "telemetry_at_error": self.sample_telemetry()
                            }
                            if is_recursion:
                                self.recursion_errors.append(err_event)
                                logger.critical(f"\n🚨 [RECURSION ERROR CAPTURED IN DASHBOARD]\n{line_str}\n")
                            else:
                                self.general_errors.append(err_event)
                                logger.error(f"⚠️ [DASHBOARD ERROR] {line_str[:120]}")

                            self.save_report()
            except Exception as e:
                logger.debug(f"Error reading dashboard error log: {e}")
            time.sleep(1.0)

    def run(self):
        """Start passive monitoring loop."""
        logger.info("\n" + "="*80)
        logger.info("   🔍 PASSIVE E2E DEBUG & RECURSION TRACKER STARTED")
        logger.info("="*80)
        logger.info("• Monitoring Watcher Daemon, Streamlit Dashboard, and Ingestion Jobs")
        logger.info(f"• Diagnostic output target: {REPORT_JSON}")
        logger.info("• Press Ctrl+C at any time to finish and generate final forensic summary.\n")

        # Start log tailing in background threads
        w_thread = threading.Thread(target=self.tail_watcher_log, daemon=True)
        w_thread.start()

        d_thread = threading.Thread(target=self.tail_dashboard_error_log, daemon=True)
        d_thread.start()

        last_heartbeat_print = 0
        last_telemetry_sample = 0

        while self.running:
            try:
                now = time.time()

                # Sample telemetry every 5s
                if now - last_telemetry_sample >= 5:
                    last_telemetry_sample = now
                    telem = self.sample_telemetry()
                    self.telemetry_history.append(telem)

                # Check job transitions
                self.monitor_processing_jobs()

                # Periodic console summary every 30s
                if now - last_heartbeat_print >= 30:
                    last_heartbeat_print = now
                    elapsed_min = (now - self.start_time) / 60.0
                    telem = self.sample_telemetry()
                    w_str = f"Watcher: {'🟢 Online' if telem['watcher_running'] else '🔴 Offline'} ({telem['watcher_rss_mb']}MB)"
                    s_str = f"Streamlit: {'🟢 Online' if telem['streamlit_running'] else '🔴 Offline'} ({telem['streamlit_rss_mb']}MB)"
                    d_str = f"Docker Aligners: {telem['active_aligners_count']}"
                    rec_str = f"Recursions: {len(self.recursion_errors)}"
                    logger.info(f"⏱️ [Tracker T+{elapsed_min:.1f}m] {w_str} | {s_str} | {d_str} | {rec_str}")

                time.sleep(2)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in tracking loop: {e}")
                time.sleep(2)

        self.save_report()
        logger.info(f"\n✅ Forensic Report successfully updated at: {REPORT_JSON}")


def main():
    tracker = PassiveE2ETracker()
    tracker.run()


if __name__ == "__main__":
    main()
