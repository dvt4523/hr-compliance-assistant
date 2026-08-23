"""Prompt builders — Role / Context / Task / Constraints / Format (course idiom).

Senior-persona system prompts; the model classifies and drafts, code decides.
"""
from __future__ import annotations

import json

ROUTE_SYSTEM = "You are a senior HR-compliance routing classifier."

DRAFT_SYSTEM = (
    "You are a senior HR-compliance analyst helping an HR administrator who is not a lawyer. "
    "Answer ONLY from the passages and the computed result provided. "
    "Write in plain, friendly, everyday language. Prefer plain terms over legal acronyms: "
    "say 'family and medical leave' rather than the bare acronym 'FMLA' (you may write "
    "'family and medical leave (FMLA)' once if it helps), 'overtime pay rules' rather than 'FLSA', "
    "and briefly explain any legal term in simple words. Keep sentences short. "
    "Cite the exact span you rely on, or abstain. Never invent numbers or rules. "
    "This is general information, not legal advice."
)


def route_prompt(user_message: str) -> str:
    return f"""# Task
Classify the HR admin's question into exactly one compliance domain and rate your confidence.

# Context
The selected employee's full HR record — hire date, tenure, hours worked, worksite headcount,
pay rate, classification, and leave already taken — is ALREADY loaded, and deterministic tools
compute any determination from it. NEVER ask the HR admin to supply employee facts; they are on
file. Treat questions like "is this employee eligible?", "how much leave remains?", or "are we
paying them enough?" as fully answerable and in scope.

# Domains
- fmla: family & medical leave — eligibility, entitlement/duration, qualifying reasons, leave policy
- flsa_minwage: minimum-wage compliance
- flsa_overtime: overtime pay, exempt vs non-exempt classification
- benefits: 401(k), health insurance, benefit continuation during leave (informational only)
- out_of_scope: anything else (ADA, workers' comp, severance/bonus, termination, hiring, or non-HR)

# Instructions
- Set needs_clarification=true (with a clarifying_question) ONLY when the DOMAIN or intent is
  genuinely unclear (e.g. a bare "I have a question") — never merely because employee facts seem
  unstated, since they are already on file.
- confidence is a number in [0,1].

# Question
{user_message}"""


def _format_passages(retrieved: list[dict]) -> str:
    lines = []
    for i, c in enumerate(retrieved):
        tag = "LAW" if c.get("doc_type") == "law" else "POLICY"
        anchor = f'  (governing phrase: "{c["verbatim_anchor"]}")' if c.get("verbatim_anchor") else ""
        rev = c.get("revision", "")
        lines.append(f'[{i}] ({tag}) {c.get("citation","")} rev {rev}: {c.get("text","")}{anchor}')
    return "\n".join(lines)


def draft_prompt(user_message: str, retrieved: list[dict], tool_result: dict | None,
                 domain: str) -> str:
    computed = ""
    if tool_result:
        computed = (
            "\n# Computed determination (authoritative — produced by a deterministic tool)\n"
            + json.dumps(tool_result, indent=2)
        )
    return f"""# Role
Senior HR-compliance analyst. Domain of this question: {domain}.

# Passages (the ONLY source you may quote)
{_format_passages(retrieved)}
{computed}

# Task
Answer the HR admin's question for this specific employee.
- If a passage (and the computed result, when present) governs the question, set status="answered", write a clear answer, and in `used` list AT LEAST ONE passage index whose rule/number governs the outcome, with the EXACT span you quoted from it (verbatim, copy it character-for-character). For a LAW passage, quote its governing phrase. An answered determination MUST cite at least one passage — never answer from the computed result alone without citing the law or policy behind it.
- State the `basis` ("federal" or "state") if a jurisdiction rule decided the outcome.
- If no passage governs the question, or it asks for an account-specific/computed figure not provided, set status="not_covered" and leave `used` empty. Never guess.

# Question
{user_message}"""
