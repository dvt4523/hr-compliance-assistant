"""Gradio Blocks UI — a THIN, polished layer over the headless LangGraph pipeline.

Design: "refined legal-tech" — deep navy + warm ivory + brass gold, Fraunces (serif
display) + Public Sans (the US federal typeface, on-theme for a labour-law tool).
UX patterns: persona gate + profile card, a chat transcript, an evidence panel with
citation cards, a deliberate HITL approval zone, example chips, empty states.

The graph is driven exactly as CLI/eval drive it (build_graph + invoke +
Command(resume=...)), split across two handlers because a request/response UI can't
block inside run_turn's HITL callback. This module imports (never modifies)
src.graph / src.config / src.data_loader. Graph + LLM built lazily.
"""
from __future__ import annotations

import html
import time
import uuid

import gradio as gr
from langgraph.types import Command

from . import config, data_loader
from .graph import build_graph
from .llm import LLMClient

_GRAPH = None
_LLM = None


def _ensure():
    global _GRAPH, _LLM
    if _GRAPH is None:
        _LLM = LLMClient()
        _GRAPH = build_graph(_LLM)
    return _GRAPH, _LLM


# --- content helpers --------------------------------------------------------
def _employee_choices():
    return [(f"{e['employee_id']} · {e['name']} — {e['job_title']}", eid)
            for eid, e in data_loader.load_employees().items()]


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _profile_html(emp_id: str) -> str:
    emp = data_loader.load_employees()[emp_id]
    site = data_loader.site_for_employee(emp)
    pay = (f"${emp['pay_rate_hourly']:.2f}/hr" if emp.get("pay_rate_hourly")
           else f"${emp.get('annual_salary', 0):,}/yr")
    pay_kind = ("paid hourly · earns overtime" if emp.get("classification") == "non-exempt"
                else "salaried · exempt from overtime")
    stats = [
        (f"{emp['tenure_months']}", "months employed"),
        (f"{emp['hours_last_12mo']:,}", "hours worked, past year"),
        (pay, pay_kind),
        (f"{site['headcount_within_75mi']}", "employees within 75 miles"),
        (f"{emp['leave_taken_weeks_ytd']}", "weeks of leave used this year"),
    ]
    stat_html = "".join(
        f'<div class="stat"><b>{v}</b><span>{_esc(label)}</span></div>' for v, label in stats)
    return f"""
    <div class="profile-card">
      <div class="pc-head">
        <span class="pc-name">{_esc(emp['name'])}</span>
        <span class="pc-id">{_esc(emp_id)}</span>
      </div>
      <div class="pc-sub">{_esc(emp['job_title'])} &middot; {_esc(site['name'])}
        <span class="pc-state">{_esc(site['state'])}</span></div>
      <div class="pc-stats">{stat_html}</div>
      <div class="pc-reason">Leave request on file &mdash; <em>{_esc(emp.get('leave_reason','—'))}</em></div>
    </div>"""


_EMPTY_EVIDENCE = ('<div class="evidence empty"><div class="ev-title">Sources</div>'
                   '<p class="ev-empty">Ask a question and the sources behind the answer, '
                   'which rules apply, and any handbook-vs-law conflicts will show here.</p></div>')

# Plain-language names for the internal domain codes (never show raw codes to HR).
DOMAIN_LABEL = {
    "fmla": "Family & medical leave",
    "flsa_minwage": "Minimum wage",
    "flsa_overtime": "Overtime & pay type",
    "benefits": "Benefits",
    "out_of_scope": "Outside scope",
}


