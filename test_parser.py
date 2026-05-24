"""test_parser.py — free check that requests + BeautifulSoup can fetch and
extract text from real biotech sites.

Uses research.py's EXACT extraction (research.extract_text) and the same
headers/timeout, so this faithfully mirrors production parsing. Does a single
raw GET per URL WITHOUT raise_for_status, so block responses (403/429/202) are
reported rather than hidden. Makes NO Anthropic API calls.

Run:  ./venv/bin/python test_parser.py
"""

import time

import requests

import research

TEST_URLS = [
    "https://www.fiercebiotech.com",
    "https://endpts.com",
    "https://www.biopharmadive.com",
    "https://clinicaltrials.gov",
    "https://www.fda.gov",
    "https://www.sec.gov",
    "https://www.statnews.com",
    "https://www.businesswire.com",
    "https://www.prnewswire.com",
]

DELAY = 1.5  # polite pause between requests


def main() -> None:
    session = requests.Session()
    print(f"{'URL':38} {'status':>6} {'bytes':>9} {'chars':>8}  first_100_chars")
    print("-" * 110)

    results = []
    for i, url in enumerate(TEST_URLS):
        if i:
            time.sleep(DELAY)
        try:
            # No raise_for_status: we WANT to see 403/429/202 block codes.
            resp = session.get(
                url, headers=research.HEADERS, timeout=research.REQUEST_TIMEOUT
            )
            status = resp.status_code
            nbytes = len(resp.content)
            text = research.extract_text(resp.text)
            preview = text[:100].replace("\n", " ")
            results.append((url, status, nbytes, len(text)))
            print(f"{url:38} {status:>6} {nbytes:>9} {len(text):>8}  {preview}")
        except Exception as exc:
            results.append((url, f"ERR", 0, 0))
            print(f"{url:38} {'ERR':>6} {0:>9} {0:>8}  {type(exc).__name__}: {exc}")

    # --- Summary --------------------------------------------------------
    print("\n" + "=" * 60)
    print("SUMMARY")
    ok = [r for r in results if isinstance(r[1], int) and r[1] == 200 and r[3] >= 100]
    blocked = [r for r in results if isinstance(r[1], int) and r[1] in (202, 403, 429)]
    errored = [r for r in results if r[1] == "ERR"]
    print(f"  Fetched OK (200 + usable text): {len(ok)} / {len(TEST_URLS)}")
    if blocked:
        print("  Blocked (202/403/429):")
        for url, status, *_ in blocked:
            print(f"    {status}  {url}")
    if errored:
        print("  Errored (timeout/SSL/connection):")
        for url, *_ in errored:
            print(f"    {url}")


if __name__ == "__main__":
    main()
