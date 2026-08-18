"""Shared health check result models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HealthCheckResult:
    """Immutable result returned by a health check."""

    name: str
    status: str
    summary: str
    metrics: dict[str, object]
    recommendation: str
