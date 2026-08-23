# Northwind Engineering — Employee Handbook (synthetic policy corpus)

Fully **fictional** company policy for the HR-compliance demo. These are the `doc_type: "policy"` chunks of the RAG corpus. Because policy is not law, policy chunks carry **no `url` and no `verbatim_anchor`** (there is nothing external to anchor to); the assistant labels their citations `[POLICY]` vs. the `[LAW]` chunks in `../legal/`.

## Files (one per handbook part)
| File | Handbook part | Chunks |
|------|---------------|--------|
| `01_leaves_of_absence.json` | LV-4 — Leaves of Absence | LV-4.1 … LV-4.6 (7, incl. two LV-4.2 revisions) |
| `02_compensation_and_hours.json` | CH-3 — Compensation & Working Hours | CH-3.1 … CH-3.5 (5) |
| `03_benefits.json` | BN-5 — Employee Benefits | BN-5.1 … BN-5.4 (4) |
| `04_workplace_policies.json` | WP-6 — Workplace Policies | WP-6.1 … WP-6.4 (4) |

**Total: 20 policy chunks.** Current handbook revision = `2026-01` (effective 2026-01-01).

## Chunk schema
Each file is `{source, part, current_revision, doc_type, notes, chunks: [...]}`. Every chunk is self-contained:
`id, doc_type, source, citation, section, title, revision, effective, domain, text`.
A loader merges `chunks` from every `*.json` here (and in `../legal/`) into one flat list. The `README.md` and the file-level `notes` field are ignored by the loader.

## `domain` vocabulary (routing / soft retrieval filter)
`fmla` · `flsa_minwage` · `flsa_overtime` · `benefits` · `general` (neutral/out-of-scope filler). Treated as a soft signal, not a hard filter.

## Deliberate demo hooks (what each chunk is for)
| Hook | Chunk(s) | Why it's here |
|------|----------|---------------|
| **Policy-vs-law conflict** | `pol-LV-4.2-2026` (8 wks) | Below the FMLA 12-week floor → the assistant must answer *and* flag the conflict, deferring to the legal floor. Headline demo. |
| **Superseded revision (stale filter)** | `pol-LV-4.2-2024-06` (6 wks, effective 2024-06-01) vs `pol-LV-4.2-2026` (8 wks, effective 2026-01-01) | `drop_superseded()` must return only the current revision. |
| **More-generous, NO conflict** | `pol-LV-4.3-2026` (12 wks *paid* parental) | Exceeds the floor → apply it, do **not** flag. Tests that the agent doesn't cry "conflict" on every difference. |
| **Notice / procedure** | `pol-LV-4.4-2026` | Aligns with FMLA's 30-day notice rule → cite policy + law together. |
| **FLSA policy pair** | `pol-CH-3.1/3.2/3.5` | Compliant pay clauses that give a `[POLICY]` citation to pair with the FLSA `[LAW]` chunks. The real pay problems (E003 below CA min, E006 misclassified) live in the employee DB, not here. |
| **Benefits (retrieval-only)** | `pol-BN-5.1/5.2/5.4` | Answerable plan lookups; the assistant must abstain on computed/account-specific asks (exact balance, individual premium). |
| **Cross-domain [LAW]+[POLICY]** | `pol-BN-5.3-2026` | Pairs with FMLA §825.209 (benefit continuation during leave). |
| **Out-of-scope present in handbook** | `pol-WP-6.3-2026` (parking) | A compliance query must not retrieve it; a parking query is outside scope → decline/abstain, not wrong-retrieval. |
| **Neutral discriminators** | bereavement, jury, meal/rest, paydays, remote work, PTO, code of conduct | Force retrieval to discriminate; improve eval realism. |

> Educational demo — **not legal advice**, and not a real company.
