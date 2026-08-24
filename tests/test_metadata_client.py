import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.external.metadata_client import extract_isbn_from_sources, BookMetadataFetcher

class TestMetadataClient(unittest.TestCase):

    def test_extract_isbn_from_folder_name(self):
        folder = Path("/test_material/Agnes Aubert's Mystical Cat Shelter-9780593973264")
        isbn = extract_isbn_from_sources(folder_path=folder)
        self.assertEqual(isbn, "9780593973264")

    def test_extract_isbn_from_audio_filenames(self):
        files = [Path("9798217279272_UA_M_1_1_1-of-40.flac")]
        isbn = extract_isbn_from_sources(file_paths=files)
        self.assertEqual(isbn, "9798217279272")

    def test_extract_isbn_from_opf_text(self):
        text = "<dc:identifier scheme='ISBN'>9780593973264</dc:identifier>"
        isbn = extract_isbn_from_sources(manifest_or_opf_text=text)
        self.assertEqual(isbn, "9780593973264")

    @patch("urllib.request.urlopen")
    def test_audnexus_fetch(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'''{
            "title": "Agnes Aubert's Mystical Cat Shelter",
            "authors": [{"name": "Agnes Aubert"}],
            "narrators": [{"name": "Jane Doe"}],
            "summary": "A mystical tale of cats.",
            "publisher": "Cat Shelter Press",
            "genres": [{"name": "Fantasy"}]
        }'''
        mock_urlopen.return_value.__enter__.return_value = mock_response

        fetcher = BookMetadataFetcher()
        meta = fetcher.fetch_audnexus_metadata("B0CSB12345")
        self.assertEqual(meta["title"], "Agnes Aubert's Mystical Cat Shelter")
        self.assertEqual(meta["narrator_name"], "Jane Doe")
        self.assertEqual(meta["print_publisher"], "Cat Shelter Press")
        self.assertEqual(meta["subjects"], ["Fantasy"])

if __name__ == "__main__":
    unittest.main()
