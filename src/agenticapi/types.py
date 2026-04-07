"""Common type definitions for AgenticAPI."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

# Type aliases using Python 3.13+ type statement
type JSON = dict[str, Any]
type JSONList = list[JSON]
type Headers = dict[str, str]
type Metadata = dict[str, Any]


class AutonomyLevel(StrEnum):
    """Agent autonomy levels."""

    AUTO = "auto"
    SUPERVISED = "supervised"
    MANUAL = "manual"


class TraceLevel(StrEnum):
    """Audit trace levels."""

    MINIMAL = "minimal"
    STANDARD = "standard"
    FULL = "full"
    DEBUG = "debug"


class Severity(StrEnum):
    """Severity levels for incidents and alerts."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