def _evidence_html(result: dict, tokens: int, seconds: float) -> str:
    det = result.get("draft", {}) or {}
    route = result.get("route", {}) or {}
    pills = []
    if route.get("domain"):
        label = DOMAIN_LABEL.get(route["domain"], route["domain"])
        pills.append(f'<span class="pill pill-domain">{_esc(label)}</span>')
    if det.get("basis"):
        basis_txt = "state law" if det["basis"] == "state" else "federal law"
        pills.append(f'<span class="pill pill-basis">Based on {basis_txt}</span>')
    pills_html = f'<div class="pills">{"".join(pills)}</div>' if pills else ""

    cites = det.get("citations") or []
    cite_html = ""
    if cites:
        cards = []
        for c in cites:
            tag = _esc(c.get("doc_type", "")).upper()
            tag_cls = "tag-law" if tag == "LAW" else "tag-policy"
            cite_txt = _esc(c.get("citation", ""))
            head = (f'<a href="{_esc(c["url"])}" target="_blank">{cite_txt}</a>'
                    if c.get("url") else cite_txt)
            rev = f'<span class="rev">rev {_esc(c["revision"])}</span>' if c.get("revision") else ""
            cards.append(
                f'<div class="cite-card"><div class="cite-head">'
                f'<span class="tag {tag_cls}">{tag}</span>{head}{rev}</div>'
                f'<blockquote>&ldquo;{_esc(c.get("span",""))}&rdquo;</blockquote></div>')
        cite_html = f'<div class="cites">{"".join(cards)}</div>'

    conflict = det.get("conflict_flag")
    conflict_html = ""
    if conflict:
        conflict_html = (
            f'<div class="conflict"><span class="conflict-badge">Handbook conflicts with the law</span>'
            f'The handbook says <b>{_esc(conflict["policy_value"])}</b>, but the law requires at least '
            f'<b>{_esc(conflict["law_floor"])}</b>.<br><em>{_esc(conflict["resolution"])}</em></div>')

    meta = f'<div class="meta">Answered in {seconds:.1f}s</div>' if seconds else ""
    disc = f'<div class="ev-disclaimer">{_esc(det.get("disclaimer",""))}</div>' if det.get("disclaimer") else ""
    return (f'<div class="evidence"><div class="ev-title">Sources</div>'
            f'{pills_html}{cite_html}{conflict_html}{disc}{meta}</div>')


def _contract_html(req: dict) -> str:
    rows = [("Decision", req.get("action", "")),
            ("Why you're asked", req.get("reason_for_gate", "")),
            ("If you approve", req.get("effect", "")),
            ("Can this be undone?", req.get("reversibility", ""))]
    dl = "".join(f'<div class="ct-row"><dt>{_esc(k)}</dt><dd>{_esc(v)}</dd></div>' for k, v in rows)
    return (f'<div class="approval-head"><span class="ap-dot"></span>'
            f'Your approval needed &mdash; nothing is saved until you sign off</div>'
            f'<dl class="contract">{dl}</dl>')


_STATUS = {
    "finalized": "✓ Finalized", "denied": "Denied", "declined": "Declined",
    "abstained": "Not covered", "abstained_fallback": "Escalated",
    "needs_clarification": "Needs clarification", "error": "Error",
}


def _answer_bubble(result: dict, prefix: str = "") -> str:
    det = result.get("draft", {}) or {}
    tag = _STATUS.get(result.get("status", ""), "")
    badge = f"**{tag}** — " if tag else ""
    return f"{prefix}{badge}{det.get('answer','')}"


# --- handlers ---------------------------------------------------------------
def open_case(emp_id, session):
    session = session or uuid.uuid4().hex[:8]
    if not emp_id:
        return (session, None, '<div class="profile-empty">Pick an employee to open a case.</div>',
                0, None, [], _EMPTY_EVIDENCE, gr.update(visible=False))
    return (session, emp_id, _profile_html(emp_id), 0, None, [], _EMPTY_EVIDENCE,
            gr.update(visible=False))


def on_ask(question, emp_id, session, turn, chat):
    chat = chat or []
    if not emp_id:
        return (chat, _EMPTY_EVIDENCE, gr.update(visible=False), "", gr.update(value=""),
                None, turn, "")
    if not (question or "").strip():
        return (chat, gr.update(), gr.update(visible=False), "", gr.update(value=""),
                None, turn, question)
    graph, llm = _ensure()
    cfg = {"configurable": {"thread_id": f"{session}:{emp_id}:{turn}"}}
    t0, s0 = llm.total_tokens(), time.time()
    state = {"employee_id": emp_id, "user_message": question, "turn": turn}
    try:
        result = graph.invoke(state, cfg)
    except Exception as e:  # noqa: BLE001
        result = {"status": "error",
                  "draft": {"answer": f"Something went wrong: {e}", "citations": [],
                            "disclaimer": config.DISCLAIMER}}
    toks, secs = llm.total_tokens() - t0, time.time() - s0
    chat = chat + [{"role": "user", "content": question}]

    if result.get("__interrupt__"):
        req = result["__interrupt__"][0].value
        det = result.get("draft", {}) or {}
        chat = chat + [{"role": "assistant",
                        "content": _answer_bubble(result, "⏸️ *Awaiting your approval*\n\n")}]
        return (chat, _evidence_html(result, toks, secs), gr.update(visible=True),
                _contract_html(req), gr.update(value=det.get("answer", "")), cfg, turn, "")
    # terminal without a gate
    chat = chat + [{"role": "assistant", "content": _answer_bubble(result)}]
    return (chat, _evidence_html(result, toks, secs), gr.update(visible=False), "",
            gr.update(value=""), None, turn + 1, "")


