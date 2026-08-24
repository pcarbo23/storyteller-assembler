import zipfile
import re
from pathlib import Path
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import pytest

from src.epub_nls_editor import NLSEPUBEditor, NLS_PREFIX_URL, DEFAULT_GENERATOR


def test_edit_aligned_epub_real_sample(tmp_path):
    """Test NLSEPUBEditor on a real Storyteller aligned EPUB from data/processing."""
    source_epub = Path("data/processing/db100000_aligned.epub")
    if not source_epub.exists():
        pytest.skip(f"Test sample {source_epub} not found.")

    output_epub = tmp_path / "db100000.epub"
    editor = NLSEPUBEditor()
    
    fixed_time = datetime(2026, 8, 20, 15, 30, 0, tzinfo=timezone.utc)
    res = editor.edit_aligned_epub(
        input_epub=source_epub,
        output_epub=output_epub,
        prod_id="db100000",
        modified_time=fixed_time
    )

    assert res == output_epub
    assert output_epub.exists()

    # 1. Verify ZIP container format (mimetype first and uncompressed)
    with zipfile.ZipFile(output_epub, "r") as z:
        infolist = z.infolist()
        assert len(infolist) > 0
        first_item = infolist[0]
        assert first_item.filename == "mimetype"
        assert first_item.compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype").decode("utf-8").strip() == "application/epub+zip"

        # 2. Verify container.xml points to original OPF path
        container_xml = z.read("META-INF/container.xml")
        csoup = BeautifulSoup(container_xml, "xml")
        rootfile = csoup.find("rootfile")
        assert rootfile is not None
        opf_path = rootfile["full-path"]
        assert opf_path.endswith(".opf")

        # 3. Verify OPF content
        opf_data = z.read(opf_path).decode("utf-8")
        soup = BeautifulSoup(opf_data, "xml")

        # Package element checks
        pkg = soup.find("package")
        assert pkg["version"] == "3.0"
        assert pkg["unique-identifier"] == "nls-id"
        assert f"nls: {NLS_PREFIX_URL}" in pkg["prefix"]
        assert "http://www.idpf.org/2007/ops" in pkg.get("xmlns:epub", "")

        # Identifiers
        nls_id = soup.find(lambda tag: tag.name.endswith("identifier") and tag.get("id") == "nls-id")
        assert nls_id is not None
        assert nls_id.string == "us-nls-db100000"

        # Source identifier remains
        source_id = soup.find(lambda tag: tag.name.endswith("identifier") and tag.get("id") == "uid")
        assert source_id is not None
        assert source_id.string == "9781250386410"

        # Source UID refinement meta
        src_refine = soup.find(
            lambda tag: tag.name.endswith("meta")
            and tag.get("refines") == "#uid"
            and tag.get("property") == "identifier-type"
        )
        assert src_refine is not None
        assert src_refine.string == "UID of the source EPUB"

        # Modified date meta (exactly one, ISO 8601 extended format)
        mod_tags = soup.find_all(lambda tag: tag.name.endswith("meta") and tag.get("property") == "dcterms:modified")
        assert len(mod_tags) == 1
        assert mod_tags[0].string == "2026-08-20T15:30:00Z"

        # Generator meta
        gen_tag = soup.find(lambda tag: tag.name.endswith("meta") and tag.get("property") == "nls:generator")
        assert gen_tag is not None
        assert gen_tag.string == DEFAULT_GENERATOR

        # Media Overlay metadata preserved
        dur_tags = soup.find_all(lambda tag: tag.name.endswith("meta") and tag.get("property") == "media:duration")
        assert len(dur_tags) >= 1

        active_class = soup.find(lambda tag: tag.name.endswith("meta") and tag.get("property") == "media:active-class")
        assert active_class is not None
        assert active_class.string == "-epub-media-overlay-active"

        # 4. Verify NCX dtb:uid matches NLS OPF identifier
        ncx_files = [f for f in z.namelist() if f.endswith(".ncx")]
        if ncx_files:
            for ncx_name in ncx_files:
                ncx_data = z.read(ncx_name).decode("utf-8")
                nsoup = BeautifulSoup(ncx_data, "xml")
                uid_meta = nsoup.find(lambda tag: tag.name == "meta" and tag.get("name", "").lower() == "dtb:uid")
                assert uid_meta is not None
                assert uid_meta.get("content") == "us-nls-db100000"


