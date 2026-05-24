"""Shared configuration for the Precision Medicine Landscape Agent.

Centralizes the Claude model name and the Anthropic client so the rest of the
codebase imports them from one place. To change models later, edit MODEL here.
"""

import os
import sys

from dotenv import load_dotenv
from anthropic import Anthropic
from tavily import TavilyClient

# Load variables from the .env file into the environment.
# This makes ANTHROPIC_API_KEY and TAVILY_API_KEY available via os.environ.
load_dotenv()

# The Claude model used for both query generation and synthesis.
# claude-sonnet-4-5 balances cost and quality well for this workload.
MODEL = "claude-sonnet-4-5"


def get_client() -> Anthropic:
    """Return an authenticated Anthropic client.

    Exits with a friendly message if the API key is missing or still the
    placeholder value, so we fail clearly instead of with a cryptic 401.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if not api_key or api_key.startswith("paste"):
        print(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "Open the .env file and replace the placeholder with your real key, "
            "then run again.",
            file=sys.stderr,
        )
        sys.exit(1)

    return Anthropic(api_key=api_key)


def get_tavily_client() -> TavilyClient:
    """Return an authenticated Tavily search client.

    Exits with a friendly message if TAVILY_API_KEY is missing or a placeholder.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()

    if not api_key or api_key.startswith("paste"):
        print(
            "ERROR: TAVILY_API_KEY is not set.\n"
            "Open the .env file and add your Tavily key, then run again.",
            file=sys.stderr,
        )
        sys.exit(1)

    return TavilyClient(api_key=api_key)
