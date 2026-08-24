import re
import logging
import urllib.request
import urllib.parse
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def extract_isbns_from_sources(
    folder_path: Optional[Path] = None,
    file_paths: Optional[List[Path]] = None,
    manifest_or_opf_text: Optional[str] = None
) -> List[str]:
    """
    Extract all 13-digit ISBNs (starting with 978 or 979) from folder paths, filenames, or text content.
    Returns list of unique cleaned 13-digit ISBN strings in order of discovery.
    """
    isbn_pattern = re.compile(r'(97[89][0-9]{10})')
    found: List[str] = []

    def add_match(val: str):
        if val not in found:
            found.append(val)

    # 1. Search in audio or file names (highest priority for audiobook ISBNs)
    if file_paths:
        for fp in file_paths:
            for match in isbn_pattern.finditer(fp.name):
                add_match(match.group(1))

    # 2. Search in folder path
    if folder_path:
        for match in isbn_pattern.finditer(folder_path.name):
            add_match(match.group(1))

    # 3. Search in manifest or OPF XML text
    if manifest_or_opf_text:
        for match in isbn_pattern.finditer(manifest_or_opf_text):
            add_match(match.group(1))

    return found


def extract_isbn_from_sources(
    folder_path: Optional[Path] = None,
    file_paths: Optional[List[Path]] = None,
    manifest_or_opf_text: Optional[str] = None
) -> Optional[str]:
    isbns = extract_isbns_from_sources(folder_path, file_paths, manifest_or_opf_text)
    return isbns[0] if isbns else None


