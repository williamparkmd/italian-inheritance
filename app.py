#!/usr/bin/env python3
"""
Inheritance — Document Reports & AI Chat
Reads documents from shared Dropbox folder, shows structured reports,
and lets family members ask questions and create reports via AI.
"""

import json
import os
from datetime import datetime, timedelta

import anthropic
import streamlit as st
from dotenv import load_dotenv

load_dotenv(".env.local")

from scan import (
    get_dropbox_client,
    get_dropbox_fingerprint,
    load_app_data,
    parse_assets,
    parse_heirs,
    save_app_data,
    scan_dropbox,
)

# --- Config ---
st.set_page_config(
    page_title="Inheritance",
    page_icon="\U0001f3db\ufe0f",
    layout="wide",
)

# --- State Init ---
for key, default in [
    ("messages", []),
    ("data", None),
    ("dropbox_fingerprint", None),
    ("reports", []),
    ("notes", []),
    ("interview", []),
    ("initialized", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default


def load_documents():
    """Scan Dropbox via API and parse data."""
    dbx = get_dropbox_client()
    if not dbx:
        return None
    documents = scan_dropbox(dbx)
    st.session_state.dropbox_fingerprint = get_dropbox_fingerprint(dbx)
    return {
        "scan_date": datetime.now().isoformat(),
        "documents": documents,
        "heirs": parse_heirs(documents),
        "assets": parse_assets(documents),
    }


def load_persistent_data():
    """Load chat history, reports, notes, and interview from Dropbox."""
    dbx = get_dropbox_client()
    if not dbx:
        return
    for key, filename in [
        ("messages", "chat_history.json"),
        ("reports", "reports.json"),
        ("notes", "notes.json"),
        ("interview", "interview.json"),
    ]:
        data = load_app_data(dbx, filename)
        if data:
            st.session_state[key] = data


def _save(filename, key):
    dbx = get_dropbox_client()
    if dbx:
        save_app_data(dbx, filename, st.session_state[key])


def save_chat_history():
    _save("chat_history.json", "messages")


def save_reports():
    _save("reports.json", "reports")


def save_notes():
    _save("notes.json", "notes")


def save_interview():
    _save("interview.json", "interview")


# --- Auto-load on first open ---
if not st.session_state.initialized:
    with st.spinner("Loading from Dropbox..."):
        st.session_state.data = load_documents()
        load_persistent_data()
        st.session_state.initialized = True


# --- Poll Dropbox for document changes every 30 seconds ---
@st.fragment(run_every=timedelta(seconds=30))
def _poll_dropbox():
    dbx = get_dropbox_client()
    if not dbx:
        return
    fingerprint = get_dropbox_fingerprint(dbx)
    if fingerprint and fingerprint != st.session_state.dropbox_fingerprint:
        st.session_state.data = load_documents()
        st.rerun(scope="app")


_poll_dropbox()


# --- AI Tools ---
AI_TOOLS = [
    {
        "name": "update_report",
        "description": (
            "Create or update a section of the inheritance report. "
            "Use this when the user asks to create, modify, add to, or correct "
            "any part of the report. Each section has a unique ID \u2014 reuse the "
            "same ID to update an existing section."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "Unique identifier (e.g. 'division_proposal'). Lowercase with underscores.",
                },
                "title": {
                    "type": "string",
                    "description": "Display title for the section",
                },
                "content": {
                    "type": "string",
                    "description": "Markdown content. Use tables, lists, headers as needed.",
                },
            },
            "required": ["section_id", "title", "content"],
        },
    },
    {
        "name": "delete_report_section",
        "description": "Remove a section from the report.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "The section ID to remove",
                },
            },
            "required": ["section_id"],
        },
    },
    {
        "name": "add_note",
        "description": (
            "Save a correction or important fact provided by the user. "
            "Use this whenever the user corrects information or provides new facts "
            "not in the documents. Notes persist and override document data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {
                    "type": "string",
                    "description": "The correction or fact to remember. Be specific and concise.",
                },
            },
            "required": ["note"],
        },
    },
    {
        "name": "remove_note",
        "description": "Remove a previously saved note that is no longer accurate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_index": {
                    "type": "integer",
                    "description": "0-based index of the note to remove.",
                },
            },
            "required": ["note_index"],
        },
    },
    {
        "name": "save_interview_entry",
        "description": (
            "Save a question-answer pair from the interview. Use this during interviews "
            "to record the user's answer. Each entry has a topic for grouping."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Category: 'deceased', 'family', 'properties', 'finances', 'legal', 'agreements', or 'other'.",
                },
                "question": {
                    "type": "string",
                    "description": "The interview question that was asked.",
                },
                "answer": {
                    "type": "string",
                    "description": "Summary of the user's answer. Be factual and concise.",
                },
            },
            "required": ["topic", "question", "answer"],
        },
    },
    {
        "name": "update_interview_entry",
        "description": "Update the answer of an existing interview entry when the user provides a correction.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_index": {
                    "type": "integer",
                    "description": "0-based index of the interview entry to update.",
                },
                "answer": {
                    "type": "string",
                    "description": "The corrected answer.",
                },
            },
            "required": ["entry_index", "answer"],
        },
    },
]


