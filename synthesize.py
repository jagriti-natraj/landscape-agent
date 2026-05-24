"""synthesize.py — turn raw research into a VC-ready landscape (two-pass).

This module makes TWO Claude calls per run:

    1. Synthesis call  — produces the draft competitive landscape.
    2. Verification call — audits that draft against the original source
       material and flags any claim not directly supported by the sources.

The two-pass design exists because this is a VC use case where a fabricated
funding number or invented company is catastrophic. The synthesis prompt is
strict about evidence; the verification prompt independently double-checks it.

The verification audit is appended to the bottom of the output markdown.
"""

import re
from datetime import datetime

from config import MODEL, get_client

# Cap the total research text sent to Claude. Main cost control: bounds input
# tokens regardless of how many pages were fetched. Applied to BOTH calls.
MAX_TOTAL_RESEARCH_CHARS = 60_000

# Verbatim phrase the auditor emits when nothing is wrong (used for counting).
ALL_CLEAR_PHRASE = "All claims verified against sources"


# --- System prompts (verbatim, as specified) ---------------------------

SYNTHESIS_SYSTEM_PROMPT = """You are a precision medicine VC research analyst. You will be given source material (web pages, articles) about a therapeutic area, and you must produce a structured competitive landscape.

CRITICAL RULES — read carefully:

1. EVIDENCE REQUIREMENT: Every factual claim (company name, funding amount, stage, investor, year, technology approach) must be supported by a verbatim quote from the source material I provide. If a fact is not directly stated in the sources, you must write "not in sources" or "undisclosed" — do not infer, estimate, extrapolate, or guess.

2. NO PRIOR KNOWLEDGE: You may have information about these companies in your training data. IGNORE IT. Use only the text provided in this context. If you catch yourself adding a fact not present in the sources, stop and mark it "not in sources" instead.

3. CONFIDENCE LABELS: For each company, assign a confidence level:
   - "high" = multiple sources mention with consistent details
   - "medium" = one source, clearly stated
   - "low" = mentioned in passing or details are fuzzy

4. EVIDENCE FIELD: For each company, include a short verbatim quote (under 15 words) from the source material that justifies their inclusion. If you cannot find one, do not include the company.

5. ADVERSARIAL CASE: If the source material does not actually substantiate a real competitive landscape (e.g., the topic is too niche, made-up, or sources are off-topic), state explicitly: "Insufficient source material to construct a landscape" and stop. Do not invent companies to fill space.

6. STAGE LANGUAGE PRECISION: Stage labels must reflect current state, not future plans or transitional language.
   - "Entering Phase 1" / "about to begin Phase 1" → stage is "preclinical"
   - "Will advance to IND-enabling" / "planned IND filing" → stage is "preclinical"
   - "In Phase 1 trials" / "Phase 1 ongoing" → stage is "clinical (Phase 1)"
   - "Phase 2 data presented" / "Phase 2 results" → stage is "clinical (Phase 2)"
   - If source language is ambiguous between current and fut1ure state, default to the EARLIER stage and add a note like "Source language suggests transition; confirm current status."

7. SINGLE-SOURCE AND PRESS-RELEASE CAUTION: Source quality affects confidence.
   - If a company is mentioned in only ONE source, maximum confidence is "low" — regardless of how detailed that source is.
   - If a source URL contains "pr.", "press", "announce", "newsroom", or is from a company's own domain, treat it as a company-controlled press release. Note this in the company entry: "Source is a company press release; independent verification needed."
   - Single-source AND press-release together is the highest-risk combination — confidence must be "low" and the note must be included.

Output format: clean markdown with this structure:

# {Therapeutic Area} Landscape
**Generated:** {timestamp}
**Sources analyzed:** {count}

TARGET COMPANY COUNT: Identify the 8–12 most substantively documented companies only. Do not include companies mentioned only in passing. Quality over quantity — 8 well-evidenced entries are more useful than 19 thin ones. If you have identified more than 12, select the 12 with the strongest evidence and exclude the rest.

## Companies

For each company, a section like:

### {Company Name} [confidence: high/medium/low]
- **Stage:** {preclinical / clinical / approved / platform / undisclosed}
- **Lead Investors:** {names or "undisclosed"}
- **Last Funding:** {amount + date or "undisclosed"}
- **Tech Approach:** {1 sentence}
- **Differentiator:** {1 sentence}
- **Evidence:** "{verbatim quote under 15 words}"
- **Sources:** [{numbered source references}]

## Gap Analysis
{What is missing in the space, what is crowded, what is emerging — only based on what the sources show}

## Sources
{Numbered list of source URLs}"""