class BookMetadataFetcher:
    """Fetches audiobook & print metadata from Libex, Audnexus, Google Books, and Open Library APIs."""

    LIBEX_BASE_URL = "https://libexdb.com"
    AUDNEXUS_BASE_URL = "https://api.audnex.us"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def fetch_audnexus_metadata(self, isbn: str) -> Dict[str, Any]:
        """Fetch metadata from Audnexus API using ASIN or Audible ID."""
        if not isbn:
            return {}
        # Audnexus only supports 10-character Audible ASINs starting with B.
        # If the input is a 13-digit ISBN (starts with 978/979), skip Audnexus direct lookup.
        if re.match(r"^(978|979)\d{10}$", isbn):
            logger.debug(f"Skipping direct Audnexus book lookup for ISBN {isbn} (requires ASIN).")
            return {}
            
        url = f"{self.AUDNEXUS_BASE_URL}/books/{isbn}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AutoStoryPipe/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    logger.info(f"Successfully retrieved metadata from Audnexus for ISBN {isbn}")
                    return self._parse_audnexus_response(data)
        except Exception as e:
            logger.warning(f"Audnexus API call failed for ASIN/ISBN {isbn}: {e}")
        return {}

    def fetch_libex_metadata(self, isbn: str) -> Dict[str, Any]:
        """Fetch metadata from Libex API using ISBN-13 database query."""
        if not isbn:
            return {}
        url = f"{self.LIBEX_BASE_URL}/db/book?isbn={isbn}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AutoStoryPipe/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    raw_data = json.loads(resp.read().decode("utf-8"))
                    data = raw_data[0] if isinstance(raw_data, list) and raw_data else raw_data
                    if data:
                        logger.info(f"Successfully retrieved metadata from Libex for ISBN {isbn}")
                        return self._parse_libex_response(data)
        except Exception as e:
            logger.warning(f"Libex API call failed for ISBN {isbn}: {e}")
        return {}

    def search_libex_metadata(self, query: str) -> Dict[str, Any]:
        """Search Libex using a general query (ISBN, ASIN, or Title)."""
        if not query:
            return {}
        quoted_query = urllib.parse.quote(query)
        url = f"{self.LIBEX_BASE_URL}/search?query={quoted_query}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AutoStoryPipe/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    raw_data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(raw_data, list) and raw_data:
                        logger.info(f"Successfully retrieved search metadata from Libex for query '{query}'")
                        return self._parse_libex_response(raw_data[0])
        except Exception as e:
            logger.warning(f"Libex search API call failed for query '{query}': {e}")
        return {}

    def fetch_google_books_metadata(self, isbn: str) -> Dict[str, Any]:
        """Fetch metadata from Google Books API using ISBN-13."""
        if not isbn:
            return {}
        isbn_clean = isbn.replace("-", "").strip()
        url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn_clean}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AutoStoryPipe/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    items = data.get("items", [])
                    if items:
                        volume_info = items[0].get("volumeInfo", {})
                        logger.info(f"Successfully retrieved metadata from Google Books for ISBN {isbn}")
                        authors = volume_info.get("authors", [])
                        categories = volume_info.get("categories", [])
                        return {
                            "title": volume_info.get("title"),
                            "author_names": ", ".join(authors) if authors else None,
                            "description": volume_info.get("description"),
                            "print_publisher": volume_info.get("publisher"),
                            "subjects": categories if categories else None,
                        }
        except Exception as e:
            logger.warning(f"Google Books API call failed for ISBN {isbn}: {e}")
        return {}

    def fetch_open_library_metadata(self, isbn: str) -> Dict[str, Any]:
        """Fetch metadata from Open Library API using ISBN-13."""
        if not isbn:
            return {}
        isbn_clean = isbn.replace("-", "").strip()
        url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn_clean}&jscmd=data&format=json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AutoStoryPipe/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    key = f"ISBN:{isbn_clean}"
                    if key in data:
                        book_info = data[key]
                        logger.info(f"Successfully retrieved metadata from Open Library for ISBN {isbn}")
                        authors_list = [a.get("name") for a in book_info.get("authors", []) if a.get("name")]
                        subjects_list = [s.get("name") for s in book_info.get("subjects", []) if s.get("name")]
                        publishers_list = [p.get("name") for p in book_info.get("publishers", []) if p.get("name")]
                        desc = book_info.get("notes") or book_info.get("description")
                        if isinstance(desc, dict):
                            desc = desc.get("value", "")

                        return {
                            "title": book_info.get("title"),
                            "author_names": ", ".join(authors_list) if authors_list else None,
                            "description": desc,
                            "print_publisher": ", ".join(publishers_list) if publishers_list else None,
                            "subjects": subjects_list if subjects_list else None,
                        }
        except Exception as e:
            logger.warning(f"Open Library API call failed for ISBN {isbn}: {e}")
        return {}

    def _parse_audnexus_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        narrators = [n.get("name") for n in data.get("narrators", []) if isinstance(n, dict) and n.get("name")]
        authors = [a.get("name") for a in data.get("authors", []) if isinstance(a, dict) and a.get("name")]
        genres = [g.get("name") for g in data.get("genres", []) if isinstance(g, dict) and g.get("name")]

        return {
            "title": data.get("title"),
            "author_names": ", ".join(authors) if authors else None,
            "narrator_name": ", ".join(narrators) if narrators else None,
            "description": data.get("summary") or data.get("description"),
            "print_publisher": data.get("publisher"),
            "subjects": genres if genres else None,
            "recording_agency_name": data.get("publisher"),
        }

    def _parse_libex_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        narrators = [n.get("name") for n in data.get("narrators", []) if isinstance(n, dict) and n.get("name")]
        authors = [a.get("name") for a in data.get("authors", []) if isinstance(a, dict) and a.get("name")]
        genres = [g.get("name") for g in data.get("genres", []) if isinstance(g, dict) and g.get("name")]

        return {
            "title": data.get("title"),
            "author_names": ", ".join(authors) if authors else (data.get("author") or data.get("authors")),
            "narrator_name": ", ".join(narrators) if narrators else data.get("narrator"),
            "description": data.get("summary") or data.get("description"),
            "print_publisher": data.get("publisher"),
            "subjects": genres if genres else (data.get("subjects") or data.get("categories")),
            "recording_agency_name": data.get("recordingAgency") or data.get("publisher"),
        }

    def _merge_metadata(self, target: dict, source: dict) -> None:
        for k, v in source.items():
            if v and not target.get(k):
                target[k] = v

    def _is_metadata_complete(self, meta: dict) -> bool:
        return bool(meta.get("title") and meta.get("author_names") and meta.get("description"))

    def fetch_all_for_isbns(self, isbns: List[str], title: Optional[str] = None) -> Dict[str, Any]:
        """Fetch metadata for candidate ISBNs across APIs, consolidating available non-empty fields."""
        consolidated: Dict[str, Any] = {}
        for isbn in isbns:
            # 1. Try Libex Database Lookup
            libex_data = self.fetch_libex_metadata(isbn)
            self._merge_metadata(consolidated, libex_data)

            # 2. Try Libex Search using ISBN
            if not self._is_metadata_complete(consolidated):
                libex_search_data = self.search_libex_metadata(isbn)
                self._merge_metadata(consolidated, libex_search_data)

            # 3. Try Google Books API using ISBN
            if not self._is_metadata_complete(consolidated):
                google_data = self.fetch_google_books_metadata(isbn)
                self._merge_metadata(consolidated, google_data)

            # 4. Try Open Library API using ISBN
            if not self._is_metadata_complete(consolidated):
                open_lib_data = self.fetch_open_library_metadata(isbn)
                self._merge_metadata(consolidated, open_lib_data)

        # 5. Try Libex Search using Title if we still lack information
        if title and not self._is_metadata_complete(consolidated):
            title_search_data = self.search_libex_metadata(title)
            self._merge_metadata(consolidated, title_search_data)

        return consolidated

    def fetch_all(self, isbn: str) -> Dict[str, Any]:
        """Fetch metadata from Audnexus and Libex for a single ISBN."""
        return self.fetch_all_for_isbns([isbn]) if isbn else {}