def handle_tool_call(name, params):
    """Execute a tool call and return a result string."""
    if name == "update_report":
        section_id = params["section_id"]
        title = params["title"]
        content = params["content"]
        for section in st.session_state.reports:
            if section["id"] == section_id:
                section["title"] = title
                section["content"] = content
                section["updated_at"] = datetime.now().isoformat()
                save_reports()
                return f"Updated report section '{title}'"
        st.session_state.reports.append({
            "id": section_id,
            "title": title,
            "content": content,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        })
        save_reports()
        return f"Created report section '{title}'"

    if name == "delete_report_section":
        section_id = params["section_id"]
        before = len(st.session_state.reports)
        st.session_state.reports = [
            s for s in st.session_state.reports if s["id"] != section_id
        ]
        if len(st.session_state.reports) < before:
            save_reports()
            return f"Deleted report section '{section_id}'"
        return f"Section '{section_id}' not found"

    if name == "add_note":
        st.session_state.notes.append({
            "note": params["note"],
            "added_at": datetime.now().isoformat(),
        })
        save_notes()
        return f"Saved note: '{params['note']}'"

    if name == "remove_note":
        idx = params["note_index"]
        if 0 <= idx < len(st.session_state.notes):
            removed = st.session_state.notes.pop(idx)
            save_notes()
            return f"Removed note: '{removed['note']}'"
        return f"Invalid note index {idx}"

    if name == "save_interview_entry":
        st.session_state.interview.append({
            "topic": params["topic"],
            "question": params["question"],
            "answer": params["answer"],
            "answered_at": datetime.now().isoformat(),
        })
        save_interview()
        return f"Saved interview entry under '{params['topic']}'"

    if name == "update_interview_entry":
        idx = params["entry_index"]
        if 0 <= idx < len(st.session_state.interview):
            st.session_state.interview[idx]["answer"] = params["answer"]
            st.session_state.interview[idx]["answered_at"] = datetime.now().isoformat()
            save_interview()
            return f"Updated interview entry {idx}"
        return f"Invalid entry index {idx}"

    return "Unknown tool"


def send_to_ai(user_message):
    """Send a message to the AI, handle tool use loop, save results."""
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    except Exception:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    st.session_state.messages.append({"role": "user", "content": user_message})

    context = build_context(st.session_state.data)
    api_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages
    ]

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=context,
        messages=api_messages,
        tools=AI_TOOLS,
    )

    # Tool use loop
    while response.stop_reason == "tool_use":
        assistant_content = []
        tool_results = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                result = handle_tool_call(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        api_messages.append({"role": "assistant", "content": assistant_content})
        api_messages.append({"role": "user", "content": tool_results})

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=context,
            messages=api_messages,
            tools=AI_TOOLS,
        )

    # Extract final text reply
    reply = ""
    for block in response.content:
        if block.type == "text":
            reply += block.text
    reply = reply or "Done \u2014 check the Report panel."

    st.session_state.messages.append({"role": "assistant", "content": reply})
    save_chat_history()
    return reply


