"""``agenticapi bump`` — semantic version bumping via git tags.

hatch-vcs derives the package version from annotated git tags.  This
command creates the next semver tag so that ``agenticapi version``
reflects the new release.

Examples::

    agenticapi bump patch              # 0.1.0 -> 0.1.1
    agenticapi bump minor              # 0.1.0 -> 0.2.0
    agenticapi bump major              # 0.1.0 -> 1.0.0
    agenticapi bump prerelease         # 0.1.0 -> 0.1.1-rc.1
    agenticapi bump current            # display current version tag
    agenticapi bump --dry-run patch    # preview without creating tag
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemVer:
    """Semantic version with major.minor.patch[-prerelease]."""

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
        """Bump to the next prerelease within the *next* patch."""
        if self.prerelease and self.prerelease.startswith(prefix + "."):
            num = int(self.prerelease.split(".")[-1]) + 1
            return SemVer(self.major, self.minor, self.patch, f"{prefix}.{num}")
        nxt = self.bump_patch()
        return SemVer(nxt.major, nxt.minor, nxt.patch, f"{prefix}.1")

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.prerelease}" if self.prerelease else base

    @property
    def tag(self) -> str:
        return f"v{self}"


def _run(cmd: list[str], *, check: bool = True) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=check)
    return result.stdout.strip()


def _latest_tag() -> SemVer | None:
    try:
        tags = _run(["git", "tag", "--sort=-v:refname", "--list", "v*"])
    except subprocess.CalledProcessError:
        return None
    for line in tags.splitlines():
        try:
            return SemVer.parse(line.strip())
        except ValueError:
            continue
    return None


def _working_tree_clean() -> bool:
    return len(_run(["git", "status", "--porcelain"])) == 0


def run_bump(
    part: str,
    *,
    dry_run: bool = False,
    pre_prefix: str = "rc",
    initial: str = "0.1.0",
) -> int:
    """Execute the bump and return an exit code."""

    current = _latest_tag()

    if part == "current":
        if current is None:
            print("No version tags found.")
            print(f"  Run `agenticapi bump patch` to create {initial}")
        else:
            print(f"{current} (tag: {current.tag})")
        return 0

    # Compute next version.
    if current is None:
        nxt = SemVer.parse(initial)
        print(f"No existing tags — starting at {nxt}")
    else:
        match part:
            case "major":
                nxt = current.bump_major()
            case "minor":
                nxt = current.bump_minor()
            case "patch":
                nxt = current.bump_patch()
            case "prerelease":
                nxt = current.bump_prerelease(pre_prefix)
            case _:
                raise AssertionError(f"unreachable: {part}")
        print(f"{current} -> {nxt}")

    if dry_run:
        print(f"[dry-run] Would create tag: {nxt.tag}")
        return 0

    if not _working_tree_clean():
        print("Error: uncommitted changes. Commit or stash first.", file=sys.stderr)
        return 1

    _run(["git", "tag", "-a", nxt.tag, "-m", f"Release {nxt}"])
    print(f"Created tag: {nxt.tag}")
    print()
    print("Next steps:")
    print(f"  git push origin {nxt.tag}")
    return 0
