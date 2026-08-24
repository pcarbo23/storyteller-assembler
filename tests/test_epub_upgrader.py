import zipfile
import pytest
from pathlib import Path
from bs4 import BeautifulSoup
from src.epub_upgrader import is_epub2, upgrade_epub2_to_epub3

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def test_detect_epub2_files():
    epub2_path = PROJECT_ROOT / "test_material/Day Zero/Day Zero.epub"
    if epub2_path.exists():
        assert is_epub2(epub2_path) is True

    epub3_path = PROJECT_ROOT / "test_material/A Mouthful of Dust/A Mouthful of Dust-9781250386410.epub"
    if epub3_path.exists():
        assert is_epub2(epub3_path) is False

def test_upgrade_epub2_to_epub3(tmp_path):
    epub2_src = PROJECT_ROOT / "test_material/Day Zero/Day Zero.epub"
    if not epub2_src.exists():
        pytest.skip("Day Zero sample EPUB not found")

    target_epub = tmp_path / "Day_Zero_upgraded.epub"
    res_path = upgrade_epub2_to_epub3(epub2_src, target_epub)

    assert res_path.exists()
    assert is_epub2(res_path) is False

    # Verify internal structure
    with zipfile.ZipFile(res_path, "r") as z:
        # Find OPF
        container_xml = z.read("META-INF/container.xml")
        c_soup = BeautifulSoup(container_xml, "xml")
        opf_path = c_soup.find("rootfile")["full-path"]
        
        opf_content = z.read(opf_path)
        opf_soup = BeautifulSoup(opf_content, "xml")
        pkg = opf_soup.find("package")

        assert pkg["version"] == "3.0"
        assert "xmlns:epub" in pkg.attrs or pkg.get("xmlns:epub") == "http://www.idpf.org/2007/ops"

        # Check for nav document in manifest
        nav_item = opf_soup.find("item", properties=lambda x: x and "nav" in x)
        assert nav_item is not None
        assert nav_item.get("href") is not None

        # Verify nav document exists inside the archive
        opf_dir = Path(opf_path).parent
        nav_rel_path = str(opf_dir / nav_item["href"]) if str(opf_dir) != "." else nav_item["href"]
        assert nav_rel_path in z.namelist()