TOPIC_LABELS = {
    "deceased": "Deceased",
    "family": "Family",
    "properties": "Properties",
    "finances": "Finances",
    "legal": "Legal",
    "agreements": "Agreements",
    "other": "Other",
}


def build_context(data):
    """Build document context string for the AI."""
    parts = [
        "You are an advisor helping an Italian family with inheritance division.",
        "You have access to the following documents and extracted data.",
        "Answer in the same language the user writes in (Italian or English).",
        "When discussing legal matters, note that this is informational only, not legal advice.",
        "",
        "== YOUR TOOLS ==",
        "",
        "REPORTS: You can create/update/delete report sections on the Report panel using",
        "update_report and delete_report_section. Use these when asked to create reports,",
        "summaries, proposals, or any structured output.",
        "",
        "NOTES: When the user corrects information or provides new facts, ALWAYS use add_note",
        "to save it. Notes override document data and persist across sessions.",
        "",
        "INTERVIEW: When conducting an interview, save each answer using save_interview_entry.",
        "If the user corrects a previous interview answer, use update_interview_entry.",
        "Interview data is the DEFINITIVE source of truth \u2014 it takes highest priority",
        "over documents and notes when generating reports or answering questions.",
        "",
        "When conducting an interview, ask ONE question at a time. Cover these topics:",
        "- Deceased: name, date of death, place of residence, marital status at death",
        "- Family: complete family tree, spouse(s), all children and their families",
        "- Properties: all real estate, locations, estimated values, ownership details",
        "- Finances: bank accounts, investments, pensions, debts, mortgages",
        "- Legal: existing wills, donations, prior agreements, power of attorney",
        "- Agreements: any informal agreements between heirs, preferences, disputes",
        "Review what has already been answered before asking the next question.",
        "Ask follow-up questions when answers are incomplete or raise new topics.",
        "",
    ]

    # Interview data (highest priority)
    if st.session_state.interview:
        parts.append("== INTERVIEW DATA (definitive source of truth) ==")
        topics = {}
        for i, entry in enumerate(st.session_state.interview):
            topics.setdefault(entry["topic"], []).append((i, entry))
        for topic, entries in topics.items():
            label = TOPIC_LABELS.get(topic, topic.title())
            parts.append(f"\n--- {label} ---")
            for i, entry in entries:
                parts.append(f"  [{i}] Q: {entry['question']}")
                parts.append(f"      A: {entry['answer']}")
        parts.append("")

    # Notes (override documents)
    if st.session_state.notes:
        parts.append("== CORRECTIONS & NOTES (override document data) ==")
        for i, n in enumerate(st.session_state.notes):
            parts.append(f"  {i}. {n['note']} (added {n['added_at'][:10]})")
        parts.append("")

    # Document data
    if data["heirs"]:
        parts.append("== HEIRS (Eredi) \u2014 from documents ==")
        for i, h in enumerate(data["heirs"], 1):
            line = f"  {i}. {h.get('name', 'Unknown')}"
            if h.get("date_of_birth"):
                line += f", born {h['date_of_birth']}"
            if h.get("marital_status"):
                line += f", {h['marital_status']}"
            if h.get("num_children") is not None:
                line += f", {h['num_children']} children"
            parts.append(line)
        parts.append("")

    if data["assets"]:
        parts.append("== ASSETS (Immobili / Beni) \u2014 from documents ==")
        for i, a in enumerate(data["assets"], 1):
            parts.append(f"  {i}. {a['description']}")
        parts.append("")

    parts.append("== RAW DOCUMENT TEXT ==")
    for doc in data["documents"]:
        parts.append(f"\n--- Document: {doc['path']} (from folder: {doc['folder']}) ---")
        parts.append(doc["text"])

    # Current report sections
    if st.session_state.reports:
        parts.append("\n== CURRENT REPORT SECTIONS ==")
        for s in st.session_state.reports:
            parts.append(f"\n--- Section: {s['title']} (id: {s['id']}) ---")
            parts.append(s["content"])

    return "\n".join(parts)


