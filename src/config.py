"""Configuration: env, model tiers, pinned constants, data paths.

All tunables live here so the pipeline reads top-to-bottom without magic numbers.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Provider (Siraya model router, OpenAI-compatible) ---------------------
SIRAYA_API_KEY = os.getenv("SIRAYA_API_KEY")
SIRAYA_BASE_URL = os.getenv("SIRAYA_BASE_URL", "https://llm.siraya.ai/v1")

# Role-based model tiering (all verified to support json_schema on our key).
ROUTER_MODEL = os.getenv("SIRAYA_ROUTER_MODEL", "gemini-2.5-flash-lite")
RERANK_MODEL = os.getenv("SIRAYA_RERANK_MODEL", "gemini-2.5-flash-lite")
DRAFT_MODEL = os.getenv("SIRAYA_DRAFT_MODEL", "gemini-2.5-flash")
CHAT_MODEL = os.getenv("SIRAYA_CHAT_MODEL", "gemini-2.5-flash")
REASONING_MODEL = os.getenv("SIRAYA_REASONING_MODEL", "claude-sonnet-4.5")

# --- Pinned constants ------------------------------------------------------
# TODAY is pinned (labs pin a fixed "today"); do NOT use date.today() in logic.
TODAY = "2026-08-23"

# FMLA ground truth
FMLA_TENURE_MONTHS = 12
FMLA_HOURS = 1250
FMLA_WORKSITE_HEADCOUNT = 50
FMLA_WORKSITE_MILES = 75
FMLA_ENTITLEMENT_WEEKS = 12

# Retrieval / routing gates
RELEVANCE_BAR = 0.5      # abstain if top rerank relevance below this
CONF_BAR = 0.6           # escalate/clarify if route confidence below this
PREFILTER_K = 8          # keyword candidates before rerank
RETRIEVE_K = 4           # chunks passed to the drafter

# Bounded loops
MAX_CLARIFY_LOOPS = 2
MAX_REVISE = 1

HOURS_PER_YEAR = 2080    # full-time hours, for salary <-> hourly conversion

DISCLAIMER = (
    "This is general information from company policy and public law, not legal advice. "
    "Confirm with counsel before acting."
)

# Standing human-escalation fallback for anything the assistant can't answer reliably.
ESCALATE_MSG = (
    "I can't answer this reliably from the policy and law on file — "
    "please escalate to HR leadership or employment counsel."
)

# --- Data paths ------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
LEGAL_DIR = DATA_DIR / "legal"
POLICY_DIR = DATA_DIR / "policy"
EMPLOYEES_FILE = DATA_DIR / "employees.json"
SITES_FILE = DATA_DIR / "sites.json"
STATE_RULES_FILE = DATA_DIR / "state_rules.json"
CASE_LOG_FILE = DATA_DIR / "case_log.jsonl"   # episodic memory (append-only)


def require_key() -> str:
    """Return the Siraya key or raise — call before any live LLM use."""
    if not SIRAYA_API_KEY:
        raise RuntimeError(
            "Missing SIRAYA_API_KEY. Copy .env.example to .env and set a real key."
        )
    return SIRAYA_API_KEY
