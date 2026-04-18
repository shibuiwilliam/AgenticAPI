"""Tests for ``agenticapi bump`` — semantic version bumping."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agenticapi.cli.bump import SemVer, run_bump

# ── SemVer parsing ──────────────────────────────────────────────────


class TestSemVerParse:
    def test_basic(self) -> None:
        v = SemVer.parse("1.2.3")
        assert (v.major, v.minor, v.patch, v.prerelease) == (1, 2, 3, None)

    def test_with_v_prefix(self) -> None:
        v = SemVer.parse("v0.5.0")
        assert (v.major, v.minor, v.patch) == (0, 5, 0)

    def test_with_prerelease(self) -> None:
        v = SemVer.parse("v1.0.0-rc.2")
        assert v.prerelease == "rc.2"

    def test_invalid(self) -> None:
        with pytest.raises(ValueError, match="Invalid semver"):
            SemVer.parse("not-a-version")


# ── SemVer bumping ──────────────────────────────────────────────────


class TestSemVerBump:
    def test_bump_major(self) -> None:
        assert str(SemVer(1, 2, 3).bump_major()) == "2.0.0"

    def test_bump_minor(self) -> None:
        assert str(SemVer(1, 2, 3).bump_minor()) == "1.3.0"

    def test_bump_patch(self) -> None:
        assert str(SemVer(1, 2, 3).bump_patch()) == "1.2.4"

    def test_bump_prerelease_from_release(self) -> None:
        v = SemVer(1, 2, 3).bump_prerelease()
        assert str(v) == "1.2.4-rc.1"

    def test_bump_prerelease_from_prerelease(self) -> None:
        v = SemVer(1, 2, 4, "rc.1").bump_prerelease()
        assert str(v) == "1.2.4-rc.2"

    def test_bump_prerelease_custom_prefix(self) -> None:
        v = SemVer(0, 1, 0).bump_prerelease("beta")
        assert str(v) == "0.1.1-beta.1"

    def test_tag_property(self) -> None:
        assert SemVer(0, 1, 0).tag == "v0.1.0"
        assert SemVer(1, 0, 0, "rc.1").tag == "v1.0.0-rc.1"

    def test_str(self) -> None:
        assert str(SemVer(0, 1, 0)) == "0.1.0"
        assert str(SemVer(1, 0, 0, "alpha.3")) == "1.0.0-alpha.3"


# ── run_bump integration ───────────────────────────────────────────


class TestRunBump:
    def test_current_no_tags(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("agenticapi.cli.bump._latest_tag", return_value=None):
            code = run_bump("current")
        assert code == 0
        assert "No version tags" in capsys.readouterr().out

    def test_current_with_tag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("agenticapi.cli.bump._latest_tag", return_value=SemVer(1, 2, 3)):
            code = run_bump("current")
        assert code == 0
        assert "1.2.3" in capsys.readouterr().out

    def test_dry_run_patch(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("agenticapi.cli.bump._latest_tag", return_value=SemVer(0, 1, 0)):
            code = run_bump("patch", dry_run=True)
        assert code == 0
        out = capsys.readouterr().out
        assert "v0.1.1" in out
        assert "dry-run" in out

    def test_dry_run_no_tags(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("agenticapi.cli.bump._latest_tag", return_value=None):
            code = run_bump("minor", dry_run=True, initial="0.1.0")
        assert code == 0
        assert "v0.1.0" in capsys.readouterr().out

    def test_dirty_tree_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("agenticapi.cli.bump._latest_tag", return_value=SemVer(0, 1, 0)),
            patch("agenticapi.cli.bump._working_tree_clean", return_value=False),
        ):
            code = run_bump("patch")
        assert code == 1
        assert "uncommitted" in capsys.readouterr().err

    def test_creates_tag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("agenticapi.cli.bump._latest_tag", return_value=SemVer(0, 1, 0)),
            patch("agenticapi.cli.bump._working_tree_clean", return_value=True),
            patch("agenticapi.cli.bump._run") as mock_run,
        ):
            code = run_bump("minor")
        assert code == 0
        mock_run.assert_called_once_with(["git", "tag", "-a", "v0.2.0", "-m", "Release 0.2.0"])
        assert "v0.2.0" in capsys.readouterr().out
