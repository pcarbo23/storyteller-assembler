import json
import pytest
import tempfile
import threading
from pathlib import Path
from src.prod_id_manager import ProdIDManager
from src.tracker import ProductionTracker

def test_prod_id_manager_constraints():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.json"
        
        # Test default creation
        manager = ProdIDManager(config_path)
        assert config_path.exists()
        
        # Test lowercase enforcement
        config_path.write_text(json.dumps({
            "prefix": "DB",
            "range_start": 100000,
            "range_end": 199999,
            "next_value": 100000
        }))
        leased_id = manager.lease_id()
        assert leased_id == "db100000"
        
        # Test 6-digit minimum constraint
        config_path.write_text(json.dumps({
            "prefix": "db",
            "range_start": 9999,
            "range_end": 99999,
            "next_value": 9999
        }))
        with pytest.raises(ValueError, match="at least 6 digits long"):
            manager.lease_id()

def test_prod_id_manager_concurrency():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.json"
        manager = ProdIDManager(config_path)
        
        leased_ids = []
        def worker():
            for _ in range(10):
                leased_ids.append(manager.lease_id())
                
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            
        assert len(leased_ids) == 50
        assert len(set(leased_ids)) == 50
        assert leased_ids[0] == "db100000"
        assert "db100049" in leased_ids

def test_production_tracker():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        csv_path = Path(tmp_dir) / "test.csv"
        
        tracker = ProductionTracker(db_path, csv_path)
        
        opf_path = Path(tmp_dir) / "test.opf"
        opf_path.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<package unique-identifier="uid" xmlns="http://openebook.org/namespaces/oeb-package/1.0/">
  <metadata>
    <dc-metadata xmlns:dc="http://purl.org/dc/elements/1.0/">
      <dc:Title>Test Title</dc:Title>
      <dc:Creator>Test Author</dc:Creator>
      <dc:Date>2026-08-06</dc:Date>
      <dc:Publisher>Test Publisher</dc:Publisher>
      <dc:Language>en</dc:Language>
    </dc-metadata>
    <x-metadata>
      <meta name="dtb:narrator" content="Test Narrator"/>
      <meta name="dtb:sourcePublisher" content="Random House Audio"/>
    </x-metadata>
  </metadata>
</package>
""", encoding="utf-8")
        
        tracker.log_production(
            prod_id="db100001",
            opf_path=opf_path,
            isbn_epub="1234567890",
            isbn_audio="0987654321",
            zedval_status="pass",
            nlsval_status="pending"
        )
        
        # Verify CSV
        assert csv_path.exists()
        with open(csv_path, mode="r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 2 # Header + 1 row
            assert "db100001" in lines[1]
            assert "Test Title" in lines[1]
            assert "Test Author" in lines[1]
            assert "1234567890" in lines[1]
            assert "pass" in lines[1]
            assert "pending" in lines[1]