# --- Sidebar ---
with st.sidebar:
    st.image("assets/crest.png", use_container_width=True)
    st.title("Inheritance")
    st.caption("Divisione Eredit\u00e0")

    if st.session_state.data:
        n_docs = len(st.session_state.data["documents"])
        scan_time = datetime.fromisoformat(st.session_state.data["scan_date"]).strftime("%H:%M")
        st.caption(f"\u2713 {n_docs} document(s) \u00b7 last sync {scan_time}")
    else:
        st.warning("Dropbox not configured or no documents found.")

    if st.session_state.data:
        st.divider()
        st.subheader("Documents")
        for doc in st.session_state.data["documents"]:
            st.text(f"\U0001f4c4 {doc['filename']}")

    if st.session_state.messages:
        st.divider()
        if st.button("Clear Chat History", use_container_width=True):
            st.session_state.messages = []
            save_chat_history()
            st.rerun()


# --- Custom CSS for layout ---
st.markdown("""
<style>
/* Blue highlighted expandable report items */
div[data-testid="stExpander"] details {
    border: 1px solid #1976D2;
    border-radius: 8px;
    margin-bottom: 0.5rem;
}
div[data-testid="stExpander"] details summary {
    background-color: #E3F2FD;
    color: #1565C0;
    font-weight: 600;
    border-radius: 8px;
    padding: 0.6rem 1rem;
}
div[data-testid="stExpander"] details[open] summary {
    border-radius: 8px 8px 0 0;
}

/* Green interview button */
.interview-btn button {
    background-color: #2E7D32 !important;
    color: white !important;
    border: none !important;
}
.interview-btn button:hover {
    background-color: #1B5E20 !important;
    color: white !important;
}
</style>
""", unsafe_allow_html=True)

# --- Main Layout: Report (2/3) | Chat (1/3) ---
col_report, col_chat = st.columns([2, 1])

