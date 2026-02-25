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
if "messages" not in st.session_state:
    st.session_state.messages = []
if "data" not in st.session_state:
    st.session_state.data = None
if "dropbox_fingerprint" not in st.session_state:
    st.session_state.dropbox_fingerprint = None
if "reports" not in st.session_state:
    st.session_state.reports = []
if "initialized" not in st.session_state:
    st.session_state.initialized = False


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
    """Load chat history and reports from Dropbox."""
    dbx = get_dropbox_client()
    if not dbx:
        return
    chat_data = load_app_data(dbx, "chat_history.json")
    if chat_data:
        st.session_state.messages = chat_data
    report_data = load_app_data(dbx, "reports.json")
    if report_data:
        st.session_state.reports = report_data


def save_chat_history():
    """Save chat history to Dropbox."""
    dbx = get_dropbox_client()
    if dbx:
        save_app_data(dbx, "chat_history.json", st.session_state.messages)


def save_reports():
    """Save reports to Dropbox."""
    dbx = get_dropbox_client()
    if dbx:
        save_app_data(dbx, "reports.json", st.session_state.reports)


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


# --- Report Tools for AI ---
REPORT_TOOLS = [
    {
        "name": "update_report",
        "description": (
            "Create or update a section of the inheritance report. "
            "Use this when the user asks to create, modify, add to, or correct "
            "any part of the report. Each section has a unique ID — reuse the "
            "same ID to update an existing section."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "Unique identifier (e.g. 'division_proposal', 'property_summary'). Lowercase with underscores.",
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
]


def handle_tool_call(name, params):
    """Execute a report tool call and return a result string."""
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

    return "Unknown tool"


def build_context(data):
    """Build document context string for the AI."""
    parts = [
        "You are an advisor helping an Italian family with inheritance division.",
        "You have access to the following documents and extracted data.",
        "Answer in the same language the user writes in (Italian or English).",
        "When discussing legal matters, note that this is informational only, not legal advice.",
        "",
        "You have tools to create and modify report sections that appear on the Report panel",
        "next to this chat. When the user asks you to create a report, summary, proposal,",
        "or any structured output, use the update_report tool to display it on the Report panel.",
        "You can create multiple sections. To update an existing section, use update_report",
        "with the same section_id. To remove a section, use delete_report_section.",
        "",
    ]

    if data["heirs"]:
        parts.append("== HEIRS (Eredi) ==")
        for i, h in enumerate(data["heirs"], 1):
            line = f"{i}. {h.get('name', 'Unknown')}"
            if h.get("date_of_birth"):
                line += f", born {h['date_of_birth']}"
            if h.get("marital_status"):
                line += f", {h['marital_status']}"
            if h.get("num_children") is not None:
                line += f", {h['num_children']} children"
            parts.append(line)
        parts.append("")

    if data["assets"]:
        parts.append("== ASSETS (Immobili / Beni) ==")
        for i, a in enumerate(data["assets"], 1):
            parts.append(f"{i}. {a['description']}")
        parts.append("")

    parts.append("== RAW DOCUMENT TEXT ==")
    for doc in data["documents"]:
        parts.append(f"\n--- Document: {doc['path']} (from folder: {doc['folder']}) ---")
        parts.append(doc["text"])

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


# --- Main Layout: Side by Side ---
col_report, col_chat = st.columns([1, 1])

# --- Report Column ---
with col_report:
    st.header("Report")

    if st.session_state.data is None:
        st.info("Connecting to Dropbox... If this persists, check your Dropbox configuration.")
    else:
        data = st.session_state.data

        # Heirs
        st.subheader("Heirs (Eredi)")
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
            st.subheader("Italian Succession Law (Preliminary)")
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
        st.subheader("Assets (Immobili / Beni)")
        if data["assets"]:
            for i, a in enumerate(data["assets"], 1):
                st.write(f"{i}. {a['description']}")
        else:
            st.info("No assets documented yet.")

        # AI-generated report sections
        if st.session_state.reports:
            st.divider()
            st.subheader("AI Reports")
            for section in st.session_state.reports:
                st.markdown(f"### {section['title']}")
                st.markdown(section["content"])
                st.caption(
                    f"Updated: {datetime.fromisoformat(section['updated_at']).strftime('%Y-%m-%d %H:%M')}"
                )

# --- Chat Column ---
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
            st.caption("Ask questions or request reports in English or Italian.")

            # Scrollable chat history
            chat_container = st.container(height=500)
            with chat_container:
                for msg in st.session_state.messages:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])

            # Chat input
            if prompt := st.chat_input("Ask about the inheritance..."):
                st.session_state.messages.append({"role": "user", "content": prompt})

                context = build_context(st.session_state.data)
                api_messages = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages
                ]

                client = anthropic.Anthropic(api_key=api_key)

                with st.spinner("Thinking..."):
                    response = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=4096,
                        system=context,
                        messages=api_messages,
                        tools=REPORT_TOOLS,
                    )

                    # Tool use loop
                    while response.stop_reason == "tool_use":
                        assistant_content = []
                        tool_results = []
                        for block in response.content:
                            if block.type == "text":
                                assistant_content.append(
                                    {"type": "text", "text": block.text}
                                )
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
                            tools=REPORT_TOOLS,
                        )

                    # Extract final text reply
                    reply = ""
                    for block in response.content:
                        if block.type == "text":
                            reply += block.text
                    reply = reply or "Done \u2014 check the Report panel."

                st.session_state.messages.append({"role": "assistant", "content": reply})
                save_chat_history()
                st.rerun()

            # Disclaimer
            st.divider()
            st.caption(
                "\u26a0\ufe0f This is informational only \u2014 not legal advice. "
                "Consult a qualified Italian lawyer for legal decisions."
            )
