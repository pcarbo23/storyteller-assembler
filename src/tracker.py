import csv
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

class ProductionTracker:
    """
    Tracks successfully converted NLS DTB packages.
    Stores records in a local SQLite database and exports to a human-readable CSV.
    """
    def __init__(self, db_path: Path, csv_path: Path):
        self.db_path = Path(db_path)
        self.csv_path = Path(csv_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create the SQLite tracking table if it does not exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS production_history (
                    prod_id TEXT PRIMARY KEY,
                    dc_title TEXT,
                    dc_creator TEXT,
                    dc_date TEXT,
                    dc_publisher TEXT,
                    source_publisher TEXT,
                    dc_language TEXT,
                    x_metadata_narrator TEXT,
                    x_metadata_copyright TEXT,
                    isbn_epub TEXT,
                    isbn_audio TEXT,
                    zedval_status TEXT,
                    nlsval_status TEXT,
                    validator_version TEXT,
                    timestamp_completed TEXT
                )
            """)
            conn.commit()

            # Ensure source_publisher and validator_version columns exist in existing databases (migration)
            for col in ["source_publisher", "validator_version"]:
                try:
                    cursor.execute(f"ALTER TABLE production_history ADD COLUMN {col} TEXT")
                    conn.commit()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database: {e}")
        finally:
            conn.close()

    def _parse_opf(self, opf_path: Path) -> dict:
        """Parse OPF file to extract dc and x-metadata fields including dtb:sourcePublisher."""
        metadata = {}
        if not opf_path.exists():
            return metadata
        try:
            from bs4 import BeautifulSoup
            content = opf_path.read_text(encoding="utf-8")
            soup = BeautifulSoup(content, "xml")
            
            # Helper to find dc elements (case-insensitive)
            # Find all dc elements inside dc-metadata or metadata
            dc_metadata = soup.find("dc-metadata") or soup.find("metadata")
            if dc_metadata:
                for child in dc_metadata.find_all(recursive=True):
                    tag_name = child.name.lower()
                    # Strip namespace prefix if any (e.g. dc:title -> title)
                    if ":" in tag_name:
                        tag_name = tag_name.split(":")[-1]
                    
                    if tag_name == "title":
                        metadata["dc:title"] = child.text.strip()
                    elif tag_name == "creator":
                        metadata["dc:creator"] = child.text.strip()
                    elif tag_name == "date":
                        metadata["dc:date"] = child.text.strip()
                    elif tag_name == "publisher":
                        metadata["dc:publisher"] = child.text.strip()
                    elif tag_name == "language":
                        metadata["dc:language"] = child.text.strip()
                        
            # Helper to find x-metadata elements
            for meta in soup.find_all("meta"):
                name = meta.get("name", "").lower()
                content_val = meta.get("content", "").strip()
                if "narrator" in name:
                    metadata["x-metadata:narrator"] = content_val
                elif "copyright" in name:
                    metadata["x-metadata:copyright"] = content_val
                elif "sourcepublisher" in name:
                    metadata["x-metadata:sourcePublisher"] = content_val
                    
            # Fallback for dtb:sourcePublisher if not in meta tags
            if not metadata.get("x-metadata:sourcePublisher"):
                sp_tag = soup.find(lambda tag: "sourcepublisher" in tag.name.lower())
                if sp_tag and sp_tag.text:
                    metadata["x-metadata:sourcePublisher"] = sp_tag.text.strip()

            # Fallback for copyright if not explicitly in meta: check dc:rights
            if not metadata.get("x-metadata:copyright"):
                rights_el = soup.find("dc:Rights") or soup.find("dc:rights") or soup.find("rights")
                if rights_el:
                    metadata["x-metadata:copyright"] = rights_el.text.strip()
        except Exception as e:
            logger.error(f"Failed to parse OPF file {opf_path}: {e}")
        return metadata

    def log_production(
        self,
        prod_id: str,
        opf_path: Path,
        isbn_epub: str,
        isbn_audio: str,
        zedval_status: str,
        nlsval_status: str,
        validator_version: str = ""
    ) -> None:
        """
        Record conversion metadata to SQLite database and append to human-readable CSV.
        """
        timestamp = datetime.now().isoformat()
        
        # Parse metadata from OPF file
        metadata = self._parse_opf(opf_path)
        
        dc_title = metadata.get("dc:title", "")
        dc_creator = metadata.get("dc:creator", "")
        dc_date = metadata.get("dc:date", "")
        dc_publisher = metadata.get("dc:publisher", "")
        source_publisher = metadata.get("x-metadata:sourcePublisher", "")
        if not source_publisher:
            source_publisher = dc_publisher
            
        dc_language = metadata.get("dc:language", "")
        x_metadata_narrator = metadata.get("x-metadata:narrator", "")
        x_metadata_copyright = metadata.get("x-metadata:copyright", "")

        row = {
            "prod_id": prod_id,
            "dc_title": dc_title,
            "dc_creator": dc_creator,
            "dc_date": dc_date,
            "dc_publisher": dc_publisher,
            "source_publisher": source_publisher,
            "dc_language": dc_language,
            "x_metadata_narrator": x_metadata_narrator,
            "x_metadata_copyright": x_metadata_copyright,
            "isbn_epub": isbn_epub,
            "isbn_audio": isbn_audio,
            "zedval_status": zedval_status,
            "nlsval_status": nlsval_status,
            "validator_version": validator_version,
            "timestamp_completed": timestamp
        }

        # 1. Save to SQLite
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO production_history (
                    prod_id, dc_title, dc_creator, dc_date, dc_publisher, source_publisher, dc_language,
                    x_metadata_narrator, x_metadata_copyright, isbn_epub, isbn_audio,
                    zedval_status, nlsval_status, validator_version, timestamp_completed
                ) VALUES (
                    :prod_id, :dc_title, :dc_creator, :dc_date, :dc_publisher, :source_publisher, :dc_language,
                    :x_metadata_narrator, :x_metadata_copyright, :isbn_epub, :isbn_audio,
                    :zedval_status, :nlsval_status, :validator_version, :timestamp_completed
                )
            """, row)
            conn.commit()
            logger.info(f"Recorded metadata for {prod_id} (Source Publisher: '{source_publisher}', Validator Ver: '{validator_version}') in SQLite database.")
        except Exception as e:
            logger.error(f"Failed to save record to SQLite: {e}")
        finally:
            conn.close()

        # 2. Append to CSV
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_exists = self.csv_path.exists()
        
        headers = list(row.keys())
        try:
            with open(self.csv_path, mode="a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                if not csv_exists:
                    writer.writeheader()
                writer.writerow(row)
            logger.info(f"Appended metadata for {prod_id} to CSV file: {self.csv_path}")
        except Exception as e:
            logger.error(f"Failed to append record to CSV: {e}")