def test_edit_epub_with_no_source_id_attribute(tmp_path):
    """Test when source EPUB has a dc:identifier with no id attribute."""
    synth_dir = tmp_path / "synth_epub"
    synth_dir.mkdir()
    (synth_dir / "META-INF").mkdir()
    (synth_dir / "OEBPS").mkdir()

    (synth_dir / "mimetype").write_text("application/epub+zip")
    (synth_dir / "META-INF" / "container.xml").write_text("""<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles>
<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles>
</container>""")

    (synth_dir / "OEBPS" / "content.opf").write_text("""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="BookId">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Synthetic Test Book</dc:title>
    <dc:identifier>9780000000000</dc:identifier>
  </metadata>
  <manifest>
    <item id="item1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="item1"/>
  </spine>
</package>""")

    (synth_dir / "OEBPS" / "toc.ncx").write_text("""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="9780000000000"/>
    <meta name="dtb:depth" content="1"/>
  </head>
  <docTitle><text>Synthetic Test Book</text></docTitle>
  <navMap>
    <navPoint id="np1" playOrder="1">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="chapter1.xhtml"/>
    </navPoint>
  </navMap>
</ncx>""")

    synth_epub = tmp_path / "synth_raw.epub"
    with zipfile.ZipFile(synth_epub, "w") as z:
        z.write(synth_dir / "mimetype", "mimetype")
        z.write(synth_dir / "META-INF" / "container.xml", "META-INF/container.xml")
        z.write(synth_dir / "OEBPS" / "content.opf", "OEBPS/content.opf")
        z.write(synth_dir / "OEBPS" / "toc.ncx", "OEBPS/toc.ncx")

    out_epub = tmp_path / "db100099.epub"
    editor = NLSEPUBEditor(generator_name="Custom Assembler 2.0")
    editor.edit_aligned_epub(synth_epub, out_epub, "db100099")

    with zipfile.ZipFile(out_epub, "r") as z:
        soup = BeautifulSoup(z.read("OEBPS/content.opf"), "xml")
        
        # Check that unique-identifier is nls-id
        pkg = soup.find("package")
        assert pkg["unique-identifier"] == "nls-id"
        assert pkg["version"] == "3.0"

        # Check NLS identifier
        nls_id = soup.find(lambda tag: tag.name.endswith("identifier") and tag.get("id") == "nls-id")
        assert nls_id.string == "us-nls-db100099"

        # Check source identifier got an id assigned
        source_id = soup.find(lambda tag: tag.name.endswith("identifier") and tag.string == "9780000000000")
        assert source_id is not None
        assigned_id = source_id.get("id")
        assert assigned_id is not None

        # Check refines points to the assigned id
        refine_meta = soup.find(
            lambda tag: tag.name.endswith("meta")
            and tag.get("refines") == f"#{assigned_id}"
            and tag.get("property") == "identifier-type"
        )
        assert refine_meta is not None
        assert refine_meta.string == "UID of the source EPUB"

        # Check NCX dtb:uid
        ncx_soup = BeautifulSoup(z.read("OEBPS/toc.ncx"), "xml")
        uid_meta = ncx_soup.find(lambda tag: tag.name == "meta" and tag.get("name", "").lower() == "dtb:uid")
        assert uid_meta is not None
        assert uid_meta.get("content") == "us-nls-db100099"


def test_smil_manifest_and_metadata_spine_ordering(tmp_path):
    """
    Test that SMIL manifest items and media:duration metadata elements are reordered
    to strictly match the linear reading order defined by the spine (epub_MED_015 compliance).
    """
    sample_epub = Path("data/processing/db100033_aligned.epub")
    if not sample_epub.exists():
        sample_epub = Path("data/processing/db100001_aligned.epub")
    if not sample_epub.exists():
        pytest.skip("No out-of-order sample EPUB available.")

    out_epub = tmp_path / "db100033.epub"
    editor = NLSEPUBEditor()
    editor.edit_aligned_epub(sample_epub, out_epub, "db100033")

    with zipfile.ZipFile(out_epub, "r") as z:
        # Locate OPF
        container_xml = z.read("META-INF/container.xml")
        csoup = BeautifulSoup(container_xml, "xml")
        opf_path = csoup.find("rootfile")["full-path"]
        
        soup = BeautifulSoup(z.read(opf_path), "xml")
        manifest = soup.find("manifest")
        spine = soup.find("spine")

        manifest_items_by_id = {it.get("id"): it for it in manifest.find_all("item") if it.get("id")}
        spine_idrefs = [itemref.get("idref") for itemref in spine.find_all("itemref") if itemref.get("idref")]

        expected_smil_order = []
        for idref in spine_idrefs:
            item = manifest_items_by_id.get(idref)
            if item and item.get("media-overlay"):
                ov_id = item.get("media-overlay")
                if ov_id and ov_id not in expected_smil_order:
                    expected_smil_order.append(ov_id)

        # 1. Verify manifest SMIL order matches expected spine reading order
        actual_smil_order = [it.get("id") for it in manifest.find_all("item") if it.get("media-type") == "application/smil+xml"]
        assert actual_smil_order == expected_smil_order
        assert actual_smil_order[0] == "c001_overlay"
        assert actual_smil_order[-1] == "c037_overlay"

        # 2. Verify media:duration metadata order matches expected spine reading order
        actual_dur_metas = [
            m.get("refines", "").lstrip("#")
            for m in soup.find_all("meta")
            if m.get("property") == "media:duration" and m.get("refines")
        ]
        assert actual_dur_metas == expected_smil_order
        assert actual_dur_metas[0] == "c001_overlay"
        assert actual_dur_metas[-1] == "c037_overlay"

