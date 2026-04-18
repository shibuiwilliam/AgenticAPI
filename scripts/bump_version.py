#!/usr/bin/env python3
"""Semantic version bump tool for AgenticAPI.

Creates git tags following semver (https://semver.org/).
hatch-vcs derives the package version from these tags automatically.

Usage:
    python scripts/bump_version.py major      # 0.1.0 -> 1.0.0
    python scripts/bump_version.py minor      # 0.1.0 -> 0.2.0
    python scripts/bump_version.py patch      # 0.1.0 -> 0.1.1
    python scripts/bump_version.py prerelease # 0.1.0 -> 0.1.1-rc.1
    python scripts/bump_version.py current    # Show current version
    python scripts/bump_version.py --dry-run patch  # Preview without tagging
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemVer:
    """Semantic version representation."""

    major: int
    minor: int
    patch: int
    prerelease: str | None = None

    _TAG_RE = re.compile(
        r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
        r"(?:-(?P<pre>[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*))?$"
    )

    @classmethod
    def parse(cls, tag: str) -> SemVer:
        m = cls._TAG_RE.match(tag)
        if not m:
            raise ValueError(f"Invalid semver tag: {tag!r}")
        return cls(
            major=int(m["major"]),
            minor=int(m["minor"]),
            patch=int(m["patch"]),
            prerelease=m["pre"],
        )

    def bump_major(self) -> SemVer:
        return SemVer(self.major + 1, 0, 0)

    def bump_minor(self) -> SemVer:
        return SemVer(self.major, self.minor + 1, 0)

    def bump_patch(self) -> SemVer:
        return SemVer(self.major, self.minor, self.patch + 1)

    def bump_prerelease(self, prefix: str = "rc") -> SemVer:
        if self.prerelease and self.prerelease.startswith(prefix + "."):
            num = int(self.prerelease.split(".")[-1]) + 1
            return SemVer(self.major, self.minor, self.patch, f"{prefix}.{num}")
        next_patch = self.bump_patch()
        return SemVer(next_patch.major, next_patch.minor, next_patch.patch, f"{prefix}.1")

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            return f"{base}-{self.prerelease}"
        return base

    @property
    def tag(self) -> str:
        return f"v{self}"


def run(cmd: list[str], *, check: bool = True) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=check)
    return result.stdout.strip()


def get_latest_tag() -> SemVer | None:
    """Get the latest semver tag from git history."""
    try:
        tags = run(["git", "tag", "--sort=-v:refname", "--list", "v*"])
    except subprocess.CalledProcessError:
        return None
    if not tags:
        return None
    for line in tags.splitlines():
        line = line.strip()
        try:
            return SemVer.parse(line)
        except ValueError:
            continue
    return None


def check_clean_working_tree() -> bool:
    """Return True if the working tree is clean (no uncommitted changes)."""
    status = run(["git", "status", "--porcelain"])
    return len(status) == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bump the semantic version via git tags.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "part",
        choices=["major", "minor", "patch", "prerelease", "current"],
        help="Which part of the version to bump, or 'current' to display.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the new version without creating a tag.",
    )
    parser.add_argument(
        "--pre-prefix",
        default="rc",
        help="Prerelease prefix (default: rc). E.g. 'alpha', 'beta', 'rc'.",
    )
    parser.add_argument(
        "--initial",
        default="0.1.0",
        help="Initial version if no tags exist (default: 0.1.0).",
    )
    args = parser.parse_args()

    current = get_latest_tag()

    if args.part == "current":
        if current is None:
            print("No version tags found. Use 'major', 'minor', or 'patch' to create the first tag.")
            print(f"  Initial version will be: {args.initial}")
        else:
            print(f"Current version: {current} (tag: {current.tag})")
        return 0

    # Determine the new version.
    if current is None:
        new = SemVer.parse(args.initial)
        print(f"No existing version tags. Starting at {new}")
    else:
        match args.part:
            case "major":
                new = current.bump_major()
            case "minor":
                new = current.bump_minor()
            case "patch":
                new = current.bump_patch()
            case "prerelease":
                new = current.bump_prerelease(args.pre_prefix)
            case _:
                raise AssertionError(f"unreachable: {args.part}")
        print(f"Bumping {args.part}: {current} -> {new}")

    if args.dry_run:
        print(f"[dry-run] Would create tag: {new.tag}")
        return 0

    if not check_clean_working_tree():
        print("Error: working tree has uncommitted changes. Commit or stash them first.", file=sys.stderr)
        return 1

    # Create the annotated tag.
    tag = new.tag
    run(["git", "tag", "-a", tag, "-m", f"Release {new}"])
    print(f"Created tag: {tag}")
    print()
    print("Next steps:")
    print(f"  git push origin {tag}    # Push the tag to trigger release")
    print("  git push origin main     # Push commits")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