def on_decide(choice, edited, cfg, turn, chat):
    chat = chat or []
    if not cfg:
        return chat, gr.update(visible=False), turn
    graph, _ = _ensure()
    decision = {"choice": choice, "reviewer": "hr-admin", "decided_at": config.TODAY}
    if choice == "edit":
        decision["edited_answer"] = edited
    result = graph.invoke(Command(resume=decision), cfg)
    note = {"approve": "✓ approved", "edit": "✎ edited & approved", "deny": "⃠ denied"}[choice]
    final = _answer_bubble(result) + f"\n\n_— {note}, recorded to the case log._"
    if chat and chat[-1]["role"] == "assistant":
        chat[-1]["content"] = final
    else:
        chat = chat + [{"role": "assistant", "content": final}]
    return chat, gr.update(visible=False), turn + 1


def _fill(example):
    return example


# --- theme + css ------------------------------------------------------------
THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.blue,
    neutral_hue=gr.themes.colors.stone,
    font=[gr.themes.GoogleFont("Public Sans"), "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("IBM Plex Mono"), "monospace"],
).set(
    body_background_fill="#f4efe4",
    body_text_color="#17293a",
    block_background_fill="#fffef9",
    block_border_color="#e7dcc4",
    block_label_text_color="#5b6b78",
    block_radius="14px",
    input_background_fill="#fffef9",
    button_primary_background_fill="#12324e",
    button_primary_background_fill_hover="#1b466b",
    button_primary_text_color="#f6f1e7",
    button_secondary_background_fill="#efe7d5",
    button_secondary_text_color="#12324e",
)

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap');
.gradio-container { max-width: 1180px !important; margin: 0 auto !important; }
:root { --navy:#12324e; --gold:#b0842f; --ivory:#f4efe4; --line:#e7dcc4; --ink:#17293a; }

/* header */
.app-header { background:linear-gradient(135deg,#12324e,#1c466b); color:#f6f1e7;
  border-radius:14px; padding:11px 20px; margin-bottom:10px; display:flex;
  align-items:center; justify-content:space-between; gap:14px;
  box-shadow:0 8px 24px -16px rgba(18,50,78,.6); }
.app-header .brand { font-family:'Fraunces',Georgia,serif; font-size:1.3rem; font-weight:600;
  letter-spacing:.2px; line-height:1.1; }
.app-header .brand .thin { opacity:.62; font-weight:500; }
.app-header .subtitle { opacity:.82; font-size:.82rem; font-weight:400; margin-top:3px; max-width:72ch; }
/* header sits on a dark navy band -> force light text (beat Gradio's light-mode default) */
.app-header .brand, .app-header .subtitle, .app-header .brand .thin { color:#f6f1e7 !important; }
.disc-chip { flex:none; font-size:.68rem; letter-spacing:.06em; text-transform:uppercase;
  color:#f0e6cf; border:1px solid rgba(240,230,207,.4); border-radius:999px; padding:3px 11px; }

/* section labels */
.sec-label { font-size:.72rem; letter-spacing:.13em; text-transform:uppercase;
  color:#8a7a52; font-weight:700; margin:4px 2px -4px; }

/* employee card picker */
.emp-grid { display:grid !important; grid-template-columns:1fr; gap:7px; }
.emp-card { text-align:left !important; white-space:pre-line !important; line-height:1.3 !important;
  justify-content:flex-start !important; align-items:flex-start !important;
  background:#fffef9 !important; border:1px solid var(--line) !important; border-radius:10px !important;
  padding:9px 12px !important; color:#3a5670 !important; font-weight:600 !important; font-size:.75rem !important;
  box-shadow:none !important; min-height:auto !important;
  transition:border-color .15s ease, transform .15s ease, box-shadow .15s ease; }
.emp-card::first-line { font-size:.9rem; color:var(--navy); }
.emp-card:hover { border-color:var(--gold) !important; transform:translateX(2px);
  box-shadow:-2px 4px 14px -12px rgba(18,50,78,.5) !important; }

/* profile */
.profile-card { border:1px solid var(--line); border-radius:14px; background:#fffef9; padding:16px 18px; }
.profile-empty { color:#9a927e; font-style:italic; font-size:.88rem; padding:2px 2px 6px; }
.pc-head { display:flex; align-items:baseline; gap:10px; }
.pc-name { font-family:'Fraunces',Georgia,serif; font-size:1.28rem; font-weight:600; color:var(--navy); }
.pc-id { font-family:'IBM Plex Mono',monospace; font-size:.74rem; color:#fff; background:var(--navy);
  padding:2px 8px; border-radius:6px; }
.pc-sub { color:#4a5b68; margin-top:2px; font-size:.92rem; }
.pc-state { background:var(--gold); color:#fff; font-size:.68rem; font-weight:700; padding:1px 7px;
  border-radius:5px; margin-left:6px; letter-spacing:.05em; }
.pc-stats { display:flex; flex-wrap:wrap; gap:20px; margin:14px 0 10px; }
.stat b { display:block; font-family:'Fraunces',Georgia,serif; font-size:1.15rem; color:var(--navy); }
.stat span { font-size:.72rem; color:#8a8676; text-transform:uppercase; letter-spacing:.05em; }
.pc-reason { border-top:1px dashed var(--line); padding-top:10px; font-size:.9rem; color:#4a5b68; }

/* evidence panel */
.evidence { border:1px solid var(--line); border-radius:14px; background:#fffef9; padding:16px 18px;
  position:sticky; top:12px; }
.ev-title { font-family:'Fraunces',Georgia,serif; font-size:1.05rem; color:var(--navy); font-weight:600;
  margin-bottom:10px; }
.ev-empty { color:#8a8676; font-style:italic; font-size:.9rem; }
.pills { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }
.pill { font-size:.74rem; background:#efe7d5; color:#5b5233; padding:3px 10px; border-radius:999px; }
.pill-domain { background:var(--navy); color:#f6f1e7; font-family:'IBM Plex Mono',monospace; }
.pill-basis { background:#e7efe3; color:#3c5a3c; }
.cite-card { border:1px solid var(--line); border-left:3px solid var(--navy); border-radius:8px;
  padding:9px 12px; margin-bottom:8px; background:#fdfbf4; }
.cite-head { display:flex; align-items:center; gap:8px; font-size:.86rem; flex-wrap:wrap; }
.cite-head a { color:var(--navy); font-weight:600; text-decoration:none; border-bottom:1px solid #c9d4dd; }
.tag { font-size:.64rem; font-weight:700; letter-spacing:.06em; padding:2px 7px; border-radius:5px; color:#fff; }
.tag-law { background:var(--navy); }
.tag-policy { background:var(--gold); }
.rev { color:#9a927e; font-size:.72rem; }
.cite-card blockquote { margin:6px 0 0; padding-left:10px; border-left:2px solid var(--line);
  color:#3f4d57; font-style:italic; font-size:.86rem; }
.conflict { border:1px solid #e6b8ac; background:#fbf1ee; border-radius:10px; padding:11px 13px;
  margin-top:10px; font-size:.86rem; color:#7a3527; }
.conflict-badge { display:block; font-weight:700; color:#a23b28; font-size:.72rem; letter-spacing:.05em;
  text-transform:uppercase; margin-bottom:4px; }
.ev-disclaimer { margin-top:12px; font-size:.76rem; color:#9a927e; font-style:italic;
  border-top:1px solid var(--line); padding-top:9px; }
.meta { margin-top:8px; font-family:'IBM Plex Mono',monospace; font-size:.72rem; color:#b0a88f; }

/* approval zone */
.approval { border:1.5px solid var(--gold) !important; background:#fdf8ec !important;
  border-radius:14px !important; box-shadow:0 8px 24px -16px rgba(176,132,47,.7); }
.approval-head { font-family:'Fraunces',Georgia,serif; font-weight:600; color:#8a5a12; font-size:1.02rem;
  display:flex; align-items:center; gap:9px; }
.ap-dot { width:9px; height:9px; border-radius:50%; background:var(--gold);
  box-shadow:0 0 0 4px rgba(176,132,47,.2); }
.contract { margin:10px 0 4px; }
.contract .ct-row { display:grid; grid-template-columns:120px 1fr; gap:10px; padding:4px 0;
  border-top:1px dotted var(--line); font-size:.87rem; }
.contract dt { color:#8a7a52; font-weight:700; }
.contract dd { margin:0; color:#3f4d57; }

/* light-canvas safety net (design is light-only) + flatten Gradio's nested boxes */
.gradio-container { background:#f4efe4 !important; }
.approval .block, .approval .form { background:transparent !important; border:none !important;
  box-shadow:none !important; }
.approval label span, .approval .block-title { color:#8a5a12 !important; }
.gradio-container textarea, .gradio-container input[type=text] {
  background:#fffdf7 !important; color:#17293a !important; }
"""


def build_blocks():
    with gr.Blocks(title="Northwind HR · Compliance Assistant") as demo:  # theme/css → launch() (Gradio 6)
        session = gr.State(None)
        emp_state = gr.State(None)
        turn_state = gr.State(0)
        cfg_state = gr.State(None)

        gr.HTML(
            '<div class="app-header">'
            '<div class="hd-left">'
            '<div class="brand">Northwind HR <span class="thin">· Compliance Assistant</span></div>'
            '<div class="subtitle">Quick, clearly-sourced answers on employee leave, pay, and '
            'benefits — you review and approve every answer before it is final.</div>'
            '</div>'
            '<span class="disc-chip">Not legal advice</span>'
            '</div>')

        with gr.Row(equal_height=False):
            # left — employee picker (sidebar)
            with gr.Column(scale=2, min_width=170):
                gr.HTML('<div class="sec-label">Employees</div>')
                emp_buttons = []
                with gr.Column(elem_classes="emp-grid"):
                    for _eid, _e in data_loader.load_employees().items():
                        _b = gr.Button(f"{_e['name']}\n{_e['job_title']}", elem_classes="emp-card")
                        emp_buttons.append((_b, _eid))

            # middle — conversation
            with gr.Column(scale=5):
                gr.HTML('<div class="sec-label">Conversation</div>')
                chatbot = gr.Chatbot(height=360, show_label=False)
                with gr.Row():
                    question = gr.Textbox(show_label=False, scale=5, lines=1,
                                          placeholder="Ask about the selected employee…")
                    ask_btn = gr.Button("Ask", variant="primary", scale=1, min_width=90)
                with gr.Group(visible=False, elem_classes="approval") as approval_row:
                    contract_html = gr.HTML()
                    edit_box = gr.Textbox(label="Revise the answer (used only with “Edit & approve”)",
                                          lines=2)
                    with gr.Row():
                        approve_btn = gr.Button("Approve", variant="primary")
                        edit_btn = gr.Button("Edit & approve", variant="secondary")
                        deny_btn = gr.Button("Deny", variant="stop")

            # right — case details (profile + evidence)
            with gr.Column(scale=3):
                gr.HTML('<div class="sec-label">Case</div>')
                profile_html = gr.HTML('<div class="profile-empty">Pick an employee to open a case.</div>')
                evidence_html = gr.HTML(_EMPTY_EVIDENCE)

        # wiring
        open_out = [session, emp_state, profile_html, turn_state, cfg_state, chatbot,
                    evidence_html, approval_row]
        for _btn, _eid in emp_buttons:
            _btn.click(lambda s, e=_eid: open_case(e, s), [session], open_out)

        ask_out = [chatbot, evidence_html, approval_row, contract_html, edit_box,
                   cfg_state, turn_state, question]
        ask_btn.click(on_ask, [question, emp_state, session, turn_state, chatbot], ask_out)
        question.submit(on_ask, [question, emp_state, session, turn_state, chatbot], ask_out)

        dec_out = [chatbot, approval_row, turn_state]
        approve_btn.click(lambda cfg, t, ch: on_decide("approve", "", cfg, t, ch),
                          [cfg_state, turn_state, chatbot], dec_out)
        edit_btn.click(lambda ed, cfg, t, ch: on_decide("edit", ed, cfg, t, ch),
                       [edit_box, cfg_state, turn_state, chatbot], dec_out)
        deny_btn.click(lambda cfg, t, ch: on_decide("deny", "", cfg, t, ch),
                       [cfg_state, turn_state, chatbot], dec_out)
    return demo


# Force the light palette (the whole design is light; dark mode makes text vanish).
# Redirect early, before Gradio renders, if the client isn't already in light mode.
FORCE_LIGHT_HEAD = (
    "<script>if(new URLSearchParams(location.search).get('__theme')!=='light'){"
    "const u=new URL(location.href);u.searchParams.set('__theme','light');"
    "location.replace(u.toString());}</script>"
)

if __name__ == "__main__":
    build_blocks().launch(theme=THEME, css=CSS, head=FORCE_LIGHT_HEAD)
