from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def rss_xml() -> str:
    return (FIXTURES / "rss_sample.xml").read_text(encoding="utf-8")


@pytest.fixture
def atom_xml() -> str:
    return (FIXTURES / "atom_sample.xml").read_text(encoding="utf-8")


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
