"""
Unit and Integration Tests for Phase 3.5 Vault Archive Operations and Document Extraction/Creation
"""

import os
import io
import shutil
import tempfile
import zipfile
import tarfile
import unittest

from agent.vault_service import VaultService, VaultAccessError


class TestVaultArchivesAndDocuments(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="nexus_vault_phase35_")
        self.vault = VaultService(agent_vault_root=self.test_dir)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_archive_list_and_extract_zip(self):
        # Create test zip file
        zip_path = os.path.join(self.test_dir, "sample.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("notes/syllabus.txt", "Cryptography Syllabus Content")
            zf.writestr("notes/lab1.txt", "Lab 1 Instructions")

        # 1. Test vault.archive_list
        list_res = self.vault.archive_list("admin", {"path": "sample.zip"})
        self.assertTrue(list_res.ok)
        self.assertEqual(list_res.data["total_entries"], 2)

        # 2. Test vault.archive_extract
        ext_res = self.vault.archive_extract("admin", {"path": "sample.zip", "destination_dir": "Extracted"})
        self.assertTrue(ext_res.ok)
        self.assertEqual(ext_res.data["files_extracted_count"], 2)

        # Verify file exists on disk
        extracted_file = os.path.join(self.test_dir, "Extracted", "notes", "syllabus.txt")
        self.assertTrue(os.path.isfile(extracted_file))
        with open(extracted_file, "r") as f:
            self.assertEqual(f.read(), "Cryptography Syllabus Content")

    def test_archive_zip_slip_rejection(self):
        # Create a malicious zip with ../ traversal
        zip_path = os.path.join(self.test_dir, "malicious.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../../escape.txt", "Malicious content")

        ext_res = self.vault.archive_extract("admin", {"path": "malicious.zip", "destination_dir": "Extracted"})
        self.assertFalse(ext_res.ok)
        self.assertEqual(ext_res.error_code, "ARCHIVE_EXTRACTION_ERROR")

    def test_document_create_text_and_markdown(self):
        res_md = self.vault.document_create("admin", {
            "path": "Notes/dl_summary.md",
            "content": "# Deep Learning Summary\n\n- CNNs\n- RNNs\n- Transformers"
        })
        self.assertTrue(res_md.ok)
        self.assertEqual(res_md.data["format"], "md")

        # Verify reading it back via document_extract
        ext_res = self.vault.document_extract("admin", {"path": "Notes/dl_summary.md"})
        self.assertTrue(ext_res.ok)
        self.assertEqual(ext_res.data["content_type"], "text/markdown")
        self.assertIn("Transformers", ext_res.data["text"])

    def test_document_create_pdf_via_reportlab(self):
        res_pdf = self.vault.document_create("admin", {
            "path": "Notes/crypto_guide.pdf",
            "content": "# Cryptography & Network Security\n\nChapter 1: Symmetric Encryption\n- AES-256\n- DES",
            "format": "pdf",
            "title": "Crypto Guide"
        })
        self.assertTrue(res_pdf.ok)
        self.assertEqual(res_pdf.data["format"], "pdf")
        self.assertGreater(res_pdf.data["size_bytes"], 500)

        # Verify reading it back via pypdf inside document.extract
        ext_res = self.vault.document_extract("admin", {
            "path": "Notes/crypto_guide.pdf",
            "start_page": 1,
            "max_chars": 2000
        })
        self.assertTrue(ext_res.ok)
        self.assertEqual(ext_res.data["content_type"], "extracted_pdf_text")
        self.assertGreaterEqual(ext_res.data["total_pages"], 1)
        self.assertIn("Cryptography", ext_res.data["text"])


if __name__ == "__main__":
    unittest.main()
