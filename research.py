"""research.py — web research for the Landscape Agent (Tavily-powered).

Pipeline (collect-then-filter):

    Step A — Run all 5 typed searches via the Tavily API and pool every result
             with metadata (search_angle, search_rank) AND Tavily's own clean
             content excerpt. No page fetching yet.
    Step B — Classify every pooled URL by trust tier (source_quality.py).
    Step C — Quota-based selection picks WHICH results to keep, reserving slots
             for regulatory + high-trust before press releases, then back-filling
             remaining budget up to 12 with leftover non-press sources.
    Step D — For each selected result, use Tavily's content directly when it's
             substantial (>500 chars); otherwise fall back to fetching the page
             with requests + BeautifulSoup.

Returns a list of dicts (the contract synthesize.py reads):
    {
        "source_url": str,
        "page_text": str,
        "source_type": "regulatory" | "high_trust" | "press_release" | "other",
        "search_angle": str,
    }
"""

import json
import time
from collections import Counter, defaultdict
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import MODEL, get_client, get_tavily_client
from source_quality import classify_source

# --- Tunable knobs ------------------------------------------------------
TAVILY_MAX_RESULTS = 5       # results requested per search angle
TAVILY_CONTENT_MIN = 500     # use Tavily's excerpt directly above this length
MAX_FETCH = 12               # hard cap on results we keep / pages we fetch
MAX_PAGE_CHARS = 3000        # truncate page text to control downstream API cost
REQUEST_TIMEOUT = 12         # seconds before giving up on a fallback fetch
POLITE_DELAY = 1.0           # seconds between fallback fetches

# The five fixed search angles. One query per angle, no near-duplicates.
SEARCH_ANGLES = [
    "financial",
    "regulatory",
    "industry_analysis",
    "partnership_ma",
    "review_academic",
]

# Natural-language query templates (NOT boolean). Tavily is a semantic search
# API: "quotes", OR, and site: operators degrade relevance, so we avoid them.
# Used as the fallback if Claude query generation fails, and by test_search.py.
# Templates take {area} and {geography}; the regulatory/partnership templates
# name Canadian bodies because the default geography is Canada.
QUERY_TEMPLATES = {
    "financial": "{geography} {area} biotech startup funding rounds Series A Series B investors 2025 2026",
    "regulatory": "{geography} {area} Health Canada CIHR clinical trials regulatory status",
    "industry_analysis": "{geography} {area} precision medicine competitive landscape biotech industry analysis 2026",
    "partnership_ma": "{geography} {area} partnership acquisition deal MaRS Genome Canada collaboration",
    "review_academic": "{geography} {area} precision medicine scientific review overview",
}

# Generic browser User-Agent for the fallback page fetcher (not search-specific).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ======================================================================
# Query generation
# ======================================================================

