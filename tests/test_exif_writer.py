"""Tests for the EXIF XPTags writer module (via exiftool subprocess)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

from exif_tagger.exif_writer import (
    _parse_existing_tags,
    get_existing_xptags,
    tag_image_exif,
    write_xptags,
)


def _mock_run(result: tuple[int, str]) -> MagicMock:
    """Helper to create a mock subprocess.run side_effect that returns a completed process."""

    def runner(*args, **kwargs):  # type: ignore[no-untyped-def]
        code, stdout = result
        proc = MagicMock()
        proc.returncode = code
        proc.stdout = stdout
        proc.stderr = ""
        return proc

    return MagicMock(side_effect=runner)


class TestParseExistingTags:
    """Test parsing of semicolon-separated XPTags."""

    def test_empty_string(self):
        assert _parse_existing_tags("") == set()

    def test_single_tag(self):
        result = _parse_existing_tags("landscape")
        assert result == {"landscape"}

    def test_multiple_tags_semicolon(self):
        result = _parse_existing_tags("landscape;portrait;architecture")
        assert result == {"landscape", "portrait", "architecture"}

    def test_whitespace_handling(self):
        result = _parse_existing_tags("  landscape ; portrait ; architecture ")
        assert result == {"landscape", "portrait", "architecture"}


class TestGetExistingXptags:
    """Test reading XPTags from real image files via exiftool mock."""

    @patch("exif_tagger.exif_writer.subprocess.run")
    def test_new_image_has_no_xptags(self, mock_run):
        """A newly created image should have no existing tags (empty exiftool output)."""
        path = Path("/tmp/test_new.jpg")
        mock_run.side_effect = _mock_run((0, ""))  # read returns empty

        with patch("exif_tagger.exif_writer._check_exiftool_available", return_value=True):
            result = get_existing_xptags(path)

        assert result == set()
        # Verify subprocess.run was called for reading (with security parameters)
        mock_run.assert_called_once_with(
            ["exiftool", "-s3", "-XPTags", str(path)], 
            capture_output=True, 
            text=True, 
            timeout=10,
            check=False,  # SECURITY: Don't raise on non-zero exit
            shell=False,  # SECURITY: Explicitly disabled for command injection prevention
        )

    @patch("exif_tagger.exif_writer.subprocess.run")
    def test_image_with_tags(self, mock_run):
        """Image that already has XPTags should return them."""
        path = Path("/tmp/test_with.jpg")
        mock_run.side_effect = _mock_run((0, "landscape;portrait"))

        with patch("exif_tagger.exif_writer._check_exiftool_available", return_value=True):
            result = get_existing_xptags(path)

        assert result == {"landscape", "portrait"}

    @patch("exif_tagger.exif_writer.subprocess.run")
    def test_exiftool_failure_returns_empty(self, mock_run):
        """If exiftool fails, return empty set (graceful degradation)."""
        path = Path("/tmp/test_fail.jpg")
        mock_run.side_effect = _mock_run((1, "error message"))

        with patch("exif_tagger.exif_writer._check_exiftool_available", return_value=True):
            result = get_existing_xptags(path)

        assert result == set()


class TestWriteXptags:
    """Test writing XPTags to image files via exiftool mock."""

    @patch("exif_tagger.exif_writer.subprocess.run")
    def test_write_single_tag(self, mock_run):
        """Writing one tag should call exiftool with the correct command."""
        path = Path("/tmp/test1.jpg")

        # First call (read existing → empty), second call (write landscape)
        read_result = MagicMock()
        read_result.returncode = 0
        read_result.stdout = ""
        read_result.stderr = ""

        write_result = MagicMock()
        write_result.returncode = 0
        write_result.stdout = ""
        write_result.stderr = ""

        mock_run.side_effect = [read_result, write_result]

        with patch("exif_tagger.exif_writer._check_exiftool_available", return_value=True):
            modified, count = write_xptags(path, ["landscape"])

        assert modified is True
        assert count == 1
        # Verify exiftool was called for the write command (second call)
        all_calls = mock_run.call_args_list
        assert len(all_calls) >= 2, f"Expected at least 2 calls, got {len(all_calls)}"
        # Second call should be the write: exiftool -XPTags=landscape ...
        second_call_args = all_calls[1]
        if isinstance(second_call_args, tuple):
            combined_str = " ".join(str(a) for a in second_call_args[0])
        else:
            combined_str = str(second_call_args)
        assert "-XPTags=landscape" in combined_str

    @patch("exif_tagger.exif_writer.subprocess.run")
    def test_append_mode_keeps_existing(self, mock_run):
        """Writing new tags should preserve already-existing ones."""
        path = Path("/tmp/test2.jpg")

        with patch("exif_tagger.exif_writer._check_exiftool_available", return_value=True):
            # First write: read returns empty → write landscape
            r1 = MagicMock()
            r1.returncode = 0; r1.stdout = ""; r1.stderr = ""
            w1 = MagicMock(); w1.returncode = 0; w1.stdout = ""; w1.stderr = ""

            mock_run.side_effect = [r1, w1]
            modified, count = write_xptags(path, ["landscape"])
            assert modified is True and count == 1

            # Second write: read returns "landscape" → write portrait+landscape (merged)
            r2 = MagicMock()
            r2.returncode = 0; r2.stdout = "landscape"; r2.stderr = ""
            w2 = MagicMock(); w2.returncode = 0; w2.stdout = ""; w2.stderr = ""

            mock_run.side_effect = [r2, w2]
            modified, count = write_xptags(path, ["portrait"])
            assert modified is True and count == 1

    @patch("exif_tagger.exif_writer.subprocess.run")
    def test_no_duplicate_writes(self, mock_run):
        """Writing tags that already exist should not call exiftool to WRITE."""
        path = Path("/tmp/test3.jpg")

        with patch("exif_tagger.exif_writer._check_exiftool_available", return_value=True):
            # read returns landscape → no new tags, write should NOT be called
            r1 = MagicMock()
            r1.returncode = 0; r1.stdout = "landscape"; r1.stderr = ""

            mock_run.side_effect = [r1]
            modified, count = write_xptags(path, ["landscape"])

        assert modified is False
        assert count == 0


class TestTagImageExif:
    """Test the convenience wrapper tag_image_exif."""

    @patch("exif_tagger.exif_writer.subprocess.run")
    def test_wrapper_works(self, mock_run):
        """tag_image_exif should behave identically to write_xptags."""
        path = Path("/tmp/wrapper_test.jpg")

        with patch("exif_tagger.exif_writer._check_exiftool_available", return_value=True):
            r1 = MagicMock()
            r1.returncode = 0; r1.stdout = ""; r1.stderr = ""
            w1 = MagicMock(); w1.returncode = 0; w1.stdout = ""; w1.stderr = ""

            mock_run.side_effect = [r1, w1]
            modified, count = tag_image_exif(path, ["landscape"])

        assert modified is True and count == 1
