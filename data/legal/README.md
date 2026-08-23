# Offline legal corpus (FMLA + FLSA)

The `doc_type: "law"` chunks of the RAG corpus. Design = **"summarized handout, but every chunk is citation-faithful and linked to the real source."** Unlike the synthetic policy chunks, every law chunk carries a real **`citation`**, a **`url`**, and a **`verbatim_anchor`** — the exact governing phrase quoted from the public-domain source (federal works are public domain, 17 U.S.C. §105).

**All verbatim anchors were verified 2026-08-23** against primary sources: Cornell LII (mirrors official eCFR / U.S. Code) for federal law, California leginfo for state code, and the CA DIR announcement for the 2026 wage rate. Load-bearing numbers are verbatim-accurate; the machine-readable values the tools compute with live in `../state_rules.json` and must stay consistent with these.

> Educational tool — **not legal advice.**

## Files (organized by domain)
| File | Domain | Chunks |
|------|--------|--------|
| `fmla.json` | `fmla` | 10 — §825.104, .110(a)(1)/(a)(2)/(a)(3), .111, .112, .200, .209, .302, .303 |
| `flsa_minimum_wage.json` | `flsa_minwage` | 2 — 29 U.S.C. §206 (federal $7.25), Cal. Lab. Code §1182.12 (CA $16.90) |
| `flsa_overtime.json` | `flsa_overtime` | 2 — 29 U.S.C. §207 (federal >40h ×1.5), Cal. Lab. Code §510 (CA daily OT / double time) |
| `flsa_exemption.json` | `flsa_overtime` | 2 — 29 CFR §541.600 (federal $684/wk), Cal. Lab. Code §515 (CA 2× min wage) |

**Total: 16 law chunks.**

## Chunk schema
Each file is `{corpus, domain, doc_type, notes, chunks: [...]}`. Every chunk is self-contained:
`id, doc_type, domain, jurisdiction, source, citation, url, section, title, revision, effective, retrieved, text, verbatim_anchor`.
The loader merges `chunks` from every `*.json` here and in `../policy/`. `README.md` and file-level `notes` are ignored.

## How the anchors map to the demo
| Anchor | Chunk | Used by |
|--------|-------|---------|
| `at least 12 months` | §825.110(a)(1) | FMLA tenure test (E002 fails) |
| `at least 1,250 hours of service …` | §825.110(a)(2) | FMLA hours test (E003 fails) |
| `50 or more employees … within 75 miles …` | §825.110(a)(3) | FMLA worksite test (E004 fails) |
| `home base, from which their work is assigned …` | §825.111 | field-project worksite rationale (E004) |
| `a total of 12 workweeks …` | §825.200 | entitlement/balance + the policy-conflict floor (E005) |
| `on the same conditions … continuously employed …` | §825.209 | benefit-continuation, cross-domain w/ `pol-BN-5.3` |
| `$7.25 an hour` / `$16.90 per hour` | §206 / §1182.12 | min-wage resolver (E002 compliant TX, E003 violation CA) |
| `one and one-half times the regular rate` / `in excess of eight hours in one workday` | §207 / §510 | OT resolver (E002 federal weekly, E001 CA daily) |
| `not less than $684 per week` / `no less than two times the state minimum wage …` | §541.600 / §515 | exemption / misclassification (E004 correctly exempt, E006 misclassified) |

## Jurisdiction & sourcing
- `jurisdiction`: `federal` or `CA` (drives the more-protective-of-federal-vs-state resolvers).
- Federal law is public domain (17 U.S.C. §105) → verbatim quoting is free.
- DOL WHD Fact Sheets (FS-28 FMLA, FS-14 min wage, FS-23 overtime, FS-17G salary basis) are the plain-language companions; the primary statutory/regulatory citations above are used as the authoritative anchors.
- Any future refresh should go through a one-time `scripts/fetch_legal.py`; the app never fetches at runtime.
