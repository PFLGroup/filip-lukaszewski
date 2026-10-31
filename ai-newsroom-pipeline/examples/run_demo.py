"""Demo offline: przykładowe kanały z tests/fixtures -> scoring -> szkice (fałszywy LLM) -> WordPress w trybie dry-run.

Uruchomienie (z katalogu repozytorium):
    python examples/run_demo.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from newsroom.ingest import parse_feed  # noqa: E402
from newsroom.llm import FakeLLMClient  # noqa: E402
from newsroom.models import Reach  # noqa: E402
from newsroom.pipeline import run_pipeline  # noqa: E402
from newsroom.scoring import ScoringConfig  # noqa: E402
from newsroom.wp_publisher import WordPressPublisher  # noqa: E402


def demo_llm(system: str, prompt: str) -> str:
    if '"adjust"' in system:
        return '{"adjust": 2, "reason": "temat lokalny, dobrze rokuje"}'
    title = prompt.split("Tytuł źródła: ")[1].split("\n")[0]
    body = "## Najważniejsze\n" + "Opracowanie redakcyjne na podstawie źródła. " * 12
    return json.dumps({"title": title[:100], "lead": "Krótki lead.", "body_markdown": body, "tags": ["demo"]})


def main() -> None:
    fixtures = ROOT / "tests" / "fixtures"
    items = parse_feed((fixtures / "rss_sample.xml").read_text(encoding="utf-8"), "regional", Reach.REGIONAL)
    items += parse_feed((fixtures / "atom_sample.xml").read_text(encoding="utf-8"), "national", Reach.NATIONAL)

    publisher = WordPressPublisher("https://wp.example.com", "demo", "demo", dry_run=True)
    report = run_pipeline(
        items,
        FakeLLMClient(handler=demo_llm),
        publisher,
        config=ScoringConfig(topics=frozenset({"transport", "budzet", "energia", "most"})),
        now=datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc),
    )
    print(f"pobrane: {report.fetched}, unikalne: {report.unique}, GO: {report.go}, "
          f"odrzucone: {report.rejected}, do przeglądu: {len(report.review)}")
    for payload in publisher.sent:
        print(f"  [{payload['status']}] {payload['title']}  meta={payload['meta']}")


if __name__ == "__main__":
    main()
