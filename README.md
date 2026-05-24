Precision Medicine Landscape Agent
A research assistant that compresses competitive landscape work from 2 hours to 15 minutes. Give it a therapeutic area, get back a structured VC-ready landscape: companies, stage, lead investors, funding, tech approach, and a gap analysis — with every claim traced to a source.
Built for my own use as a UofT biomedical engineering student navigating the Canadian precision medicine ecosystem. I needed to map who's building what, where the gaps are, and how Canadian companies compare to global peers — weekly, not occasionally.

What it does

Generates 5 typed search queries across financial, regulatory, industry analysis, partnership, and academic angles — geographically targeted toward the Canadian ecosystem
Fetches and classifies sources using a tiered trust system: regulatory filings and trade journalism are prioritized over press releases, with a quota algorithm that prevents any single source type from dominating
Synthesizes a structured landscape using Claude with strict evidence requirements — every claim must be supported by a verbatim quote from the source material, or it gets marked "not in sources"
Runs a verification pass that independently audits the synthesis output against the original sources, flags unsupported claims, and escalates single-source press release entries as HIGH RISK


Anti-hallucination architecture
This is a VC use case. A fabricated funding number or invented company is worse than no output at all. The agent has three independent layers of defense:
Layer 1 — Source diversity quotas (research.py + source_quality.py)
The agent classifies every URL before fetching and enforces quotas: at least 2 regulatory sources, 4+ high-trust journalism sources, press releases capped at 2. A collect-then-filter algorithm prevents any one search angle from exhausting the fetch budget before higher-quality sources are evaluated.
Layer 2 — Evidence-restricted synthesis (synthesize.py)
The synthesis system prompt explicitly prohibits prior knowledge. Every factual claim requires a verbatim source quote. Stage labels must reflect current state, not future plans ("entering Phase 1" → preclinical, not clinical). Single-source companies are capped at low confidence regardless of detail level.
Layer 3 — Independent verification pass (synthesize.py)
A separate Claude call audits the draft landscape against the original source material. It performs structural checks (single-source flags, press release escalations) before claim-by-claim verification. If 3+ claims are flagged, a terminal warning fires before the file is saved.

Sample output
outputs/ai-driven-target-discovery_20260524_182512.md
Run on "AI-driven target discovery" with Canadian ecosystem targeting. 12 companies identified including BenchSci (Toronto), Deep Genomics (Toronto), and Valence Discovery (Montreal). 13 claims flagged by the verifier out of ~80 total — all minor (inferred stage labels, unsupported clarifications). Gap analysis includes a Canada-specific paragraph on the $936M Pan-Canadian AI Strategy and funding gaps vs. US peers.
Cost: $0.14. Runtime: ~90 seconds.

How to run
Prerequisites

Python 3.12+
Anthropic API key (console.anthropic.com)
Tavily API key (tavily.com — free tier, 1,000 searches/month)

Setup
bashgit clone https://github.com/jagriti-natraj/landscape-agent
cd landscape-agent
python3.12 -m venv venv
source venv/bin/activate
pip install anthropic tavily-python python-dotenv requests beautifulsoup4 streamlit
Create a .env file:
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=tvly-...
Run
bashpython agent.py "AI-driven target discovery"
python agent.py "Canadian precision medicine diagnostics"
python agent.py "lipid nanoparticle drug delivery"
Output is saved to outputs/ as a markdown file with timestamp.

Architecture
agent.py          — orchestrator, CLI entry point, file output
research.py       — Tavily search, source classification, quota-based selection
source_quality.py — URL classification by trust tier (regulatory / high_trust / press_release / other)
synthesize.py     — two-pass Claude synthesis + verification
config.py         — model config, API client initialization

Limitations

Public sources only. The agent operates on publicly indexed web content. Proprietary databases (Pitchbook, Crunchbase Pro) and paywalled trade press are outside scope.
Canadian ecosystem targeting is a lens, not a filter. Queries are Canada-constrained but well-funded global companies dominate open-web coverage. Canadian companies (BenchSci, Deep Genomics, Valence) surface clearly alongside international peers.
Source quality depends on Tavily's index. Early-stage companies with no press coverage won't appear regardless of prompt design.
Verify funding figures independently before use. The verification audit flags uncertain claims, but primary sources (Pitchbook, company IR pages, press releases) should confirm any figure used in a real investment decision.


What I'd build next

ClinicalTrials.gov API v2 integration for the regulatory angle (currently limited by JavaScript rendering)
SEC EDGAR API for Canadian equivalent (SEDAR) filings
Streamlit UI for non-technical users (Day 2 scope, skeleton already in place)
MCP server wrapper so the agent can be called from Claude directly


Built with

Anthropic Claude — synthesis and verification
Tavily — search and content extraction
Python 3.12