def generate_search_queries(area: str, geography: str = "Canada") -> dict:
    """Ask Claude for exactly 5 typed queries — one per angle, no duplicates.

    Queries are geographically constrained to `geography` (default "Canada").
    Returns {angle: query_string}. Falls back to templates on any failure.
    Queries are natural language (no boolean operators) for Tavily.
    """
    print(f"Generating search queries (one per angle, focused on {geography})...")
    client = get_client()

    prompt = (
        f'Generate web search queries to research the competitive landscape of '
        f'"{area}" in biotech/precision medicine, focused specifically on the '
        f'{geography} ecosystem.\n\n'
        f"Produce EXACTLY ONE query for each of these five angles. Each query "
        f"must target its angle, be geographically constrained to {geography}, "
        f"and must NOT be a near-duplicate of another:\n"
        f"- financial: funding rounds, Series A/B/C, raises, investors\n"
        f"- regulatory: clinical trials, national regulator filings, regulatory status\n"
        f"- industry_analysis: market landscape / analyst reports\n"
        f"- partnership_ma: partnerships, acquisitions, deals\n"
        f"- review_academic: academic or scientific review articles\n\n"
        f"Reference {geography}'s national regulators, funding agencies, and "
        f"biotech ecosystem organizations where relevant (for Canada, e.g. Health "
        f"Canada, CIHR, Genome Canada, MaRS Discovery District).\n\n"
        f"IMPORTANT: Write natural-language queries. Do NOT use boolean "
        f"operators, quotation marks, OR, or site: filters — they hurt results "
        f"on a semantic search engine.\n\n"
        f"Return ONLY a JSON object mapping each angle name to its query string, "
        f"e.g. {{\"financial\": \"...\", \"regulatory\": \"...\", "
        f"\"industry_analysis\": \"...\", \"partnership_ma\": \"...\", "
        f"\"review_academic\": \"...\"}}"
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[len("json"):]
        parsed = json.loads(text.strip())

        queries = {}
        for angle in SEARCH_ANGLES:
            q = parsed.get(angle)
            if isinstance(q, str) and q.strip():
                queries[angle] = q.strip()
            else:
                queries[angle] = QUERY_TEMPLATES[angle].format(area=area, geography=geography)
    except Exception as exc:
        print(f"  Could not parse generated queries ({exc}). Using templates.")
        queries = {
            a: QUERY_TEMPLATES[a].format(area=area, geography=geography)
            for a in SEARCH_ANGLES
        }

    for angle, q in queries.items():
        print(f"    [{angle}] {q}")
    return queries


# ======================================================================
# Step A — searching via Tavily
# ======================================================================

def tavily_search(query: str, angle: str) -> list[dict]:
    """Run one Tavily search and return pooled result dicts (no page fetch).

    Each dict: {url, search_angle, search_rank, tavily_content}. The content
    excerpt is carried along so Step D can use it without re-fetching.
    """
    client = get_tavily_client()
    try:
        resp = client.search(
            query=query,
            search_depth="advanced",
            max_results=TAVILY_MAX_RESULTS,
        )
    except Exception as exc:
        print(f"  Tavily search failed for [{angle}]: {exc}")
        return []

    results = []
    for rank, r in enumerate(resp.get("results", []), start=1):
        url = r.get("url", "")
        if not url:
            continue
        results.append({
            "url": url,
            "search_angle": angle,
            "search_rank": rank,
            "tavily_content": r.get("content", "") or "",
        })
    return results


# ======================================================================
# Step C — quota-based selection (anti-starvation + back-fill)
# ======================================================================

def _diversity_order(candidates: list[dict]) -> list[dict]:
    """Order candidates round-robin across search angles, best rank first."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for c in sorted(candidates, key=lambda x: x["search_rank"]):
        buckets[c["search_angle"]].append(c)

    ordered: list[dict] = []
    while any(buckets.values()):
        for angle in list(buckets.keys()):
            if buckets[angle]:
                ordered.append(buckets[angle].pop(0))
    return ordered


def select_sources(pool: list[dict]) -> list[dict]:
    """Choose which pooled results to keep, using strict quota precedence.

    Order (each step respects the MAX_FETCH=12 ceiling):
      1. ALL regulatory results, up to 3.
      2. high_trust until (regulatory + high_trust) >= 4.
      3. 'other' until total picks reach 8.
      4. press_release LAST, capped at 2.
      5. Back-fill remaining budget up to 12 with leftover non-press sources.
    """
    selected: list[dict] = []
    chosen_urls: set[str] = set()

    def n_type(t: str) -> int:
        return sum(1 for s in selected if s["source_type"] == t)

    def take(source_type: str, keep_going) -> None:
        candidates = [
            p for p in pool
            if p["source_type"] == source_type and p["url"] not in chosen_urls
        ]
        for item in _diversity_order(candidates):
            if len(selected) >= MAX_FETCH or not keep_going():
                break
            selected.append(item)
            chosen_urls.add(item["url"])

    # 1. Regulatory first — primary sources, hard cap 3.
    take("regulatory", lambda: n_type("regulatory") < 3)
    # 2. High-trust journalism until we have 4 strong sources total.
    take("high_trust", lambda: (n_type("regulatory") + n_type("high_trust")) < 4)
    # 3. Fill out the body of the landscape with 'other' up to 8 total.
    take("other", lambda: len(selected) < 8)
    # 4. Only now allow press releases, and never more than 2.
    take("press_release", lambda: n_type("press_release") < 2)
    # 5. Back-fill spare budget with leftover non-press sources, by priority.
    for source_type in ("regulatory", "high_trust", "other"):
        take(source_type, lambda: True)  # take() stops itself at MAX_FETCH

    return selected[:MAX_FETCH]


# ======================================================================
# Step D — page text (Tavily content, with fetch fallback)
# ======================================================================

def extract_text(html: str) -> str:
    """Clean raw HTML into readable text (no truncation). Pure function.

    Shared by fetch_page_text and the parser test so both use identical
    extraction logic.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def fetch_page_text(url: str, session: requests.Session) -> str | None:
    """Fetch a page and return cleaned text, or None if it can't be read.

    Used only as a fallback when Tavily's content excerpt is too short.
    """
    try:
        resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  Skipped (fetch failed): {url}  [{exc}]")
        return None

    if "html" not in resp.headers.get("Content-Type", "").lower():
        print(f"  Skipped (not HTML): {url}")
        return None

    text = extract_text(resp.text)
    if len(text) < 100:
        print(f"  Skipped (too little text): {url}")
        return None

    return text[:MAX_PAGE_CHARS]


# ======================================================================
# Quality summary
# ======================================================================

def _print_quality_summary(items: list[dict], queries: dict) -> None:
    """Print a research-quality readout BEFORE synthesis runs."""
    type_counts = Counter(it["source_type"] for it in items)
    domains = {urlparse(it["source_url"]).netloc.lower() for it in items}
    angles_present = {it["search_angle"] for it in items}

    print("\nResearch complete.")
    print(f"- Sources fetched: {len(items)}")
    print(f"- High-trust journalism: {type_counts.get('high_trust', 0)}")
    print(f"- Regulatory / primary: {type_counts.get('regulatory', 0)}")
    print(f"- Press releases: {type_counts.get('press_release', 0)}")
    print(f"- Other: {type_counts.get('other', 0)}")
    print(f"- Distinct domains: {len(domains)}")
    print(f"- Search angles represented: {len(angles_present)} of {len(SEARCH_ANGLES)}")

    if type_counts.get("press_release", 0) > type_counts.get("high_trust", 0):
        print(
            "⚠️ Source mix is press-release-heavy. Landscape confidence will be "
            "limited.\n"
            "   Consider trying a different therapeutic area or refining search "
            "terms."
        )

    for angle in SEARCH_ANGLES:
        if angle not in angles_present:
            print(
                f"⚠️ Search angle '{angle}' returned no usable sources. "
                f"Landscape coverage may be uneven."
            )


# ======================================================================
# Top-level entry point
# ======================================================================

def gather_research(area: str, geography: str = "Canada") -> list[dict]:
    """Run the full collect-then-filter pipeline; return fetched source dicts."""
    queries = generate_search_queries(area, geography)

    # --- Step A: search all angles via Tavily (no page fetching) --------
    print("\nStep A: searching all angles via Tavily...")
    pool: list[dict] = []
    seen: set[str] = set()
    for angle in SEARCH_ANGLES:
        print(f"  [{angle}] searching...")
        for r in tavily_search(queries[angle], angle):
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            pool.append(r)
    print(f"  Pooled {len(pool)} unique URLs across {len(SEARCH_ANGLES)} angles.")

    if not pool:
        return []

    # --- Step B: classify every pooled URL ------------------------------
    for p in pool:
        p["source_type"] = classify_source(p["url"])

    # --- Step C: quota-based selection ----------------------------------
    selected = select_sources(pool)
    sel_counts = Counter(s["source_type"] for s in selected)
    print(
        f"\nStep C: selected {len(selected)} results "
        f"(regulatory={sel_counts.get('regulatory', 0)}, "
        f"high_trust={sel_counts.get('high_trust', 0)}, "
        f"other={sel_counts.get('other', 0)}, "
        f"press_release={sel_counts.get('press_release', 0)})."
    )

    # --- Step D: use Tavily content, fall back to fetch when too short --
    print("\nStep D: collecting page text (Tavily content, fetch fallback)...")
    session = requests.Session()
    items: list[dict] = []
    for s in selected:
        content = s.get("tavily_content", "")
        if len(content) > TAVILY_CONTENT_MIN:
            page_text = content[:MAX_PAGE_CHARS]
            origin = "tavily"
        else:
            time.sleep(POLITE_DELAY)
            page_text = fetch_page_text(s["url"], session)
            origin = "fetched"

        if page_text:
            items.append({
                "source_url": s["url"],
                "page_text": page_text,
                "source_type": s["source_type"],
                "search_angle": s["search_angle"],
            })
            print(f"  [{s['source_type']}] {origin} ({len(page_text)} chars): {s['url']}")

    _print_quality_summary(items, queries)
    return items
