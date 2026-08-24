import os
import re
import shutil
import zipfile
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_GENERATOR = "Storyteller Assembler 1.0.0"
NLS_PREFIX_URL = "http://www.loc.gov/nls/metadata/"


class NLSEPUBEditor:
    """
    Edits and packages Storyteller read-along EPUB Media Overlay outputs to strictly conform
    to the Draft NLS EPUB Specification (08-20-2026) and EPUB 3.3 / Media Overlays 3.3.
    """

    def __init__(self, generator_name: str = DEFAULT_GENERATOR):
        self.generator_name = generator_name

    def edit_aligned_epub(
        self,
        input_epub: Path,
        output_epub: Path,
        prod_id: str,
        modified_time: Optional[datetime] = None
    ) -> Path:
        """
        Transforms an aligned EPUB into an NLS-compliant EPUB.
        
        Args:
            input_epub: Path to the Storyteller aligned EPUB.
            output_epub: Destination path for the conforming EPUB (<prod_id>.epub).
            prod_id: Production identifier (e.g. 'db100000').
            modified_time: Optional timestamp for dcterms:modified. Defaults to current UTC time.
            
        Returns:
            Path to the output conforming EPUB.
        """
        input_epub = Path(input_epub)
        output_epub = Path(output_epub)
        output_epub.parent.mkdir(parents=True, exist_ok=True)

        # Normalize prod_id (ensure lowercase prefix, e.g. db100000)
        norm_prod_id = prod_id.lower()
        if not norm_prod_id.startswith("db") and norm_prod_id.isdigit():
            norm_prod_id = f"db{norm_prod_id}"

        temp_dir = output_epub.parent / f"temp_nls_edit_{norm_prod_id}"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Extract input EPUB
            with zipfile.ZipFile(input_epub, "r") as z_in:
                z_in.extractall(temp_dir)

            # 2. Locate OPF file via META-INF/container.xml
            container_file = temp_dir / "META-INF" / "container.xml"
            if not container_file.exists():
                raise RuntimeError(f"Invalid EPUB: META-INF/container.xml not found in {input_epub}")

            container_soup = BeautifulSoup(container_file.read_text(encoding="utf-8", errors="replace"), "xml")
            rootfile = container_soup.find("rootfile")
            if not rootfile or not rootfile.get("full-path"):
                raise RuntimeError(f"Invalid EPUB: rootfile not found in container.xml")

            opf_rel_path = rootfile["full-path"]
            opf_file = temp_dir / opf_rel_path
            if not opf_file.exists():
                raise RuntimeError(f"Invalid EPUB: OPF package document not found at {opf_file}")

            # 3. Transform OPF package document
            self._transform_opf(
                opf_file=opf_file,
                prod_id=norm_prod_id,
                modified_time=modified_time or datetime.now(timezone.utc)
            )

            # 3b. Transform any NCX navigation documents to synchronize dtb:uid with NLS identifier
            self._transform_ncx(
                temp_dir=temp_dir,
                prod_id=norm_prod_id
            )

            # 4. Repackage into target EPUB container
            if output_epub.exists():
                output_epub.unlink()

            self._create_epub_container(temp_dir, output_epub)
            logger.info(f"Successfully generated NLS conforming EPUB: {output_epub}")
            return output_epub

        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _transform_opf(self, opf_file: Path, prod_id: str, modified_time: datetime) -> None:
        """Applies NLS specification transformations to the OPF content."""
        raw_opf = opf_file.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(raw_opf, "xml")

        package = soup.find("package")
        if not package:
            raise RuntimeError(f"Invalid OPF: <package> element missing in {opf_file}")

        # 1. Package Element Attributes
        old_unique_id = package.get("unique-identifier", "uid")
        package["unique-identifier"] = "nls-id"
        package["version"] = "3.0"

        # Update prefix attribute to include nls prefix
        existing_prefix = package.get("prefix", "").strip()
        nls_prefix_decl = f"nls: {NLS_PREFIX_URL}"
        if nls_prefix_decl not in existing_prefix:
            if existing_prefix:
                package["prefix"] = f"nls: {NLS_PREFIX_URL} {existing_prefix}"
            else:
                package["prefix"] = f"nls: {NLS_PREFIX_URL}"

        # Ensure xmlns:epub is present
        if not package.get("xmlns:epub"):
            package["xmlns:epub"] = "http://www.idpf.org/2007/ops"

        metadata = soup.find("metadata")
        if not metadata:
            metadata = soup.new_tag("metadata")
            package.insert(0, metadata)

        # 2. Source dc:identifier Refinement
        # Find all source identifiers
        dc_identifiers = soup.find_all(re.compile(r"^(?:dc:)?identifier$"))
        source_id_target = None

        # Look for the source identifier that matched the old unique-identifier
        for dc_id in dc_identifiers:
            if dc_id.get("id") == old_unique_id:
                source_id_target = old_unique_id
                break

        # If not found by ID, pick the first existing dc:identifier and ensure it has an id attribute
        if not source_id_target and dc_identifiers:
            first_id = dc_identifiers[0]
            if first_id.get("id"):
                source_id_target = first_id["id"]
            else:
                source_id_target = "source-uid"
                first_id["id"] = source_id_target
        elif not source_id_target:
            # Create placeholder source identifier if none existed
            source_id_target = "source-uid"
            src_tag = soup.new_tag("dc:identifier", id=source_id_target)
            src_tag.string = "urn:isbn:0000000000000"
            metadata.append(src_tag)

        # 3. Add / Update NLS dc:identifier
        nls_id_val = f"us-nls-{prod_id}"
        nls_id_tag = soup.find(lambda tag: tag.name.endswith("identifier") and tag.get("id") == "nls-id")
        if nls_id_tag:
            nls_id_tag.string = nls_id_val
        else:
            nls_id_tag = soup.new_tag("dc:identifier", id="nls-id")
            nls_id_tag.string = nls_id_val
            metadata.insert(0, nls_id_tag)

        # 4. Add / Update Meta subexpression for source UID
        # <meta refines="#<source_id>" property="identifier-type">UID of the source EPUB</meta>
        refines_selector = f"#{source_id_target}"
        existing_refine = soup.find(
            lambda tag: tag.name.endswith("meta")
            and tag.get("refines") == refines_selector
            and tag.get("property") == "identifier-type"
        )
        if existing_refine:
            existing_refine.string = "UID of the source EPUB"
        else:
            uid_meta = soup.new_tag("meta", refines=refines_selector, property="identifier-type")
            uid_meta.string = "UID of the source EPUB"
            metadata.append(uid_meta)

        # 5. Add / Update Release Identifier (dcterms:modified)
        # Formatted as ISO 8601-1 extended: YYYY-MM-DDThh:mm:ssZ
        utc_timestamp = modified_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Remove any existing dcterms:modified tags to guarantee exactly one
        for mod_tag in soup.find_all(lambda tag: tag.name.endswith("meta") and tag.get("property") == "dcterms:modified"):
            mod_tag.decompose()

        mod_meta = soup.new_tag("meta", property="dcterms:modified")
        mod_meta.string = utc_timestamp
        metadata.append(mod_meta)

        # 6. Production Software Generator
        # <meta property="nls:generator">Software Name Version</meta>
        for gen_tag in soup.find_all(lambda tag: tag.name.endswith("meta") and tag.get("property") == "nls:generator"):
            gen_tag.decompose()

        gen_meta = soup.new_tag("meta", property="nls:generator")
        gen_meta.string = self.generator_name
        metadata.append(gen_meta)

        # 7. Media Overlays Active Class (if missing)
        active_class = soup.find(lambda tag: tag.name.endswith("meta") and tag.get("property") == "media:active-class")
        if not active_class:
            active_meta = soup.new_tag("meta", property="media:active-class")
            active_meta.string = "-epub-media-overlay-active"
            metadata.append(active_meta)

        # 8. Synchronize Manifest and Spine & Reorder Media Overlays Metadata (epub_MED_015 compliance)
        # Determine the chronological linear reading order of SMIL overlays from <spine>
        manifest = soup.find("manifest")
        spine = soup.find("spine")
        if manifest and spine:
            manifest_items_by_id = {it.get("id"): it for it in manifest.find_all("item") if it.get("id")}
            spine_idrefs = [itemref.get("idref") for itemref in spine.find_all("itemref") if itemref.get("idref")]

            ordered_smil_ids = []
            for idref in spine_idrefs:
                item = manifest_items_by_id.get(idref)
                if item and item.get("media-overlay"):
                    ov_id = item.get("media-overlay")
                    if ov_id and ov_id not in ordered_smil_ids:
                        ordered_smil_ids.append(ov_id)

            # Include any other SMIL items present in manifest not directly referenced in spine
            smil_items = [it for it in manifest.find_all("item") if it.get("media-type") == "application/smil+xml"]
            for it in smil_items:
                sid = it.get("id")
                if sid and sid not in ordered_smil_ids:
                    ordered_smil_ids.append(sid)

            # Reorder SMIL items in <manifest> in exact spine reading order
            if smil_items and ordered_smil_ids:
                smil_items_by_id = {it.get("id"): it for it in smil_items if it.get("id")}
                for it in smil_items:
                    it.extract()
                for sid in ordered_smil_ids:
                    if sid in smil_items_by_id:
                        manifest.append(smil_items_by_id[sid])

            # Reorder media:duration metadata tags to match the exact same chronological reading order
            dur_metas = soup.find_all(lambda tag: tag.name.endswith("meta") and tag.get("property") == "media:duration")
            if dur_metas and ordered_smil_ids:
                total_dur_meta = None
                dur_by_overlay_id = {}
                for dm in dur_metas:
                    refines = dm.get("refines")
                    if refines:
                        clean_ref = refines.lstrip("#")
                        dur_by_overlay_id[clean_ref] = dm
                    else:
                        total_dur_meta = dm
                    dm.extract()

                for sid in ordered_smil_ids:
                    if sid in dur_by_overlay_id:
                        metadata.append(dur_by_overlay_id[sid])

                if total_dur_meta:
                    metadata.append(total_dur_meta)

        # Write clean transformed OPF
        opf_file.write_text(str(soup), encoding="utf-8")

    def _transform_ncx(self, temp_dir: Path, prod_id: str) -> None:
        """
        Updates the dtb:uid meta element in any NCX documents in the EPUB to match
        the NLS OPF unique identifier (us-nls-<prod_id>).
        """
        nls_uid_val = f"us-nls-{prod_id}"
        ncx_files = list(temp_dir.glob("**/*.ncx"))
        for ncx_file in ncx_files:
            try:
                raw_ncx = ncx_file.read_text(encoding="utf-8", errors="replace")
                soup = BeautifulSoup(raw_ncx, "xml")

                head = soup.find("head")
                if not head:
                    head = soup.new_tag("head")
                    ncx_root = soup.find("ncx")
                    if ncx_root:
                        ncx_root.insert(0, head)
                    else:
                        soup.append(head)

                # Look for meta dtb:uid
                uid_meta = head.find(lambda tag: tag.name == "meta" and tag.get("name", "").lower() == "dtb:uid")
                if uid_meta:
                    uid_meta["content"] = nls_uid_val
                else:
                    new_meta = soup.new_tag("meta", attrs={"name": "dtb:uid", "content": nls_uid_val})
                    head.insert(0, new_meta)

                ncx_file.write_text(str(soup), encoding="utf-8")
                logger.info(f"Updated NCX dtb:uid to '{nls_uid_val}' in {ncx_file.name}")
            except Exception as e:
                logger.warning(f"Could not transform NCX file {ncx_file}: {e}")

    def _create_epub_container(self, source_dir: Path, output_epub: Path) -> None:
        """Zips source_dir into an EPUB container conforming strictly to OCF specifications."""
        with zipfile.ZipFile(output_epub, "w", zipfile.ZIP_DEFLATED) as z_out:
            # 1. Write mimetype uncompressed first at byte offset 0
            mimetype_path = source_dir / "mimetype"
            if mimetype_path.exists():
                z_out.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
            else:
                z_out.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

            # 2. Write all other files with standard deflate compression
            for root, _, files in os.walk(source_dir):
                for file in files:
                    if file == "mimetype" or file == ".DS_Store":
                        continue
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(source_dir)
                    z_out.write(file_path, str(rel_path), compress_type=zipfile.ZIP_DEFLATED)
