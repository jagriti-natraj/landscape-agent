"""Precision Medicine Landscape Agent — main entry point.

Usage:
    python agent.py "AI-driven target discovery"

Workflow:
    1. Take a therapeutic area from the command line.
    2. research.py gathers raw text from the web about that area.
    3. synthesize.py turns that raw text into a structured, VC-ready
       competitive landscape in markdown.
    4. The result is saved to outputs/{slug}_{timestamp}.md.
"""

import os
import re
import sys
from datetime import datetime

import research
import synthesize

OUTPUT_DIR = "outputs"


def slugify(text: str) -> str:
    """Turn a therapeutic area into a safe filename fragment.

    "AI-driven target discovery" -> "ai-driven-target-discovery"
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)  # non-alphanumerics -> hyphen
    return text.strip("-")


def save_markdown(area: str, markdown: str) -> str:
    """Write the landscape markdown to outputs/ and return the file path."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{slugify(area)}_{timestamp}.md"
    path = os.path.join(OUTPUT_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)

    return path


def main() -> None:
    # --- Validate the command-line argument -----------------------------
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('Usage: python agent.py "<therapeutic area>"')
        print('Example: python agent.py "AI-driven target discovery"')
        sys.exit(1)

    area = sys.argv[1].strip()
    print(f"\n=== Precision Medicine Landscape Agent ===")
    print(f"Therapeutic area: {area}\n")

    # --- Step 1 & 2: research -------------------------------------------
    # research.gather_research handles its own progress printing and skips
    # any source that fails to fetch, so this returns whatever it could get.
    research_items = research.gather_research(area)

    if not research_items:
        print(
            "\nNo sources could be fetched. This usually means the search "
            "engine blocked the requests or there's no network access. "
            "Try again in a minute, or check your connection."
        )
        sys.exit(1)

    print(f"\nCollected {len(research_items)} sources total.")

    # --- Step 3: synthesize ---------------------------------------------
    print("Synthesizing landscape... (this may take 30-60 seconds)")
    markdown = synthesize.build_landscape(area, research_items)

    # --- Step 4: save ----------------------------------------------------
    path = save_markdown(area, markdown)
    print(f"\nDone. Landscape saved to: {path}")


if __name__ == "__main__":
    main()
