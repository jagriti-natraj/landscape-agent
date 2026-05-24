"""test_search.py — check that Tavily returns useful, diverse URLs.

Verifies the 5 typed search angles against the Tavily API (via
research.tavily_search) and classifies every result by trust tier. Makes NO
Anthropic API calls — queries come from research.QUERY_TEMPLATES (the same
templates research.py falls back to), so the query shape is faithful to
production without spending Anthropic budget.

Run:  ./venv/bin/python test_search.py
"""

from collections import Counter
from urllib.parse import urlparse

import research
from research import SEARCH_ANGLES, QUERY_TEMPLATES
from source_quality import classify_source

TEST_AREA = "AI-driven target discovery"


def build_queries(area: str) -> dict:
    """Build {angle: query} using research.py's own templates (no API call)."""
    return {angle: QUERY_TEMPLATES[angle].format(area=area) for angle in SEARCH_ANGLES}


def main() -> None:
    print(f"Therapeutic area: {TEST_AREA}\n")
    queries = build_queries(TEST_AREA)

    all_rows: list[tuple[str, str, str, int]] = []  # (angle, type, url, content_len)
    per_angle_counts: Counter = Counter()

    for angle in SEARCH_ANGLES:
        query = queries[angle]
        print(f"=== [{angle}] {query}")
        results = research.tavily_search(query, angle)
        if not results:
            print("  (no results returned)\n")
            continue
        for r in results:
            url = r["url"]
            stype = classify_source(url)
            clen = len(r.get("tavily_content", ""))
            all_rows.append((angle, stype, url, clen))
            per_angle_counts[angle] += 1
            print(f"  {angle:18} | {stype:13} | {clen:>5}c | {url}")
        print()

    # --- Summary --------------------------------------------------------
    type_counts = Counter(stype for _, stype, _, _ in all_rows)
    domains = Counter(urlparse(url).netloc.lower() for _, _, url, _ in all_rows)

    print("=" * 60)
    print("SUMMARY")
    print(f"  Total URLs found: {len(all_rows)}")
    print("  By source_type:")
    for stype in ("regulatory", "high_trust", "press_release", "other"):
        print(f"    {stype:14} {type_counts.get(stype, 0)}")
    print("  By angle:")
    for angle in SEARCH_ANGLES:
        print(f"    {angle:18} {per_angle_counts.get(angle, 0)}")
    print(f"  Distinct domains: {len(domains)}")
    print("  Top domains:")
    for domain, count in domains.most_common(8):
        print(f"    {count:>2}  {domain}")


if __name__ == "__main__":
    main()
