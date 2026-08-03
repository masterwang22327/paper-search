from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools import validate_library


class LibraryValidationTests(unittest.TestCase):
    def test_template_contains_schema_required_source_fields(self) -> None:
        data = validate_library.load_yaml(
            Path(__file__).resolve().parents[1] / "templates" / "metadata.yml"
        )

        errors = validate_library.validate_record(data)
        self.assertEqual(errors, [
            "id must be a non-empty string",
            "title must be a non-empty string",
            "year must be an integer",
            "invalid status: ",
        ])
        self.assertFalse(any("source" in error for error in errors))

    def test_validator_rejects_legacy_artifact_status(self) -> None:
        record = {
            "id": "arxiv_1234.56789",
            "title": "Example",
            "year": 2026,
            "status": "preprint",
            "reading_status": "candidate",
            "source": {"official": True},
            "artifacts": {"code": {"status": "legacy_unknown_status"}},
        }

        errors = validate_library.validate_record(record)

        self.assertEqual(errors, [
            "artifacts.code.status is invalid: legacy_unknown_status"
        ])

    def test_cli_returns_nonzero_for_invalid_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.yml"
            path.write_text("id: bad\n", encoding="utf-8")

            with redirect_stderr(StringIO()):
                self.assertNotEqual(validate_library.main([str(path)]), 0)

    def test_schema_rejects_a_record_missing_required_source(self) -> None:
        record = {
            "id": "arxiv_1234.56789",
            "title": "Example",
            "year": 2026,
            "status": "preprint",
            "reading_status": "candidate",
        }

        errors = validate_library.schema_errors(record)

        self.assertTrue(any("source" in error for error in errors))

    def test_all_existing_library_records_pass_semantic_and_schema_checks(self) -> None:
        library = Path(__file__).resolve().parents[1] / "library"

        failures = {}
        for path in library.rglob("metadata.yml"):
            errors = validate_library.validate_path(path)
            if errors:
                failures[str(path)] = errors

        self.assertEqual(failures, {})


if __name__ == "__main__":
    unittest.main()
