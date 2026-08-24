import gc
import os
import sys
import json
import time
import sqlite3
import subprocess
import traceback
from pathlib import Path
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# Run garbage collection on each render pass to prevent memory leak accumulation over thousands of runs
gc.collect()

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Add common macOS paths to environment PATH for GUI environment support (like AppleScript App launches)
for path in ["/usr/local/bin", "/opt/homebrew/bin", "/Applications/Docker.app/Contents/Resources/bin"]:
    if path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{path}:{os.environ.get('PATH', '')}"

# Set page title and layout
st.set_page_config(
    page_title="Storyteller Assembler Dashboard",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom header styling
st.markdown("""
    <style>
        .main-header {
            font-size: 2.5rem;
            color: #1E3A8A;
            font-weight: bold;
            margin-bottom: 0.5rem;
        }
        .subheader {
            font-size: 1.1rem;
            color: #4B5563;
            margin-bottom: 2rem;
        }
        /* Hide top-right running man / spinner status indicator */
        [data-testid="stStatusWidget"],
        div.stStatusWidget,
        div[class*="StatusWidget"],
        div[class*="stStatusWidget"] {
            visibility: hidden !important;
            display: none !important;
        }
    </style>
""", unsafe_allow_html=True)

# Helper function to load JSON
def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None

# Process & Daemon helper functions
def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def start_watcher():
    watcher_script = PROJECT_ROOT / "scripts" / "run_ingest_watcher.py"
    log_file = PROJECT_ROOT / "data" / "watcher_daemon.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Launch daemon in the background using the current virtual env python interpreter
    with open(log_file, "a") as f:
        subprocess.Popen(
            [sys.executable, str(watcher_script)],
            stdout=f,
            stderr=f,
            cwd=str(PROJECT_ROOT),
            preexec_fn=os.setpgrp
        )

def stop_watcher(pid: int):
    try:
        os.kill(pid, 15)  # SIGTERM
        time.sleep(0.5)
        if is_pid_running(pid):
            os.kill(pid, 9)  # SIGKILL
        return True
    except Exception:
        return False

def check_docker_health() -> bool:
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=2)
        return res.returncode == 0
    except Exception:
        return False

def launch_docker():
    try:
        subprocess.Popen(["open", "-a", "Docker"])
        return True
    except Exception:
        return False

