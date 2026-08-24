import os
import re
import shutil
import zipfile
import logging
from pathlib import Path
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def is_epub2(epub_path: Path) -> bool:
    """Check if the given EPUB file is version 2.0 (or not EPUB 3)."""
    if not epub_path.exists():
        return False
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            # 1. Read META-INF/container.xml to find the OPF path
            container_xml = z.read("META-INF/container.xml")
            soup = BeautifulSoup(container_xml, "xml")
            rootfile = soup.find("rootfile")
            if not rootfile or not rootfile.get("full-path"):
                return False
            opf_path = rootfile.get("full-path")
            
            # 2. Read OPF file and inspect version
            opf_content = z.read(opf_path).decode("utf-8", errors="replace")
            # Fast check for version="2.0" or package version
            if 'version="2.0"' in opf_content or "version='2.0'" in opf_content:
                return True
            if 'version="3.0"' in opf_content or "version='3.0'" in opf_content:
                return False
            return True
    except Exception as e:
        logger.warning(f"Failed to check EPUB version for {epub_path}: {e}")
        return False


def upgrade_epub2_to_epub3(source_epub: Path, target_epub: Path) -> Path:
    """
    Surgically upgrades an EPUB 2 file to EPUB 3 without mangling XML namespaces:
    - Updates package version="2.0" to version="3.0"
    - Adds xmlns:epub="http://www.idpf.org/2007/ops" to <package>
    - Extracts TOC from NCX and writes a valid EPUB 3 nav.xhtml document
    - Registers nav.xhtml in the <manifest> with properties="nav"
    - Preserves all original XML structure and <metadata> elements intact.
    """
    source_epub = Path(source_epub)
    target_epub = Path(target_epub)
    target_epub.parent.mkdir(parents=True, exist_ok=True)

    temp_dir = target_epub.parent / f"temp_epub_upgrade_{target_epub.stem}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Extract source EPUB
        with zipfile.ZipFile(source_epub, "r") as z:
            z.extractall(temp_dir)

        # 2. Locate OPF file from META-INF/container.xml
        container_file = temp_dir / "META-INF" / "container.xml"
        if not container_file.exists():
            raise RuntimeError(f"Invalid EPUB: META-INF/container.xml not found in {source_epub}")

        container_soup = BeautifulSoup(container_file.read_text(encoding="utf-8", errors="replace"), "xml")
        rootfile = container_soup.find("rootfile")
        if not rootfile or not rootfile.get("full-path"):
            raise RuntimeError(f"Invalid EPUB: rootfile not found in container.xml")

        opf_rel_path = rootfile["full-path"]
        opf_file = temp_dir / opf_rel_path
        opf_dir = opf_file.parent

        raw_opf = opf_file.read_text(encoding="utf-8", errors="replace")

        # 3. Extract Table of Contents from NCX if present
        toc_entries = []
        ncx_match = re.search(r'<item[^>]*href=["\']([^"\']+\.ncx)["\']', raw_opf, re.IGNORECASE)
        if ncx_match:
            ncx_rel = ncx_match.group(1)
            ncx_file = opf_dir / ncx_rel
            if ncx_file.exists():
                try:
                    ncx_soup = BeautifulSoup(ncx_file.read_text(encoding="utf-8", errors="replace"), "xml")
                    for np in ncx_soup.find_all("navPoint"):
                        text_tag = np.find("text")
                        content_tag = np.find("content")
                        if text_tag and content_tag and content_tag.get("src"):
                            title = text_tag.get_text().strip() or "Chapter"
                            src = content_tag["src"]
                            toc_entries.append((title, src))
                except Exception as e:
                    logger.warning(f"Could not parse NCX file {ncx_file}: {e}")

        # Fallback to spine items if NCX had no entries
        if not toc_entries:
            item_matches = re.findall(r'<item\s+[^>]*?id=["\']([^"\']+)["\'][^>]*?href=["\']([^"\']+)["\']', raw_opf)
            for item_id, item_href in item_matches:
                if item_href.endswith((".xhtml", ".html", ".htm")):
                    name = Path(item_href).stem.replace("_", " ").title()
                    toc_entries.append((name, item_href))

        if not toc_entries:
            toc_entries = [("Start", "index.xhtml")]

        # 4. Generate EPUB 3 Navigation Document (nav.xhtml)
        nav_filename = "nav.xhtml"
        nav_file = opf_dir / nav_filename

        li_elements = []
        for title, href in toc_entries:
            li_elements.append(f'        <li><a href="{href}">{title}</a></li>')
        
        nav_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
  <head>
    <title>Table of Contents</title>
    <meta charset="utf-8"/>
  </head>
  <body>
    <nav epub:type="toc" id="toc">
      <h1>Table of Contents</h1>
      <ol>
{chr(10).join(li_elements)}
      </ol>
    </nav>
  </body>
</html>"""
        nav_file.write_text(nav_content, encoding="utf-8")

        # 5. Surgically update OPF text without re-serializing with BeautifulSoup (to avoid opf: prefixing)
        upgraded_opf = raw_opf

        # Change version="2.0" to version="3.0"
        upgraded_opf = re.sub(
            r'<package\s+([^>]*?)version=[\"\']2\.0[\"\']',
            r'<package \1version="3.0"',
            upgraded_opf,
            count=1
        )
        if 'version="3.0"' not in upgraded_opf:
            upgraded_opf = re.sub(r'<package\s+', r'<package version="3.0" ', upgraded_opf, count=1)

        # Ensure xmlns:epub is declared on package
        if 'xmlns:epub' not in upgraded_opf:
            upgraded_opf = re.sub(
                r'<package\s+',
                r'<package xmlns:epub="http://www.idpf.org/2007/ops" ',
                upgraded_opf,
                count=1
            )

        # Register nav.xhtml in manifest if not present
        if 'properties="nav"' not in upgraded_opf:
            nav_item_xml = f'    <item id="nav" href="{nav_filename}" media-type="application/xhtml+xml" properties="nav"/>\n'
            # Insert right after <manifest> or <manifest ...>
            manifest_match = re.search(r'<manifest[^>]*>', upgraded_opf, re.IGNORECASE)
            if manifest_match:
                end_pos = manifest_match.end()
                upgraded_opf = upgraded_opf[:end_pos] + "\n" + nav_item_xml + upgraded_opf[end_pos:]

        # Clean any accidental opf: prefixes from standard container elements
        upgraded_opf = re.sub(r'<opf:(metadata|manifest|spine|guide|item|itemref)', r'<\1', upgraded_opf)
        upgraded_opf = re.sub(r'</opf:(metadata|manifest|spine|guide|item|itemref)>', r'</\1>', upgraded_opf)

        # Write upgraded OPF
        opf_file.write_text(upgraded_opf, encoding="utf-8")

        # 6. Re-package into target EPUB 3 zip file
        if target_epub.exists():
            target_epub.unlink()

        with zipfile.ZipFile(target_epub, "w", zipfile.ZIP_DEFLATED) as z_out:
            # Write mimetype uncompressed first per EPUB standard
            mimetype_file = temp_dir / "mimetype"
            if mimetype_file.exists():
                z_out.write(mimetype_file, "mimetype", compress_type=zipfile.ZIP_STORED)

            for root, _, files in os.walk(temp_dir):
                for file in files:
                    if file == "mimetype":
                        continue
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(temp_dir)
                    z_out.write(file_path, str(rel_path))

        logger.info(f"Successfully upgraded EPUB 2 to EPUB 3: {target_epub.name}")
        return target_epub

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
