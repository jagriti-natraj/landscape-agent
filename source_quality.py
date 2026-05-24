# source_quality.py — classify sources by trust tier and type
#
# Classification is precedence-ordered: regulatory > high_trust > press_release > other.
# A domain that matches the high-trust list is high-trust REGARDLESS of any
# URL substring patterns. URL patterns only apply to unknown domains.

# Independent journalism / trade press — high trust for biotech landscape work
HIGH_TRUST_DOMAINS = [
    # Biotech/pharma trade journalism
    "endpts.com", "statnews.com", "fiercebiotech.com",
    "biopharmadive.com", "biospace.com", "bioworld.com",
    "the-scientist.com", "pharmexec.com", "clinicaltrialsarena.com",
    "genengnews.com",
    # Peer-reviewed science publishers / journals
    "nature.com", "science.org", "thelancet.com",
    "nejm.org", "cell.com", "frontiersin.org",
    # Specialist regulatory / FDA law
    "fdli.org",
    # Canadian biotech ecosystem, funders, and government bodies
    "marsdd.com",
    "genomecanada.ca",
    "cihr-irsc.gc.ca",
    "lifesciencesontario.ca",
    "biopharma.ca",
    "canadianhealthcarenetwork.ca",
    "ic.gc.ca",
    "nrc-cnrc.gc.ca",
    "investottawa.ca",
]

# Regulatory / public data — high trust, primary source
REGULATORY_DOMAINS = [
    "clinicaltrials.gov", "fda.gov", "ema.europa.eu",
    "sec.gov", "ncbi.nlm.nih.gov", "europepmc.org",
    "who.int",
]

# Press release distribution networks — almost always company-controlled
PRESS_RELEASE_DOMAINS = [
    "prnewswire.com", "businesswire.com", "globenewswire.com",
    "prweb.com", "newswire.com", "accesswire.com",
]

# URL substrings that signal a press release on UNKNOWN domains only.
# These patterns are intentionally specific to avoid false positives on
# legitimate journalism URLs (e.g., statnews.com/news/... is not a press release).
PRESS_RELEASE_URL_PATTERNS = [
    "/press-release",
    "/press-releases",
    "newsroom",
    "/announce",
    "/announcement",
    "investor-relations",
    "ir.",  # investor relations subdomain
]


def classify_source(url: str) -> str:
    """Classify a URL into one of: regulatory, high_trust, press_release, other.

    Precedence is strict:
      1. Regulatory domain → 'regulatory' (always wins).
      2. High-trust domain → 'high_trust' (URL patterns IGNORED on these domains
         to prevent false-positives like statnews.com/news/... being demoted).
      3. Press-release distribution domain → 'press_release'.
      4. URL pattern match → 'press_release' (only reached for unknown domains).
      5. Otherwise → 'other'.
    """
    url_lower = url.lower()

    # 1. Regulatory: always wins.
    for domain in REGULATORY_DOMAINS:
        if domain in url_lower:
            return "regulatory"

    # 2. High-trust journalism: wins over any URL substring match.
    # This is the false-positive guard. Do NOT fall through to pattern matching.
    for domain in HIGH_TRUST_DOMAINS:
        if domain in url_lower:
            return "high_trust"

    # 3. Press-release distribution networks.
    for domain in PRESS_RELEASE_DOMAINS:
        if domain in url_lower:
            return "press_release"

    # 4. URL pattern match — only for domains not classified above.
    for pattern in PRESS_RELEASE_URL_PATTERNS:
        if pattern in url_lower:
            return "press_release"

    return "other"