def load_production_history():
    """Load persistent production records from SQLite database."""
    db_path = PROJECT_ROOT / "data" / "production_history.db"
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                prod_id, dc_title, dc_creator, dc_date, dc_publisher, source_publisher,
                dc_language, x_metadata_narrator, x_metadata_copyright, 
                isbn_epub, isbn_audio, zedval_status, nlsval_status, validator_version, timestamp_completed 
            FROM production_history 
            ORDER BY timestamp_completed DESC
        """)
        cols = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        return [dict(zip(cols, row)) for row in rows]
    except Exception:
        return []

def prune_processing_files(keep_recent_completed: int = 10) -> dict:
    """
    Deletes intermediate aligned EPUB files and prunes old completed status JSONs
    from data/processing/, keeping only active/failed and recent completed jobs.
    """
    work_dir = PROJECT_ROOT / "data" / "processing"
    if not work_dir.exists():
        return {"epubs_deleted": 0, "status_pruned": 0}
    
    epubs_deleted = 0
    # 1. Delete intermediate *.epub files in data/processing/
    for ep in work_dir.glob("*.epub"):
        try:
            ep.unlink()
            epubs_deleted += 1
        except Exception:
            pass
            
    # 2. Prune old completed status JSON files
    completed_records = []
    for sf in work_dir.glob("*_status.json"):
        data = load_json(sf)
        if data and data.get("status") == "completed":
            completed_records.append((sf, data.get("last_update", "")))
            
    completed_records.sort(key=lambda x: x[1], reverse=True)
    status_pruned = 0
    for sf, _ in completed_records[keep_recent_completed:]:
        try:
            sf.unlink()
            status_pruned += 1
        except Exception:
            pass
            
    return {"epubs_deleted": epubs_deleted, "status_pruned": status_pruned}

def render_dashboard():
    # Setup automatic polling using streamlit-autorefresh (5 seconds)
    st_autorefresh(interval=5000, key="watcher_dashboard_autorefresh")

    st.markdown('<div class="main-header">📚 Storyteller Assembler Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="subheader">Real-time status monitor for local macOS sandbox audio synchronization & compliance pipeline.</div>', unsafe_allow_html=True)

    # Initialize session state for persistent control transitions
    if "starting_watcher" not in st.session_state:
        st.session_state.starting_watcher = False
    if "launching_docker" not in st.session_state:
        st.session_state.launching_docker = False

    # Load daemon status
    heartbeat_data = load_json(PROJECT_ROOT / "data" / "watcher_heartbeat.json")
    docker_online = check_docker_health()

    # Sidebar controls
    with st.sidebar:
        st.markdown("### ⚙️ System Controls")
        if st.button("🔴 Shut Down All Services", use_container_width=True):
            st.warning("Stopping services...")
            # 1. Stop Watcher Daemon if running
            if heartbeat_data:
                w_pid = heartbeat_data.get("pid")
                if w_pid and is_pid_running(w_pid):
                    stop_watcher(w_pid)
            # 2. Stop Streamlit
            st.info("Stopped! You can now close this tab.")
            time.sleep(1.0)
            os.kill(os.getpid(), 9)

    # Layout columns for status cards
    col1, col2 = st.columns(2)

    # 1. Watcher Daemon Card
    with col1:
        with st.container():
            st.subheader("🤖 Watcher Daemon")
            
            watcher_running = False
            pid = None
            
            if heartbeat_data:
                pid = heartbeat_data.get("pid")
                last_hb_str = heartbeat_data.get("last_heartbeat")
                if last_hb_str:
                    last_hb = datetime.fromisoformat(last_hb_str)
                    seconds_ago = (datetime.now() - last_hb).total_seconds()
                    
                    # Check heartbeat freshness AND if the PID is actually alive on host
                    if seconds_ago < 15 and pid and is_pid_running(pid):
                        watcher_running = True
                        st.session_state.starting_watcher = False
                        st.success(f"Running (PID: {pid})")
                        st.caption(f"Last heartbeat: {seconds_ago:.1f} seconds ago")
                    elif pid and is_pid_running(pid):
                        # Process is alive but heartbeat is stale (maybe starting up or busy)
                        watcher_running = True
                        st.session_state.starting_watcher = False
                        st.warning(f"Running - Heartbeat Stale (PID: {pid})")
                        st.caption(f"Last heartbeat: {seconds_ago:.1f} seconds ago")
                    else:
                        st.error("Stopped / Inactive")
                        st.caption(f"Last active heartbeat was {seconds_ago:.1f} seconds ago.")
                else:
                    st.error("Stopped / Inactive")
            else:
                st.warning("Not Started")
                st.caption("No heartbeat found.")

            # Active transition feedback
            if st.session_state.starting_watcher and not watcher_running:
                st.info("Starting watcher daemon...")

            # Controls
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Start Watcher Daemon", disabled=watcher_running or st.session_state.starting_watcher, use_container_width=True):
                    st.session_state.starting_watcher = True
                    start_watcher()
            with c2:
                if st.button("Stop Watcher Daemon", disabled=not watcher_running, use_container_width=True):
                    if pid:
                        stop_watcher(pid)

    # 2. Docker Service Card
    with col2:
        with st.container():
            st.subheader("🐳 Docker Daemon")
            
            if docker_online:
                st.session_state.launching_docker = False
                st.success("Online")
                st.caption("Docker daemon is running and responding.")
            else:
                st.error("Offline")
                st.caption("Docker daemon is not running on the host.")
                
            # Active transition feedback
            if st.session_state.launching_docker and not docker_online:
                st.info("Launching Docker Desktop app...")

            # Controls
            if st.button("Launch Docker Desktop", disabled=docker_online or st.session_state.launching_docker, use_container_width=True):
                st.session_state.launching_docker = True
                if not launch_docker():
                    st.session_state.launching_docker = False
                    st.error("Failed to launch Docker. Make sure Docker Desktop is installed.")

    # Daemon Log Viewer
    log_file = PROJECT_ROOT / "data" / "watcher_daemon.log"
    if log_file.exists():
        with st.expander("📝 View Watcher Daemon Logs", expanded=False):
            try:
                log_lines = log_file.read_text().splitlines()
                # Show last 40 lines
                st.code("\n".join(log_lines[-40:]))
            except Exception as e:
                st.caption(f"Could not load log file: {e}")

    # Tabbed Interface for Queue, Archive, and Metrics
    st.write("---")
    tab_queue, tab_archive, tab_metrics = st.tabs(["🚀 Live Assembler Queue", "📚 Production Archive", "📊 Analytics & Audit"])

    # -------------------------------------------------------------
    # TAB 1: LIVE ASSEMBLER QUEUE (In-flight & Recent)
    # -------------------------------------------------------------
    with tab_queue:
        st.subheader("📦 Live In-Flight & Recent Jobs")

        processing_dir = PROJECT_ROOT / "data" / "processing"
        job_files = list(processing_dir.glob("*_status.json")) if processing_dir.exists() else []

        raw_jobs = []
        for jf in job_files:
            data = load_json(jf)
            if data:
                status = data.get("status", "")
                elapsed = data.get("time_elapsed_seconds", 0.0)
                
                # Calculate live elapsed time for active (non-terminal) jobs
                terminal_statuses = ["completed", "failed", "failed_alignment", "failed_conversion", "failed_validation"]
                if status not in terminal_statuses and "start_time" in data:
                    try:
                        start_dt = datetime.fromisoformat(data["start_time"])
                        elapsed = (datetime.now() - start_dt).total_seconds()
                    except Exception:
                        pass
                        
                raw_jobs.append({
                    "Production ID": data.get("prod_id", ""),
                    "Title": data.get("title", ""),
                    "Status": status,
                    "Elapsed Time": f"{elapsed:.1f}s",
                    "elapsed_seconds": elapsed,
                    "Last Update": data.get("last_update", "").split("T")[-1][:8] if "T" in data.get("last_update", "") else "N/A",
                    "last_update_raw": data.get("last_update", ""),
                    "is_active": status not in terminal_statuses,
                    "file_path": jf
                })

        # Separate in-flight from completed to cap recent completed in live view
        active_and_failed = [j for j in raw_jobs if j["Status"] != "completed"]
        completed_recent = [j for j in raw_jobs if j["Status"] == "completed"]
        completed_recent.sort(key=lambda x: x["last_update_raw"], reverse=True)

        # Show active + up to 20 recent completed records in live queue
        jobs = active_and_failed + completed_recent[:20]

        if jobs:
            # Table sorting controls
            c_sort1, c_sort2, _ = st.columns([2, 2, 4])
            with c_sort1:
                sort_col = st.selectbox("Sort by:", ["Production ID", "Title", "Status", "Elapsed Time", "Last Update"], key="jobs_sort_col")
            with c_sort2:
                sort_dir = st.selectbox("Order:", ["Ascending", "Descending"], key="jobs_sort_dir")

            reverse = (sort_dir == "Descending")
            if sort_col == "Elapsed Time":
                jobs.sort(key=lambda x: x["elapsed_seconds"], reverse=reverse)
            elif sort_col == "Last Update":
                jobs.sort(key=lambda x: x["last_update_raw"], reverse=reverse)
            elif sort_col == "Production ID":
                jobs.sort(key=lambda x: str(x["Production ID"]).lower(), reverse=reverse)
            elif sort_col == "Title":
                jobs.sort(key=lambda x: str(x["Title"]).lower(), reverse=reverse)
            elif sort_col == "Status":
                jobs.sort(key=lambda x: str(x["Status"]).lower(), reverse=reverse)

            # Build a clean Markdown table with status emojis
            md = "| Production ID | Title | Status | Elapsed Time | Last Update |\n"
            md += "| :--- | :--- | :--- | :--- | :--- |\n"
            for j in jobs:
                status_str = j["Status"]
                status_emoji = "🟢"
                if "failed" in status_str:
                    status_emoji = "🔴"
                elif status_str in ["starting", "aligning", "processing_dtb", "validating"]:
                    status_emoji = "🟡"
                    
                md += f"| `{j['Production ID']}` | **{j['Title']}** | {status_emoji} {status_str} | {j['Elapsed Time']} | {j['Last Update']} |\n"
                
            st.markdown(md, unsafe_allow_html=True)
            
            # Active/Running Job Kill Controls
            active_jobs = [j for j in jobs if j["is_active"]]
            if active_jobs:
                st.write("---")
                st.markdown("### 🛑 Active Job Controls")
                
                c1, c2 = st.columns(2)
                with c1:
                    for aj in active_jobs:
                        aj_id = aj["Production ID"]
                        if st.button(f"Force-Kill Job: {aj_id}", key=f"kill_{aj_id}", use_container_width=True):
                            st.info(f"Stopping container for job {aj_id}...")
                            subprocess.run(["docker", "rm", "-f", f"align_{aj_id}"], capture_output=True)
                            
                            # Update status file
                            js_file = PROJECT_ROOT / "data" / "processing" / f"{aj_id}_status.json"
                            if js_file.exists():
                                try:
                                    jdata = json.loads(js_file.read_text())
                                    jdata["status"] = "failed_alignment"
                                    jdata["error"] = "Job cancelled and force-killed by user from dashboard."
                                    js_file.write_text(json.dumps(jdata, indent=2))
                                except Exception:
                                    pass
                            st.success(f"Forced kill signal sent to job {aj_id}.")
                            time.sleep(1.0)
                            st.experimental_rerun()
                            
                with c2:
                    if st.button("🧹 Clean All node:slim Containers", use_container_width=True):
                        st.info("Locating and terminating all transient node:slim containers...")
                        res = subprocess.run(
                            ["docker", "ps", "-a", "--filter", "ancestor=node:slim", "--format", "{{.ID}}"],
                            capture_output=True,
                            text=True
                        )
                        c_ids = [line.strip() for line in res.stdout.splitlines() if line.strip()]
                        if c_ids:
                            for cid in c_ids:
                                subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
                            st.success(f"Cleaned up {len(c_ids)} container(s).")
                        else:
                            st.success("No active node:slim containers found.")
                        
            # Detail expander for errors
            failed_jobs = [jf for jf in job_files if load_json(jf) and "failed" in load_json(jf).get("status", "")]
            if failed_jobs:
                st.warning("⚠️ Processing Failures Detected:")
                for fj in failed_jobs:
                    fj_data = load_json(fj)
                    if fj_data:
                        with st.expander(f"Error details for '{fj_data.get('title')}' (ID: {fj_data.get('prod_id')})"):
                            st.code(fj_data.get("error", "Unknown error occurred."))
        else:
            st.info("No active or recent assembler jobs in in-flight queue.")

    # -------------------------------------------------------------
    # TAB 2: PRODUCTION ARCHIVE (Persistent SQLite Database)
    # -------------------------------------------------------------
    with tab_archive:
        st.subheader("📚 Persistent Production Archive")
        history_records = load_production_history()

        if history_records:
            c_arch1, c_arch2, c_arch3 = st.columns([4, 2, 2])
            with c_arch1:
                search_q = st.text_input("🔍 Search Archive:", placeholder="Title, Creator, Narrator, ISBN, or ID...", key="arch_search")
            with c_arch2:
                status_filter = st.selectbox("Compliance Filter:", ["All Records", "Passed (ZedVal pass)", "Failed (ZedVal fail)"], key="arch_filter")
            with c_arch3:
                st.write("")
                st.write("")
                csv_path = PROJECT_ROOT / "data" / "production_log.csv"
                if csv_path.exists():
                    st.download_button(
                        label="📥 Export Full CSV Log",
                        data=csv_path.read_bytes(),
                        file_name=f"production_log_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

            # Apply filters
            filtered = history_records
            if search_q.strip():
                sq = search_q.strip().lower()
                filtered = [
                    r for r in filtered
                    if sq in str(r.get("prod_id", "")).lower()
                    or sq in str(r.get("dc_title", "")).lower()
                    or sq in str(r.get("dc_creator", "")).lower()
                    or sq in str(r.get("x_metadata_narrator", "")).lower()
                    or sq in str(r.get("source_publisher", "")).lower()
                    or sq in str(r.get("isbn_epub", "")).lower()
                    or sq in str(r.get("isbn_audio", "")).lower()
                ]

            if status_filter == "Passed (ZedVal pass)":
                filtered = [r for r in filtered if r.get("zedval_status") == "pass"]
            elif status_filter == "Failed (ZedVal fail)":
                filtered = [r for r in filtered if r.get("zedval_status") == "fail"]

            st.caption(f"Displaying {len(filtered)} of {len(history_records)} recorded productions from `production_history.db`")

            if filtered:
                arch_md = "| ID | Title | Creator / Narrator | Source Publisher | ISBNs (EPUB / Audio) | Compliance | Completed |\n"
                arch_md += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
                for r in filtered:
                    c_status = r.get("zedval_status", "")
                    c_badge = "🟢 Pass" if c_status == "pass" else ("🔴 Fail" if c_status == "fail" else "⚪ Pending")
                    creator_narrator = f"{r.get('dc_creator', 'N/A')}"
                    if r.get('x_metadata_narrator'):
                        creator_narrator += f" / *{r.get('x_metadata_narrator')}*"
                    src_pub = r.get('source_publisher') or r.get('dc_publisher', 'N/A')
                    isbns = f"{r.get('isbn_epub', 'N/A')} / {r.get('isbn_audio', 'N/A')}"
                    ts = r.get("timestamp_completed", "").split("T")[0] if "T" in r.get("timestamp_completed", "") else r.get("timestamp_completed", "N/A")
                    
                    arch_md += f"| `{r.get('prod_id')}` | **{r.get('dc_title')}** | {creator_narrator} | {src_pub} | {isbns} | {c_badge} | {ts} |\n"
                st.markdown(arch_md, unsafe_allow_html=True)
            else:
                st.info("No archive records match your search filter.")

            # Prune in-flight temp storage maintenance button
            st.write("---")
            c_p1, c_p2 = st.columns([3, 5])
            with c_p1:
                if st.button("🧹 Prune Completed In-Flight Files", use_container_width=True, help="Deletes intermediate EPUBs and older completed JSON status files from data/processing/"):
                    res = prune_processing_files(keep_recent_completed=10)
                    st.success(f"Pruned {res['status_pruned']} completed status files & deleted {res['epubs_deleted']} intermediate EPUBs. Historical records remain permanently safe in SQLite.")
                    time.sleep(1.5)
                    st.experimental_rerun()
            with c_p2:
                st.caption("Pruning removes heavy intermediate `.epub` and stale in-flight JSONs from `data/processing/`. Long-term SQLite production records are not affected.")
        else:
            st.info("No completed production records found in SQLite database (`data/production_history.db`).")

    # -------------------------------------------------------------
    # TAB 3: ANALYTICS & AUDIT
    # -------------------------------------------------------------
    with tab_metrics:
        st.subheader("📊 Production Analytics & Compliance Summary")
        all_records = load_production_history()
        
        total_prod = len(all_records)
        passed_prod = len([r for r in all_records if r.get("zedval_status") == "pass"])
        failed_prod = len([r for r in all_records if r.get("zedval_status") == "fail"])
        pass_rate = (passed_prod / total_prod * 100.0) if total_prod > 0 else 0.0
        
        unique_narrators = len(set(r.get("x_metadata_narrator") for r in all_records if r.get("x_metadata_narrator")))
        
        # Calculate distinct source publishers (excluding the NLS distributor string if present)
        source_pubs = [
            r.get("source_publisher") for r in all_records 
            if r.get("source_publisher") and "National Library Service" not in r.get("source_publisher")
        ]
        unique_publishers = len(set(source_pubs)) if source_pubs else len(set(r.get("dc_publisher") for r in all_records if r.get("dc_publisher")))

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Books Produced", f"{total_prod}")
        m2.metric("Compliance Pass Rate", f"{pass_rate:.1f}%", delta=f"{passed_prod} Passed / {failed_prod} Failed")
        m3.metric("Distinct Narrators", f"{unique_narrators}")
        m4.metric("Source Publishers", f"{unique_publishers}")

        st.write("---")
        st.markdown("### 📋 Recent Deliverables Breakdown")
        if all_records:
            recent_10 = all_records[:10]
            r_md = "| ID | Title | Source Publisher | Language | Completed Date |\n"
            r_md += "| :--- | :--- | :--- | :--- | :--- |\n"
            for r in recent_10:
                ts = r.get("timestamp_completed", "").replace("T", " ")[:19]
                pub = r.get("source_publisher") or r.get("dc_publisher", "N/A")
                r_md += f"| `{r.get('prod_id')}` | **{r.get('dc_title')}** | {pub} | `{r.get('dc_language', 'en-US')}` | {ts} |\n"
            st.markdown(r_md, unsafe_allow_html=True)
        else:
            st.info("No production data available for metrics calculation.")

    # Manual refresh button fallback
    st.write("---")
    c_ref1, c_ref2 = st.columns([8, 2])
    with c_ref2:
        if st.button("🔄 Refresh Data", key="manual_refresh_btn", use_container_width=True):
            st.experimental_rerun()

    st.caption("🔄 Auto-refresh active (5s interval, streamlit-autorefresh)")

try:
    render_dashboard()
except Exception as e:
    err_msg = f"Dashboard Error: {e}\n{traceback.format_exc()}"
    error_log = PROJECT_ROOT / "data" / "debug" / "dashboard_error.log"
    error_log.parent.mkdir(parents=True, exist_ok=True)
    with open(error_log, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] {err_msg}\n")
    st.error(f"⚠️ An unexpected error occurred in Dashboard: {e}")
    with st.expander("View Diagnostic Traceback"):
        st.code(traceback.format_exc())
