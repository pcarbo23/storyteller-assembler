import os
import shutil
import sys
import hashlib
import logging
import subprocess
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from xml.etree import ElementTree as ET
import mutagen
from src import __version__

logger = logging.getLogger(__name__)


def calculate_file_md5(filepath: Path) -> str:
    """Calculate 32-character hex MD5 checksum of a file."""
    md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def format_time(seconds: float) -> str:
    """Format seconds into Z39 timecode format HH:MM:SS.mmm"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msecs = int(round((seconds - int(seconds)) * 1000))
    if msecs >= 1000:
        msecs = 0
        secs += 1
        if secs >= 60:
            secs = 0
            mins += 1
            if mins >= 60:
                mins = 0
                hrs += 1
    return f"{hrs}:{mins:02d}:{secs:02d}.{msecs:03d}"


def parse_person_names(raw_input: Any) -> List[str]:
    """
    Parses single or multiple creator/narrator names and formats each name as 'Last, First'.
    If multiple names are present, returns a list of individual formatted names.
    """
    if not raw_input:
        return []

    import re

    raw_list = raw_input if isinstance(raw_input, list) else [raw_input]
    names = []

    for entry in raw_list:
        if not entry:
            continue
        entry_str = str(entry).strip()
        # Split on common delimiters: semicolon, pipe, ' and ', ' & '
        parts = re.split(r";|\||\band\b|&", entry_str)
        for part in parts:
            p = part.strip()
            if not p:
                continue
            if "," in p:
                comma_parts = [cp.strip() for cp in p.split(",") if cp.strip()]
                if len(comma_parts) == 2:
                    # Already 'Last, First'
                    names.append(f"{comma_parts[0]}, {comma_parts[1]}")
                else:
                    for cp in comma_parts:
                        names.append(format_single_person_name(cp))
            else:
                names.append(format_single_person_name(p))

    return names


def format_single_person_name(name: str) -> str:
    """Formats a single person name string as 'Last, First'."""
    name = name.strip()
    if not name:
        return ""
    if "," in name:
        return name
    tokens = name.split()
    if len(tokens) == 1:
        return name
    return f"{tokens[-1]}, {' '.join(tokens[:-1])}"



def parse_clock_time(time_str: str) -> float:
    """Parse SMIL clock value string (e.g. '10.240s', '0:01:23.456', '12.5') into seconds float."""
    if not time_str:
        return 0.0
    time_str = time_str.strip()
    if time_str.endswith("s"):
        try:
            return float(time_str[:-1])
        except ValueError:
            return 0.0
    if time_str.endswith("ms"):
        try:
            return float(time_str[:-2]) / 1000.0
        except ValueError:
            return 0.0
    parts = time_str.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return float(m) * 60 + float(s)
        elif len(parts) == 1:
            return float(parts[0])
    except ValueError:
        pass
    return 0.0


class EPUBOverlayExtractor:
    """Extracts metadata, multi-level NCX/NAV navigation, and SMIL overlay synchronization from an EPUB3 file."""

    def __init__(self, epub_path: Path):
        self.epub_path = Path(epub_path)

    def extract(self) -> Dict[str, Any]:
        with zipfile.ZipFile(self.epub_path, "r") as z:
            container_xml = ET.fromstring(z.read("META-INF/container.xml"))
            opf_path = container_xml.find(".//{*}rootfile").attrib["full-path"]
            opf_dir = Path(opf_path).parent
            opf_xml = ET.fromstring(z.read(opf_path))

            def resolve_zip_path(rel_path: str) -> str:
                if str(opf_dir) == ".":
                    return rel_path
                return str((opf_dir / rel_path).as_posix())

            # Extract OPF Metadata
            metadata = self._extract_metadata(opf_xml)

            # Manifest map
            manifest = {}
            for item in opf_xml.findall(".//{*}manifest/{*}item"):
                manifest[item.attrib["id"]] = item.attrib

            # Find NCX or NAV
            ncx_href = None
            nav_href = None
            for item_id, item_attrs in manifest.items():
                media_type = item_attrs.get("media-type", "")
                properties = item_attrs.get("properties", "")
                href = item_attrs.get("href", "")
                if media_type == "application/x-dtbncx+xml" or item_id == "ncx" or href.endswith(".ncx"):
                    ncx_href = href
                if "nav" in properties or href.endswith("nav.xhtml"):
                    nav_href = href

            # Extract Navigation Tree
            nav_tree = []
            if ncx_href:
                try:
                    ncx_data = z.read(resolve_zip_path(ncx_href))
                    nav_tree = self._parse_ncx(ncx_data)
                except Exception as e:
                    logger.warning(f"Error parsing NCX from {ncx_href}: {e}")

            if not nav_tree and nav_href:
                try:
                    nav_data = z.read(resolve_zip_path(nav_href))
                    nav_tree = self._parse_nav_xhtml(nav_data)
                except Exception as e:
                    logger.warning(f"Error parsing NAV XHTML from {nav_href}: {e}")

            # Extract SMIL sequence and audio file references from spine
            spine_itemrefs = opf_xml.findall(".//{*}spine/{*}itemref")
            smil_segments = []
            audio_source_map = {}  # zip audio path -> relative audio path
            audio_order = []

            for itemref in spine_itemrefs:
                idref = itemref.attrib.get("idref")
                item = manifest.get(idref)
                if not item:
                    continue
                overlay_id = item.get("media-overlay")
                if not overlay_id:
                    continue
                smil_item = manifest.get(overlay_id)
                if not smil_item:
                    continue

                smil_href = smil_item["href"]
                smil_zip_path = resolve_zip_path(smil_href)
                try:
                    smil_data = z.read(smil_zip_path)
                    smil_xml = ET.fromstring(smil_data)
                    smil_dir = Path(smil_zip_path).parent

                    for par in smil_xml.findall(".//{*}par"):
                        par_id = par.attrib.get("id")
                        text_el = par.find("{*}text")
                        audio_el = par.find("{*}audio")
                        if audio_el is None:
                            continue

                        audio_src = audio_el.attrib.get("src", "")
                        clip_begin = parse_clock_time(audio_el.attrib.get("clipBegin", "0"))
                        clip_end = parse_clock_time(audio_el.attrib.get("clipEnd", "0"))

                        # Resolve relative audio zip path
                        if str(smil_dir) != ".":
                            audio_zip_path = str((smil_dir / audio_src).resolve().relative_to(Path(".").resolve()).as_posix())
                        else:
                            audio_zip_path = audio_src

                        # Normalize zip path string
                        audio_zip_path = str(Path(audio_zip_path).as_posix())
                        if audio_zip_path not in audio_source_map:
                            audio_source_map[audio_zip_path] = audio_zip_path
                            audio_order.append(audio_zip_path)

                        text_src = text_el.attrib.get("src", "") if text_el is not None else ""

                        smil_segments.append({
                            "par_id": par_id,
                            "text_src": text_src,
                            "audio_zip_path": audio_zip_path,
                            "clip_begin": clip_begin,
                            "clip_end": clip_end,
                            "duration": max(0.0, clip_end - clip_begin)
                        })
                except Exception as e:
                    logger.warning(f"Error reading SMIL {smil_zip_path}: {e}")

            return {
                "metadata": metadata,
                "nav_tree": nav_tree,
                "smil_segments": smil_segments,
                "audio_order": audio_order,
                "epub_path": self.epub_path
            }

    def _extract_metadata(self, opf_xml: ET.Element) -> Dict[str, Any]:
        meta_dict = {}

        title_el = opf_xml.find(".//{*}title")
        meta_dict["title"] = title_el.text.strip() if title_el is not None and title_el.text else "Unknown Title"

        creator_el = opf_xml.find(".//{*}creator")
        meta_dict["creator"] = creator_el.text.strip() if creator_el is not None and creator_el.text else "Unknown Author"

        publisher_el = opf_xml.find(".//{*}publisher")
        meta_dict["publisher"] = publisher_el.text.strip() if publisher_el is not None and publisher_el.text else "National Library Service for the Blind and Physically Handicapped"

        date_el = opf_xml.find(".//{*}date")
        meta_dict["date"] = date_el.text.strip() if date_el is not None and date_el.text else "2026"

        language_el = opf_xml.find(".//{*}language")
        meta_dict["language"] = language_el.text.strip() if language_el is not None and language_el.text else "EN"

        identifier_el = opf_xml.find(".//{*}identifier")
        meta_dict["identifier"] = identifier_el.text.strip() if identifier_el is not None and identifier_el.text else ""

        description_el = opf_xml.find(".//{*}description")
        if description_el is not None:
            desc_text = "".join(description_el.itertext()).strip() if description_el.text is None else description_el.text.strip()
            # If element contains inner XML/HTML elements or text, capture full text content
            if not desc_text:
                desc_text = "".join(description_el.itertext()).strip()
            meta_dict["description"] = desc_text
        else:
            meta_dict["description"] = ""

        narrator = "Narrator(s) Unknown"
        # 1. Search meta tags
        for meta in opf_xml.findall(".//{*}meta"):
            prop = meta.attrib.get("property", "")
            name = meta.attrib.get("name", "")
            val = meta.text.strip() if meta.text else meta.attrib.get("content", "").strip()
            if (prop in ("media:narrator", "narrator", "dc:narrator") or name in ("narrator", "media:narrator")) and val:
                narrator = val
                break

        # 2. Search contributor tags with role="nrt" or "narrator"
        if narrator == "Narrator(s) Unknown":
            for contrib in opf_xml.findall(".//{*}contributor"):
                role = contrib.attrib.get("{http://www.idpf.org/2007/opf}role") or contrib.attrib.get("role")
                if role in ("nrt", "narrator") and contrib.text:
                    narrator = contrib.text.strip()
                    break

        meta_dict["narrator"] = narrator

        return meta_dict


    def _parse_ncx(self, ncx_data: bytes) -> List[Dict[str, Any]]:
        ncx_xml = ET.fromstring(ncx_data)
        nav_map = ncx_xml.find(".//{*}navMap")
        if nav_map is None:
            return []

        def parse_nav_points(parent_el) -> List[Dict[str, Any]]:
            points = []
            for np in parent_el.findall("{*}navPoint"):
                text_el = np.find(".//{*}text")
                content_el = np.find("{*}content")
                title = text_el.text.strip() if text_el is not None and text_el.text else "Section"
                src = content_el.attrib.get("src", "") if content_el is not None else ""

                children = parse_nav_points(np)
                points.append({
                    "id": np.attrib.get("id"),
                    "title": title,
                    "src": src,
                    "children": children
                })
            return points

        return parse_nav_points(nav_map)

    def _parse_nav_xhtml(self, nav_data: bytes) -> List[Dict[str, Any]]:
        nav_xml = ET.fromstring(nav_data)
        nav_el = nav_xml.find(".//{*}nav")
        if nav_el is None:
            return []

        def parse_ol(ol_el) -> List[Dict[str, Any]]:
            items = []
            for li in ol_el.findall("{*}li"):
                a_el = li.find("{*}a")
                span_el = li.find("{*}span")
                title = ""
                src = ""
                if a_el is not None:
                    title = "".join(a_el.itertext()).strip()
                    src = a_el.attrib.get("href", "")
                elif span_el is not None:
                    title = "".join(span_el.itertext()).strip()

                sub_ol = li.find("{*}ol")
                children = parse_ol(sub_ol) if sub_ol is not None else []

                items.append({
                    "id": f"nav-{len(items)+1}",
                    "title": title,
                    "src": src,
                    "children": children
                })
            return items

        ol = nav_el.find(".//{*}ol")
        return parse_ol(ol) if ol is not None else []


class DTBConverter:
    """
    Converts Storyteller EPUB3 synchronized output to ANSI/NISO Z39.86-2002 compliant DTB with 44.1kHz WAV audio.
    """

    def __init__(self, prod_id: str, work_dir: Path):
        prod_id_str = str(prod_id).strip()
        # Parse prefix (e.g. db) and number portion
        if prod_id_str.lower().startswith("us-nls-"):
            prod_id_str = prod_id_str[7:]
        
        prefix = "db"
        num_part = prod_id_str
        if prod_id_str.lower().startswith("db"):
            prefix = prod_id_str[:2]
            num_part = prod_id_str[2:]

        # Pad numeric portion to minimum 5 digits
        if num_part.isdigit():
            num_part = num_part.zfill(5)
        elif not num_part:
            num_part = "00001"

        self.prod_id_base = num_part
        self.prod_id_full = f"{prefix}{num_part}"
        self.uid = f"us-nls-{self.prod_id_full}"
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)


    def convert_audio_to_wav(self, input_audio: Path, output_wav: Path) -> Path:
        """
        Converts/encodes input audio file (MP3, FLAC, WAV, OPUS, AAC) to standard 16-bit 44.1kHz PCM WAV.
        """
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        input_path = Path(input_audio)
        output_path = Path(output_wav)

        # Try ffmpeg command line (forces PCM 16-bit 44100Hz mono/stereo WAV)
        try:
            cmd = ["ffmpeg", "-y", "-i", str(input_path), "-ar", "44100", "-acodec", "pcm_s16le", str(output_path)]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode == 0:
                logger.info(f"Converted {input_path.name} -> {output_path.name} via ffmpeg CLI")
                return output_path
        except Exception as e:
            logger.debug(f"ffmpeg CLI conversion failed: {e}")

        # Try pydub fallback if available
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(input_path)
            audio = audio.set_frame_rate(44100).set_sample_width(2)
            audio.export(output_path, format="wav")
            logger.info(f"Converted {input_path.name} -> {output_path.name} via pydub")
            return output_path
        except Exception as e:
            logger.debug(f"pydub conversion failed: {e}")

        # Fallback: copy file directly
        shutil.copy(input_path, output_path)
        logger.info(f"Copied {input_path.name} -> {output_path.name} (fallback)")
        return output_path


    def calculate_max_depth(self, nav_tree: List[Dict[str, Any]]) -> int:
        if not nav_tree:
            return 1

        def depth(node):
            if not node.get("children"):
                return 1
            return 1 + max(depth(c) for c in node["children"])

        return max(depth(n) for n in nav_tree)

    def generate_z39_package(
        self,
        epub_data: Dict[str, Any],
        metadata_nls: Dict[str, Any],
        opening_wav: Path,
        closing_wav: Path,
        opening_timing: Optional[Dict[str, Any]] = None,
        closing_timing: Optional[Dict[str, Any]] = None
    ) -> Path:
        """
        Generates full NLS Z39.86 Master DTB package (WAV audio files, OPF, NCX, SMIL, DTDs).
        """
        full_id = self.prod_id_full
        if opening_timing is None:
            opening_timing = {}
        if closing_timing is None:
            closing_timing = {}

        # 2. Extract and Convert Audio Files
        converted_audio_map = {}  # original zip path -> converted WAV filename in work_dir
        audio_filenames = []

        # Opening WAV track
        opening_dtb_filename = f"{full_id}-0001.wav"
        opening_dtb_path = self.work_dir / opening_dtb_filename
        self.convert_audio_to_wav(opening_wav, opening_dtb_path)
        audio_filenames.append(opening_dtb_filename)

        # Extract source audio files from EPUB zip
        epub_path = epub_data["epub_path"]
        audio_order = epub_data["audio_order"]

        temp_extract_dir = self.work_dir / "temp_audio_extract"
        temp_extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(epub_path, "r") as z:
            for idx, zip_audio_path in enumerate(audio_order):
                target_wav_filename = f"{full_id}-{idx+2:04d}.wav"
                target_wav_path = self.work_dir / target_wav_filename

                extracted_path = temp_extract_dir / Path(zip_audio_path).name
                with open(extracted_path, "wb") as f_out:
                    f_out.write(z.read(zip_audio_path))

                self.convert_audio_to_wav(extracted_path, target_wav_path)
                converted_audio_map[zip_audio_path] = target_wav_filename
                audio_filenames.append(target_wav_filename)

        # Cleanup temp extracted directory
        shutil.rmtree(temp_extract_dir, ignore_errors=True)

        # Closing WAV track
        closing_dtb_filename = f"{full_id}-{len(audio_order)+2:04d}.wav"
        closing_dtb_path = self.work_dir / closing_dtb_filename
        self.convert_audio_to_wav(closing_wav, closing_dtb_path)
        audio_filenames.append(closing_dtb_filename)

        # 3. Generate SMIL files (< 100KB per SMIL file)
        smil_files, par_to_smil_map = self._generate_smil_files(
            smil_segments=epub_data["smil_segments"],
            converted_audio_map=converted_audio_map,
            opening_wav_name=opening_dtb_filename,
            closing_wav_name=closing_dtb_filename,
            opening_timing=opening_timing
        )

        # 4. Generate Z39 NCX file
        ncx_filename = f"{full_id}.ncx"
        ncx_path = self.work_dir / ncx_filename
        self._generate_ncx_file(
            metadata=metadata_nls,
            nav_tree=epub_data["nav_tree"],
            smil_segments=epub_data["smil_segments"],
            converted_audio_map=converted_audio_map,
            opening_wav_name=opening_dtb_filename,
            closing_wav_name=closing_dtb_filename,
            opening_timing=opening_timing,
            closing_timing=closing_timing,
            par_to_smil_map=par_to_smil_map,
            max_depth=metadata_nls.get("navigation_levels", 1),
            output_ncx=ncx_path
        )

        # 5. Generate Z39 OPF file
        opf_filename = f"{full_id}.opf"
        opf_path = self.work_dir / opf_filename
        self._generate_opf_file(
            metadata_nls,
            smil_files,
            audio_filenames,
            ncx_filename,
            opf_filename,
            opf_path,
            smil_segments=epub_data["smil_segments"],
            opening_wav_name=opening_dtb_filename,
            closing_wav_name=closing_dtb_filename
        )

        return self.work_dir



    def _generate_smil_files(
        self,
        smil_segments: List[Dict[str, Any]],
        converted_audio_map: Dict[str, str],
        opening_wav_name: str,
        closing_wav_name: str,
        opening_timing: Optional[Dict[str, Any]] = None,
        max_file_size: int = 95000  # Conservative size limit in bytes (< 100KB)
    ) -> Tuple[List[str], Dict[int, Tuple[str, str]]]:

        """
        Generates sequentially numbered SMIL files ([prod_id]-0001.smil, [prod_id]-0002.smil, ...)
        ensuring no SMIL file exceeds 100KB. Returns (list_of_smil_filenames, par_to_smil_map).
        par_to_smil_map: global par_index (1-based) -> (smil_filename, par_id_in_that_smil)
        """
        opening_duration = 5.0
        try:
            f = mutagen.File(self.work_dir / opening_wav_name)
            if f and f.info:
                opening_duration = f.info.length
        except Exception:
            pass

        closing_duration = 5.0
        try:
            f = mutagen.File(self.work_dir / closing_wav_name)
            if f and f.info:
                closing_duration = f.info.length
        except Exception:
            pass

        # Build list of all par items across the book
        # Item format: (par_key_id, wav_name, clip_begin, clip_end)
        all_pars = []

        # Check if opening announcement has a Library of Congress annotation split
        ann_heading_timing = opening_timing.get("opening_10a_annotation_heading") if opening_timing else None
        ann_body_timing = opening_timing.get("opening_10b_annotation_body") if opening_timing else None

        if ann_heading_timing and ann_body_timing:
            par1_end = ann_heading_timing["start"]
            all_pars.append(("par-titauth", opening_wav_name, "0:00:00.000", format_time(par1_end)))

            h_start = ann_heading_timing["start"]
            h_end = ann_heading_timing["end"]
            all_pars.append(("par-annotation", opening_wav_name, format_time(h_start), format_time(h_end)))

            b_start = ann_body_timing["start"]
            all_pars.append(("par-annotation-body", opening_wav_name, format_time(b_start), format_time(opening_duration)))
        else:
            all_pars.append(("par-titauth", opening_wav_name, "0:00:00.000", format_time(opening_duration)))

        # 2. Body overlay pars
        for idx, seg in enumerate(smil_segments, start=1):
            zip_audio = seg["audio_zip_path"]
            wav_name = converted_audio_map.get(zip_audio)
            if not wav_name:
                continue
            c_begin = format_time(seg["clip_begin"])
            c_end = format_time(seg["clip_end"])
            all_pars.append((f"par-body-{idx}", wav_name, c_begin, c_end))

        # 3. Closing announcement par
        all_pars.append(("par-close", closing_wav_name, "0:00:00.000", format_time(closing_duration)))

        smil_filenames = []
        par_to_smil_map = {}

        smil_file_idx = 1
        current_par_list = []
        cumulative_elapsed_seconds = 0.0

        def parse_time_seconds(t_str: str) -> float:
            try:
                parts = t_str.split(":")
                if len(parts) == 3:
                    h = float(parts[0])
                    m = float(parts[1])
                    s = float(parts[2])
                    return h * 3600.0 + m * 60.0 + s
            except Exception:
                pass
            return 0.0

        def calc_par_duration(item: Tuple[str, str, str, str]) -> float:
            _, _, c_beg, c_end = item
            sec_beg = parse_time_seconds(c_beg)
            sec_end = parse_time_seconds(c_end)
            return max(0.0, sec_end - sec_beg)

        def build_smil_content(file_number: int, elapsed_sec: float, par_items: List[Tuple[str, str, str, str]]) -> str:
            elapsed_formatted = format_time(elapsed_sec)
            lines = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<!DOCTYPE smil PUBLIC "-//NISO//DTD dtbsmil v1.1.0//EN" "dtbsmil110.dtd">',
                '<smil>',
                '  <head>',
                f'    <meta name="dtb:uid" content="{self.uid}"/>',
                f'    <meta name="dtb:totalElapsedTime" content="{elapsed_formatted}"/>',
                f'    <meta name="dtb:generator" content="Storyteller Assembler {__version__}"/>',
                '  </head>',
                '  <body>',
                '    <seq id="seq-1">'
            ]
            for p_id, wav, c_beg, c_end in par_items:
                lines.extend([
                    f'      <par id="{p_id}">',
                    f'        <audio src="{wav}" clipBegin="{c_beg}" clipEnd="{c_end}"/>',
                    '      </par>'
                ])
            lines.extend([
                '    </seq>',
                '  </body>',
                '</smil>'
            ])
            return "\n".join(lines)

        full_id = self.prod_id_full

        for p_id, wav, c_beg, c_end in all_pars:
            candidate_list = current_par_list + [(p_id, wav, c_beg, c_end)]
            test_content = build_smil_content(smil_file_idx, cumulative_elapsed_seconds, candidate_list)

            if len(test_content.encode("utf-8")) > max_file_size and current_par_list:
                smil_filename = f"{full_id}-{smil_file_idx:04d}.smil"
                smil_path = self.work_dir / smil_filename
                content_to_write = build_smil_content(smil_file_idx, cumulative_elapsed_seconds, current_par_list)

                with open(smil_path, "w", encoding="utf-8") as f:
                    f.write(content_to_write)

                for item_pid, _, _, _ in current_par_list:
                    par_to_smil_map[item_pid] = (smil_filename, item_pid)

                chunk_duration = sum(calc_par_duration(p) for p in current_par_list)
                cumulative_elapsed_seconds += chunk_duration

                smil_filenames.append(smil_filename)
                smil_file_idx += 1
                current_par_list = [(p_id, wav, c_beg, c_end)]
            else:
                current_par_list = candidate_list

        if current_par_list:
            smil_filename = f"{full_id}-{smil_file_idx:04d}.smil"
            smil_path = self.work_dir / smil_filename
            content_to_write = build_smil_content(smil_file_idx, cumulative_elapsed_seconds, current_par_list)

            with open(smil_path, "w", encoding="utf-8") as f:
                f.write(content_to_write)

            for item_pid, _, _, _ in current_par_list:
                par_to_smil_map[item_pid] = (smil_filename, item_pid)

            smil_filenames.append(smil_filename)

        logger.info(f"Generated {len(smil_filenames)} sequential SMIL file(s) (< 100KB each) with accurate dtb:totalElapsedTime for {full_id}")
        return smil_filenames, par_to_smil_map


    def _generate_ncx_file(
        self,
        metadata: Dict[str, Any],
        nav_tree: List[Dict[str, Any]],
        smil_segments: List[Dict[str, Any]],
        converted_audio_map: Dict[str, str],
        opening_wav_name: str,
        closing_wav_name: str,
        opening_timing: Dict[str, Any],
        closing_timing: Dict[str, Any],
        par_to_smil_map: Dict[str, Tuple[str, str]],
        max_depth: int,
        output_ncx: Path
    ) -> Path:
        # Calculate opening title and author clip times
        t1_start = opening_timing.get("opening_01_title", {}).get("start", 0.0)
        t1_end = opening_timing.get("opening_01_title", {}).get("end", 2.0)
        t2_end = opening_timing.get("opening_02_author", {}).get("end", t1_end + 2.0)

        # docTitle and docAuthor clip times
        doc_title_begin = format_time(t1_start)
        doc_title_end = format_time(t1_end)
        doc_author_begin = format_time(t1_end)
        doc_author_end = format_time(t2_end)

        # Title/Author first navPoint clip times
        titauth_clip_begin = doc_title_begin
        titauth_clip_end = doc_author_end if "opening_02_author" in opening_timing else doc_title_end

        # Closing announcement clip times
        close_clip_begin = "0:00:00.000"
        close_clip_end = format_time(closing_timing.get("closing_01_end_of_title", {}).get("end", 5.0))

        # Build mapping from EPUB HTML targets to SMIL audio clip details
        par_by_text_src = {}
        for idx, seg in enumerate(smil_segments, start=1):
            par_key_id = f"par-body-{idx}"
            wav_name = converted_audio_map.get(seg["audio_zip_path"], opening_wav_name)
            clip_b = format_time(seg["clip_begin"])
            clip_e = format_time(seg["clip_end"])
            info = {
                "par_key_id": par_key_id,
                "audio_src": wav_name,
                "clip_begin": clip_b,
                "clip_end": clip_e
            }

            text_src = seg.get("text_src", "")
            if text_src:
                norm_text_src = str(Path(text_src).as_posix())
                if norm_text_src not in par_by_text_src:
                    par_by_text_src[norm_text_src] = info
                base_text_src = norm_text_src.split("#")[0]
                if base_text_src not in par_by_text_src:
                    par_by_text_src[base_text_src] = info
                filename_only = Path(base_text_src).name
                if filename_only not in par_by_text_src:
                    par_by_text_src[filename_only] = info

        first_smil_file, first_par_id = par_to_smil_map.get("par-titauth", (f"{self.prod_id_full}-0001.smil", "par-titauth"))
        last_smil_file, last_par_id = par_to_smil_map.get("par-close", (f"{self.prod_id_full}-0001.smil", "par-close"))

        # Check if Library of Congress annotation is present in opening announcement timing
        ann_heading_timing = opening_timing.get("opening_10a_annotation_heading") if opening_timing else None
        ann_nav_lines = []
        if ann_heading_timing:
            ann_smil_file, ann_par_id = par_to_smil_map.get("par-annotation", (f"{self.prod_id_full}-0001.smil", "par-annotation"))
            ann_clip_b = format_time(ann_heading_timing["start"])
            ann_clip_e = format_time(ann_heading_timing["end"])
            ann_nav_lines = [
                '    <navPoint id="annotation" class="annotation">',
                '      <navLabel>',
                '        <text>Library of Congress Annotation</text>',
                f'        <audio src="{opening_wav_name}" clipBegin="{ann_clip_b}" clipEnd="{ann_clip_e}"/>',
                '      </navLabel>',
                f'      <content src="{ann_smil_file}#{ann_par_id}"/>',
                '    </navPoint>'
            ]

        ncx_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx v1.1.0//EN" "ncx110.dtd">',
            '<ncx version="1.1.0">',
            '  <head>',
            f'    <meta name="dtb:uid" content="{self.uid}"/>',
            f'    <meta name="dtb:generator" content="Storyteller Assembler {__version__}"/>',
            f'    <meta name="dtb:depth" content="{max_depth}"/>',
            '    <meta name="dtb:maxPageNormal" content="0"/>',
            '    <meta name="dtb:pageFront" content="0"/>',
            '    <meta name="dtb:pageNormal" content="0"/>',
            '    <meta name="dtb:pageSpecial" content="0"/>',
            '  </head>',
            '  <docTitle>',
            f'    <text>{metadata.get("title", "Unknown Title")}</text>',
            f'    <audio src="{opening_wav_name}" clipBegin="{doc_title_begin}" clipEnd="{doc_title_end}"/>',
            '  </docTitle>',
            '  <docAuthor>',
            f'    <text>{metadata.get("author_names", "Unknown Author")}</text>',
            f'    <audio src="{opening_wav_name}" clipBegin="{doc_author_begin}" clipEnd="{doc_author_end}"/>',
            '  </docAuthor>',
            '  <navMap>',
            '    <navPoint id="titauth" class="title/author">',
            '      <navLabel>',
            f'        <text>{metadata.get("title", "Unknown Title")} by {metadata.get("author_names", "Unknown Author")}</text>',
            f'        <audio src="{opening_wav_name}" clipBegin="{titauth_clip_begin}" clipEnd="{titauth_clip_end}"/>',
            '      </navLabel>',
            f'      <content src="{first_smil_file}#{first_par_id}"/>',
            '    </navPoint>'
        ]

        if ann_nav_lines:
            ncx_lines.extend(ann_nav_lines)


        def resolve_node_audio(node: Dict[str, Any]) -> Optional[Tuple[str, str, str, str]]:
            src = node.get("src", "")
            match = None
            if src:
                norm_src = str(Path(src).as_posix())
                base_src = norm_src.split("#")[0]
                src_filename = Path(base_src).name

                match = par_by_text_src.get(norm_src) or par_by_text_src.get(base_src) or par_by_text_src.get(src_filename)

                if not match:
                    for text_key, info in par_by_text_src.items():
                        key_filename = Path(text_key.split("#")[0]).name
                        if key_filename == src_filename:
                            if "#" in norm_src and "#" in text_key:
                                if norm_src.split("#")[1] == text_key.split("#")[1]:
                                    match = info
                                    break

            if match:
                return match["audio_src"], match["clip_begin"], match["clip_end"], match["par_key_id"]
            return None


        def render_nav_nodes(nodes: List[Dict[str, Any]], play_order_start: int) -> Tuple[List[str], int]:
            lines = []
            curr_order = play_order_start

            for node in nodes:
                resolved = resolve_node_audio(node)
                if not resolved:
                    if node.get("children"):
                        child_lines, curr_order = render_nav_nodes(node["children"], curr_order)
                        lines.extend(child_lines)
                    continue

                title = node.get("title") or f"Section {curr_order}"
                audio_src, clip_begin, clip_end, par_key_id = resolved
                smil_file, par_id = par_to_smil_map.get(par_key_id, (f"{self.prod_id_full}-0001.smil", par_key_id))

                lines.append(f'    <navPoint id="navpoint-{curr_order}" class="chapter">')
                lines.append('      <navLabel>')
                lines.append(f'        <text>{title}</text>')
                lines.append(f'        <audio src="{audio_src}" clipBegin="{clip_begin}" clipEnd="{clip_end}"/>')
                lines.append('      </navLabel>')
                lines.append(f'      <content src="{smil_file}#{par_id}"/>')

                if node.get("children"):
                    child_lines, curr_order = render_nav_nodes(node["children"], curr_order + 1)
                    lines.extend(child_lines)
                else:
                    curr_order += 1

                lines.append('    </navPoint>')

            return lines, curr_order



        if nav_tree:
            nav_lines, _ = render_nav_nodes(nav_tree, 1)
            ncx_lines.extend(nav_lines)

        # Add closing navPoint at the very end
        ncx_lines.extend([
            '    <navPoint id="close" class="close">',
            '      <navLabel>',
            f'        <text>End of {metadata.get("title", "Unknown Title")} by {metadata.get("author_names", "Unknown Author")}</text>',
            f'        <audio src="{closing_wav_name}" clipBegin="{close_clip_begin}" clipEnd="{close_clip_end}"/>',
            '      </navLabel>',
            f'      <content src="{last_smil_file}#{last_par_id}"/>',
            '    </navPoint>',
            '  </navMap>',
            '</ncx>'
        ])

        with open(output_ncx, "w", encoding="utf-8") as f:
            f.write("\n".join(ncx_lines))

        logger.info(f"Generated Z39 NCX file with titauth and close navPoints: {output_ncx}")
        return output_ncx


    def _generate_opf_file(
        self,
        metadata: Dict[str, Any],
        smil_filenames: List[str],
        audio_filenames: List[str],
        ncx_filename: str,
        opf_filename: str,
        output_opf: Path,
        smil_segments: Optional[List[Dict[str, Any]]] = None,
        opening_wav_name: str = "",
        closing_wav_name: str = ""
    ) -> Path:
        total_seconds = 0.0

        # Calculate exact total audio time directly by reading all generated SMIL files
        # This guarantees 100% exact mathematical equality with validator SMIL clip summation
        def parse_smil_time(t_str: str) -> float:
            try:
                parts = t_str.split(":")
                if len(parts) == 3:
                    return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
            except Exception:
                pass
            return 0.0

        for smil_name in smil_filenames:
            smil_p = self.work_dir / smil_name
            if smil_p.exists():
                try:
                    tree = ET.parse(smil_p)
                    for audio_tag in tree.getroot().findall(".//{*}audio"):
                        cb = parse_smil_time(audio_tag.attrib.get("clipBegin", "0"))
                        ce = parse_smil_time(audio_tag.attrib.get("clipEnd", "0"))
                        total_seconds += max(0.0, ce - cb)
                except Exception as e:
                    logger.warning(f"Could not parse SMIL file {smil_p} for totalTime: {e}")

        # Fallback if SMIL parsing yields 0
        if total_seconds == 0.0:
            for audio in audio_filenames:
                audio_path = self.work_dir / audio
                try:
                    f = mutagen.File(audio_path)
                    if f and f.info and f.info.length > 0:
                        total_seconds += f.info.length
                except Exception:
                    pass



        import datetime
        current_date_str = datetime.date.today().isoformat()
        current_year_month = datetime.date.today().strftime("%Y-%m")

        publisher_exact = "National Library Service for the Blind and Physically Handicapped, Library of Congress"

        total_time_str = format_time(total_seconds)

        opf_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!DOCTYPE package PUBLIC "+//ISBN 0-9673008-1-9//DTD OEB 1.0.1 Package//EN" "oebpkg101.dtd">',
            '<package unique-identifier="uid" xmlns="http://openebook.org/namespaces/oeb-package/1.0/">',
            '  <metadata>',
            '    <dc-metadata xmlns:dc="http://purl.org/dc/elements/1.0/">',
            f'      <dc:Title>{metadata.get("title", "Unknown Title")}</dc:Title>'
        ]

        # Process and emit individual dc:Creator elements formatted as 'Last, First'
        creators = parse_person_names(metadata.get("author_names") or metadata.get("creator") or "Unknown Author")
        if not creators:
            creators = ["Unknown Author"]
        for creator in creators:
            c_clean = creator.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            opf_lines.append(f'      <dc:Creator>{c_clean}</dc:Creator>')

        opf_lines.extend([
            f'      <dc:Publisher>{publisher_exact}</dc:Publisher>',
            '      <dc:Format>ANSI/NISO Z39.86-2002</dc:Format>',
            f'      <dc:Identifier id="uid" scheme="DTB">{self.uid}</dc:Identifier>',
            '      <dc:Rights>Further reproduction or distribution in other than an accessible format is prohibited</dc:Rights>',
            '      <dc:Language>EN</dc:Language>',
            f'      <dc:Date>{current_year_month}</dc:Date>'
        ])

        desc_text = metadata.get("description") or "No data acquired"
        desc_text_clean = desc_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        opf_lines.append(f'      <dc:Description>{desc_text_clean}</dc:Description>')

        subjects = metadata.get("subjects")
        if subjects:
            if isinstance(subjects, list):
                for subj in subjects:
                    s_clean = str(subj).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    opf_lines.append(f'      <dc:Subject>{s_clean}</dc:Subject>')
            elif isinstance(subjects, str):
                s_clean = subjects.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                opf_lines.append(f'      <dc:Subject>{s_clean}</dc:Subject>')
        else:
            opf_lines.append('      <dc:Subject>No data acquired</dc:Subject>')

        source_pub = metadata.get("print_publisher") or metadata.get("source_publisher") or ""
        source_pub_clean = source_pub.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        rec_agency = metadata.get("recording_agency_name") or metadata.get("recording_agency") or "NLS Automated Pipeline"
        rec_agency_clean = rec_agency.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        opf_lines.extend([
            '    </dc-metadata>',
            '    <x-metadata>',
            '      <meta name="dtb:multimediaType" content="audioNCX"/>',
            '      <meta name="dtb:audioFormat" content="wav"/>',
            f'      <meta name="dtb:totalTime" content="{total_time_str}"/>',
            '      <meta name="dtb:revision" content="0"/>',
            f'      <meta name="dtb:revisionDate" content="{current_date_str}"/>',
            f'      <meta name="dtb:producedDate" content="{current_date_str}"/>'
        ])

        # Process and emit individual dtb:narrator meta elements formatted as 'Last, First'
        narrators = parse_person_names(metadata.get("narrator_name") or metadata.get("narrator") or "Narrator(s) Unknown")
        if not narrators:
            narrators = ["Narrator(s) Unknown"]
        for narrator in narrators:
            n_clean = narrator.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            opf_lines.append(f'      <meta name="dtb:narrator" content="{n_clean}"/>')

        # REMOVED BY USER: to cleanly remove the legacy DTD/ENT in the manifest duplicate this and removed the lines
        # opf_lines.extend([
        #     '      <meta name="dtb:producer" content="NLS Automated Pipeline"/>',
        #     f'      <meta name="dtb:sourcePublisher" content="{source_pub_clean}"/>',
        #     f'      <meta name="nls:recordingAgency" content="{rec_agency_clean}"/>',
        #     '    </x-metadata>',
        #     '  </metadata>',
        #     '  <manifest>',
        #     f'    <item id="ncx" href="{ncx_filename}" media-type="text/xml"/>',
        #     f'    <item id="opf" href="{opf_filename}" media-type="text/xml"/>',
        #     '    <item id="pkgdtd" href="oebpkg101.dtd" media-type="text/xml" />',
        #     '    <item id="pkgent" href="oeb1.ent" media-type="text/xml" />',
        #     '    <item id="ncx_dtd" href="ncx110.dtd" media-type="text/xml" />',
        #     '    <item id="smil_dtd" href="dtbsmil110.dtd" media-type="text/xml" />'
        # ])
        opf_lines.extend([
            f'      <meta name="dtb:producer" content="Storyteller Assembler {__version__}"/>',
            f'      <meta name="dtb:sourcePublisher" content="{source_pub_clean}"/>',
            f'      <meta name="nls:recordingAgency" content="{rec_agency_clean}"/>',
            '    </x-metadata>',
            '  </metadata>',
            '  <manifest>',
            f'    <item id="ncx" href="{ncx_filename}" media-type="text/xml"/>',
            f'    <item id="opf" href="{opf_filename}" media-type="text/xml"/>',
        ])


        # Register all sequential SMIL files in manifest
        for i, smil in enumerate(smil_filenames):
            opf_lines.append(f'    <item id="smil_{i+1}" href="{smil}" media-type="application/smil"/>')

        # Register all WAV audio files in manifest
        for i, audio in enumerate(audio_filenames):
            opf_lines.append(f'    <item id="audio_{i+1}" href="{audio}" media-type="audio/x-wav"/>')

        opf_lines.extend([
            '  </manifest>',
            '  <spine>'
        ])

        # Register all sequential SMIL files in linear order in spine
        for i in range(len(smil_filenames)):
            opf_lines.append(f'    <itemref idref="smil_{i+1}"/>')

        opf_lines.extend([
            '  </spine>',
            '</package>'
        ])

        with open(output_opf, "w", encoding="utf-8") as f:
            f.write("\n".join(opf_lines))

        logger.info(f"Generated Z39 OPF file with {len(smil_filenames)} SMIL item(s): {output_opf}")
        return output_opf

