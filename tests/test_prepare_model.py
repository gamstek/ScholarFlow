"""Initialization lifecycle checks; network/model loading are replaced by fixtures."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.rag import prepare_model as initializer


class PrepareModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.model_dir = Path(self.temporary.name) / "bge-m3"
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def create_assets(self, model_dir=None, **_kwargs):
        model_dir = model_dir or self.model_dir
        for name in (*initializer.REQUIRED_FILES, "pytorch_model.bin"):
            path = model_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"test model asset")

    def test_first_start_downloads_and_validates_before_marking_ready(self):
        def validate(model_dir):
            self.assertFalse((model_dir / initializer.READY_FILE).exists())

        with patch.object(initializer, "_download_model", side_effect=self.create_assets) as download:
            with patch.object(initializer, "_validate_model", side_effect=validate):
                initializer.prepare_model(self.model_dir)
        download.assert_called_once_with(self.model_dir, force_download=False)
        self.assertTrue(initializer._is_ready(self.model_dir))

    def test_unchanged_model_reuses_files_without_network_or_loading(self):
        self.create_assets()
        initializer._mark_ready(self.model_dir)
        with patch.object(initializer, "_download_model") as download:
            with patch.object(initializer, "_validate_model") as validate:
                initializer.prepare_model(self.model_dir)
        download.assert_not_called()
        validate.assert_not_called()

    def test_existing_complete_model_is_validated_without_downloading(self):
        self.create_assets()
        with patch.object(initializer, "_download_model") as download:
            with patch.object(initializer, "_validate_model") as validate:
                initializer.prepare_model(self.model_dir)
        download.assert_not_called()
        validate.assert_called_once_with(self.model_dir)
        self.assertTrue(initializer._is_ready(self.model_dir))

    def test_missing_file_invalidates_old_marker_and_resumes_download(self):
        self.create_assets()
        initializer._mark_ready(self.model_dir)
        (self.model_dir / "tokenizer.json").unlink()
        with patch.object(initializer, "_download_model", side_effect=self.create_assets) as download:
            with patch.object(initializer, "_validate_model"):
                initializer.prepare_model(self.model_dir)
        download.assert_called_once_with(self.model_dir, force_download=False)
        self.assertTrue(initializer._is_ready(self.model_dir))

    def test_changed_weights_invalidate_marker_and_corrupt_model_is_repaired(self):
        self.create_assets()
        initializer._mark_ready(self.model_dir)
        (self.model_dir / "pytorch_model.bin").write_bytes(b"corrupt")
        self.assertFalse(initializer._is_ready(self.model_dir))
        with patch.object(initializer, "_download_model", side_effect=self.create_assets) as download:
            with patch.object(initializer, "_validate_model", side_effect=[ValueError("corrupt weights"), None]):
                initializer.prepare_model(self.model_dir)
        download.assert_called_once_with(self.model_dir, force_download=True)
        self.assertTrue(initializer._is_ready(self.model_dir))

    def test_interrupted_download_has_no_ready_marker_and_can_be_retried(self):
        with patch.object(initializer, "_download_model", side_effect=OSError("connection lost")):
            with self.assertRaises(OSError):
                initializer.prepare_model(self.model_dir)
        self.assertFalse((self.model_dir / initializer.READY_FILE).exists())
        with patch.object(initializer, "_download_model", side_effect=self.create_assets) as download:
            with patch.object(initializer, "_validate_model"):
                initializer.prepare_model(self.model_dir)
        download.assert_called_once_with(self.model_dir, force_download=False)

    def test_failed_validation_never_marks_a_download_ready(self):
        with patch.object(initializer, "_download_model", side_effect=self.create_assets):
            with patch.object(initializer, "_validate_model", side_effect=ValueError("invalid model")):
                with self.assertRaises(ValueError):
                    initializer.prepare_model(self.model_dir)
        self.assertFalse((self.model_dir / initializer.READY_FILE).exists())

    def test_malformed_marker_does_not_bypass_validation(self):
        self.create_assets()
        (self.model_dir / initializer.READY_FILE).write_text(json.dumps(["invalid"]), encoding="utf-8")
        with patch.object(initializer, "_download_model") as download:
            with patch.object(initializer, "_validate_model") as validate:
                initializer.prepare_model(self.model_dir)
        download.assert_not_called()
        validate.assert_called_once()

    def test_cli_returns_nonzero_on_failure(self):
        with patch.object(initializer, "prepare_model", side_effect=OSError("download failed")):
            self.assertEqual(initializer.main(), 1)


if __name__ == "__main__":
    unittest.main()