VERIFICATION_SYSTEM_PROMPT = """You are an audit checker. I will give you a synthesized landscape report and the original source material that informed it. Your job is to flag any claim in the report that is NOT directly supported by the source material.

For each company in the report, check:
- Is the company name actually in the sources?
- Is the funding amount actually stated in the sources?
- Is the stage actually stated?
- Is the lead investor actually named?
- Is the technology description an accurate summary or an embellishment?

Output a markdown section called "## Verification Audit" that lists every unsupported or partially-supported claim. If everything checks out, write "All claims verified against sources."

Additionally, perform these structural source-quality checks:

- For each company in the report, count how many sources mention it. Flag any company mentioned in only one source as "SINGLE-SOURCE — unverified."
- For each source URL, check if it appears to be a company press release (URL contains "pr.", "press", "announce", "newsroom"). Flag press release sources explicitly.
- If a company is BOTH single-source AND its only source is a press release, escalate the flag to "HIGH RISK — single-source press release. Likely unverifiable. Recommend exclusion or explicit caveat in any downstream use."

These structural flags are mandatory and should appear at the top of the Verification Audit, before claim-by-claim checks.

Be strict. Err on the side of flagging things. A false positive (over-flagging) is cheap. A false negative (missing a hallucination) is expensive."""


def _build_research_context(research_items: list[dict]) -> str:
    """Concatenate sources into one numbered block, within a char budget."""
    chunks: list[str] = []
    total = 0
    for i, item in enumerate(research_items, start=1):
        url = item.get("source_url", "unknown")
        text = item.get("page_text", "")
        chunk = f"--- SOURCE {i}: {url} ---\n{text}\n"
        if total + len(chunk) > MAX_TOTAL_RESEARCH_CHARS:
            break
        chunks.append(chunk)
        total += len(chunk)
    return "\n".join(chunks)


def _count_flagged_claims(audit_text: str) -> int:
    """Heuristically count flagged claims in the audit markdown.

    This is an APPROXIMATION, not an exact parser: the auditor returns free-form
    markdown, so we (a) treat the all-clear phrase as zero, otherwise (b) count
    bullet/numbered list items inside the audit. Good enough to drive a warning.
    """
    if ALL_CLEAR_PHRASE.lower() in audit_text.lower():
        return 0

    # Count markdown list items: "- ...", "* ...", or "1. ..." / "2) ..."
    list_item = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S")
    return sum(1 for line in audit_text.splitlines() if list_item.match(line))


def _run_synthesis(area: str, research_context: str, source_count: int) -> str:
    """First pass: produce the draft landscape."""
    client = get_client()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    user_message = (
        f'Therapeutic area: "{area}"\n'
        f"Timestamp to use in the header: {timestamp}\n"
        f"Number of sources analyzed: {source_count}\n\n"
        f"Below is the source material. Follow ALL critical rules. Use only "
        f"these sources — no prior knowledge.\n\n"
        f"=== SOURCE MATERIAL BEGINS ===\n{research_context}\n"
        f"=== SOURCE MATERIAL ENDS ==="
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYNTHESIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def _run_verification(draft: str, research_context: str) -> str:
    """Second pass: audit the draft against the original sources."""
    client = get_client()

    user_message = (
        f"Here is the synthesized landscape report to audit:\n\n"
        f"=== REPORT BEGINS ===\n{draft}\n=== REPORT ENDS ===\n\n"
        f"Here is the original source material it should be based on:\n\n"
        f"=== SOURCE MATERIAL BEGINS ===\n{research_context}\n"
        f"=== SOURCE MATERIAL ENDS ===\n\n"
        f"Produce the '## Verification Audit' section now."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=VERIFICATION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def build_landscape(area: str, research_items: list[dict]) -> str:
    """Run both passes and return the combined markdown (draft + audit)."""
    research_context = _build_research_context(research_items)
    source_count = len(research_items)

    # --- Pass 1: synthesis ----------------------------------------------
    draft = _run_synthesis(area, research_context, source_count)
    print("Synthesis complete. Running verification audit...")

    # --- Pass 2: verification -------------------------------------------
    audit = _run_verification(draft, research_context)
    flagged = _count_flagged_claims(audit)
    print(f"Verification complete. {flagged} unsupported claims flagged.")
    if flagged >= 3:
        print(
            "⚠️ Multiple unsupported claims detected — review output carefully "
            "before sharing."
        )

    # --- Combine: draft + audit + transparency footer -------------------
    footer = (
        f"\n\n---\n*Generated by the Precision Medicine Landscape Agent "
        f"(two-pass: synthesis + verification) from {source_count} web sources. "
        f"Facts are limited to what those sources contained; verify funding "
        f"figures independently before use.*\n"
    )

    return f"{draft}\n\n{audit}{footer}"