# --- Report Column (scrollable independently) ---
with col_report:
    st.header("Report")
    report_scroll = st.container(height=700)

    with report_scroll:
        if st.session_state.data is None:
            st.info("Connecting to Dropbox... If this persists, check your Dropbox configuration.")
        else:
            data = st.session_state.data

            # Heirs
            with st.expander("Heirs (Eredi)", expanded=False):
                if data["heirs"]:
                    heir_rows = []
                    for i, h in enumerate(data["heirs"], 1):
                        heir_rows.append({
                            "#": i,
                            "Name": h.get("name", "Unknown"),
                            "Date of Birth": h.get("date_of_birth", ""),
                            "Marital Status": h.get("marital_status", ""),
                            "Children": h.get("num_children", ""),
                        })
                    st.table(heir_rows)

                    dobs = {}
                    for h in data["heirs"]:
                        dob = h.get("date_of_birth", "")
                        if dob:
                            dobs.setdefault(dob, []).append(h["name"])
                    for dob, names in dobs.items():
                        if len(names) > 1:
                            st.info(f"\U0001f46f {', '.join(names)} share DOB {dob} (twins)")
                else:
                    st.warning("No heirs found yet.")

            # Succession Law
            if data["heirs"]:
                with st.expander("Italian Succession Law (Preliminary)", expanded=False):
                    n = len(data["heirs"])
                    if n == 1:
                        legittima = "1/2"
                        disponibile = "1/2"
                        share_pct = 50.0
                    else:
                        legittima = "2/3"
                        disponibile = "1/3"
                        share_pct = round((2 / 3) / n * 100, 1)

                    c1, c2, c3 = st.columns(3)
                    c1.metric("Legittima (forced share)", legittima)
                    c2.metric("Quota disponibile", disponibile)
                    c3.metric("Per-heir minimum", f"{share_pct}%")

                    st.caption(
                        "If a surviving spouse exists, shares differ. "
                        "Actual shares depend on wills, donations, and full family tree."
                    )

            # Assets
            with st.expander("Assets (Immobili / Beni)", expanded=False):
                if data["assets"]:
                    for i, a in enumerate(data["assets"], 1):
                        st.write(f"{i}. {a['description']}")
                else:
                    st.info("No assets documented yet.")

            # Interview data
            if st.session_state.interview:
                with st.expander(
                    f"Interview Data ({len(st.session_state.interview)} entries)",
                    expanded=False,
                ):
                    topics = {}
                    for i, entry in enumerate(st.session_state.interview):
                        topics.setdefault(entry["topic"], []).append((i, entry))

                    with st.form("interview_edit"):
                        edited_answers = {}
                        for topic, entries in topics.items():
                            label = TOPIC_LABELS.get(topic, topic.title())
                            st.markdown(f"**{label}**")
                            for i, entry in entries:
                                st.caption(entry["question"])
                                edited_answers[i] = st.text_area(
                                    f"answer_{i}",
                                    value=entry["answer"],
                                    key=f"iv_{i}",
                                    label_visibility="collapsed",
                                    height=68,
                                )
                            st.markdown("---")

                        if st.form_submit_button("Save Changes"):
                            changed = False
                            for i, new_answer in edited_answers.items():
                                if new_answer != st.session_state.interview[i]["answer"]:
                                    st.session_state.interview[i]["answer"] = new_answer
                                    st.session_state.interview[i]["answered_at"] = datetime.now().isoformat()
                                    changed = True
                            if changed:
                                save_interview()
                                st.rerun()

            # Notes
            if st.session_state.notes:
                with st.expander(
                    f"Notes & Corrections ({len(st.session_state.notes)} entries)",
                    expanded=False,
                ):
                    for i, n in enumerate(st.session_state.notes):
                        st.write(f"{i + 1}. {n['note']}")
                        st.caption(f"Added {n['added_at'][:10]}")

            # AI-generated report sections
            if st.session_state.reports:
                st.divider()
                st.subheader("AI Reports")
                for section in st.session_state.reports:
                    with st.expander(section["title"], expanded=False):
                        st.markdown(section["content"])
                        st.caption(
                            f"Updated: {datetime.fromisoformat(section['updated_at']).strftime('%Y-%m-%d %H:%M')}"
                        )

# --- Chat Column (scrollable independently) ---
with col_chat:
    st.header("Chat")

    if st.session_state.data is None:
        st.info("Waiting for documents to load from Dropbox...")
    else:
        try:
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        except Exception:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if not api_key:
            st.error("AI chat not configured.")
        else:
            # Green Interview button at top of chat
            interview_label = "Interview"
            if st.session_state.interview:
                interview_label = f"Interview ({len(st.session_state.interview)})"

            st.markdown('<div class="interview-btn">', unsafe_allow_html=True)
            if st.button(interview_label, use_container_width=True):
                if not st.session_state.interview:
                    trigger = (
                        "Please start the interview. Ask me ONE question at a time to gather "
                        "information about the inheritance situation. Start with the basics."
                    )
                else:
                    trigger = (
                        "Please continue the interview. Review what has already been covered "
                        "and ask the next most useful question. Ask ONE question at a time."
                    )
                with st.spinner("Thinking..."):
                    send_to_ai(trigger)
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

            # Scrollable chat history
            chat_container = st.container(height=550)
            with chat_container:
                for msg in st.session_state.messages:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])

            # Chat input
            if prompt := st.chat_input("Ask about the inheritance..."):
                with st.spinner("Thinking..."):
                    send_to_ai(prompt)
                st.rerun()

            # Disclaimer
            st.caption(
                "\u26a0\ufe0f Informational only \u2014 not legal advice."
            )
