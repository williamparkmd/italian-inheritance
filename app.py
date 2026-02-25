#!/usr/bin/env python3
"""
Italian Inheritance — Document Reports & AI Chat
Reads documents from shared Dropbox folder, shows structured reports,
and lets family members ask questions via AI.
"""

import os
from datetime import datetime
from pathlib import Path

import anthropic
import streamlit as st
from dotenv import load_dotenv

load_dotenv(".env.local")

from scan import (
    get_dropbox_client,
    scan_dropbox,
    upload_to_dropbox,
    parse_heirs,
    parse_assets,
    HANDLERS,
)

# --- Config ---
st.set_page_config(
    page_title="Italian Inheritance",
    page_icon="🏛️",
    layout="wide",
)

# --- State Init ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "data" not in st.session_state:
    st.session_state.data = None


def load_documents():
    """Scan Dropbox via API and parse data."""
    dbx = get_dropbox_client()
    if not dbx:
        st.error("Dropbox not configured.")
        return None
    documents = scan_dropbox(dbx)
    return {
        "scan_date": datetime.now().isoformat(),
        "documents": documents,
        "heirs": parse_heirs(documents),
        "assets": parse_assets(documents),
    }


def build_context(data):
    """Build document context string for the AI."""
    parts = [
        "You are an advisor helping an Italian family with inheritance division.",
        "You have access to the following documents and extracted data.",
        "Answer in the same language the user writes in (Italian or English).",
        "When discussing legal matters, note that this is informational only, not legal advice.",
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

    return "\n".join(parts)


# --- Sidebar ---
with st.sidebar:
    st.title("Italian Inheritance")
    st.caption("Divisione Eredità")

    # Scan documents from Dropbox
    if st.button("🔄 Load Documents", use_container_width=True):
        with st.spinner("Reading from Dropbox..."):
            st.session_state.data = load_documents()
        if st.session_state.data:
            st.success(f"Found {len(st.session_state.data['documents'])} document(s)")

    # Upload new documents to Dropbox
    st.divider()
    uploaded = st.file_uploader(
        "Upload to Dropbox",
        type=["txt", "pdf", "docx", "doc", "xlsx", "xls", "csv", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )
    if uploaded and st.button("📤 Upload & Scan", use_container_width=True):
        dbx = get_dropbox_client()
        if dbx:
            with st.spinner("Uploading to Dropbox..."):
                for f in uploaded:
                    upload_to_dropbox(dbx, f.getvalue(), f.name)
                    st.write(f"✓ {f.name}")
            with st.spinner("Scanning all documents..."):
                st.session_state.data = load_documents()
            st.success("Uploaded and scanned!")
        else:
            st.error("Dropbox not configured.")

    # Stats
    if st.session_state.data:
        st.divider()
        st.subheader("Documents")
        for doc in st.session_state.data["documents"]:
            st.text(f"📄 {doc['filename']}")

        st.divider()
        st.subheader("Quick Stats")
        n_heirs = len(st.session_state.data["heirs"])
        n_assets = len(st.session_state.data["assets"])
        st.metric("Heirs", n_heirs)
        st.metric("Assets", n_assets)
        if n_heirs > 0:
            total_gc = sum(h.get("num_children", 0) for h in st.session_state.data["heirs"])
            st.metric("Grandchildren", total_gc)

# --- Main ---
tab_report, tab_chat = st.tabs(["📊 Report", "💬 Chat"])

# --- Report Tab ---
with tab_report:
    if st.session_state.data is None:
        st.info("Click **Load Documents** in the sidebar to read documents from Dropbox.")
    else:
        data = st.session_state.data
        st.header("Inheritance Report")
        st.caption(f"Scanned: {datetime.fromisoformat(data['scan_date']).strftime('%Y-%m-%d %H:%M')}")

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

            # Twins detection
            dobs = {}
            for h in data["heirs"]:
                dob = h.get("date_of_birth", "")
                if dob:
                    dobs.setdefault(dob, []).append(h["name"])
            for dob, names in dobs.items():
                if len(names) > 1:
                    st.info(f"👯 {', '.join(names)} share DOB {dob} (twins)")
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

            col1, col2, col3 = st.columns(3)
            col1.metric("Legittima (forced share)", legittima)
            col2.metric("Quota disponibile", disponibile)
            col3.metric("Per-heir minimum", f"{share_pct}%")

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
            st.info("No assets documented yet. Upload property documents to get started.")

# --- Chat Tab ---
with tab_chat:
    if st.session_state.data is None:
        st.info("Click **Load Documents** first, then ask questions here.")
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            st.error("AI chat not configured.")
        else:
            st.caption("Ask questions about the inheritance documents in English or Italian.")

            # Display chat history
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            # Chat input
            if prompt := st.chat_input("Ask about the inheritance..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                context = build_context(st.session_state.data)

                with st.chat_message("assistant"):
                    client = anthropic.Anthropic(api_key=api_key)

                    api_messages = [
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state.messages
                    ]

                    with st.spinner("Thinking..."):
                        response = client.messages.create(
                            model="claude-sonnet-4-20250514",
                            max_tokens=2048,
                            system=context,
                            messages=api_messages,
                        )
                        reply = response.content[0].text

                    st.markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})

            # Disclaimer
            st.divider()
            st.caption(
                "⚠️ This is informational only — not legal advice. "
                "Consult a qualified Italian lawyer for legal decisions."
            )
