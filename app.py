#!/usr/bin/env python3
"""
Italian Inheritance — Document Reports & AI Chat
Reads documents from shared Dropbox folder, shows structured reports,
and lets family members ask questions via AI.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import streamlit as st
from dotenv import load_dotenv

load_dotenv(".env.local")

from scan import (
    get_dropbox_client,
    get_dropbox_fingerprint,
    scan_dropbox,
    parse_heirs,
    parse_assets,
)

# --- Config ---
st.set_page_config(
    page_title="Inheritance",
    page_icon="🏛️",
    layout="wide",
)

# --- State Init ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "data" not in st.session_state:
    st.session_state.data = None
if "dropbox_fingerprint" not in st.session_state:
    st.session_state.dropbox_fingerprint = None


def load_documents():
    """Scan Dropbox via API and parse data."""
    dbx = get_dropbox_client()
    if not dbx:
        return None
    documents = scan_dropbox(dbx)
    # Update fingerprint so the poller doesn't immediately reload
    st.session_state.dropbox_fingerprint = get_dropbox_fingerprint(dbx)
    return {
        "scan_date": datetime.now().isoformat(),
        "documents": documents,
        "heirs": parse_heirs(documents),
        "assets": parse_assets(documents),
    }


# --- Auto-load on first open ---
if st.session_state.data is None:
    with st.spinner("Loading documents from Dropbox..."):
        st.session_state.data = load_documents()


# --- Poll Dropbox for changes every 30 seconds ---
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
    st.image("assets/crest.png", use_container_width=True)
    st.title("Inheritance")
    st.caption("Divisione Eredità")

    if st.session_state.data:
        n_docs = len(st.session_state.data["documents"])
        scan_time = datetime.fromisoformat(st.session_state.data["scan_date"]).strftime("%H:%M")
        st.caption(f"✓ {n_docs} document(s) · last sync {scan_time}")
    else:
        st.warning("Dropbox not configured or no documents found.")

    # Stats
    if st.session_state.data:
        st.divider()
        st.subheader("Documents")
        for doc in st.session_state.data["documents"]:
            st.text(f"📄 {doc['filename']}")


# --- Main ---
tab_report, tab_chat = st.tabs(["📊 Report", "💬 Chat"])

# --- Report Tab ---
with tab_report:
    if st.session_state.data is None:
        st.info("Connecting to Dropbox... If this persists, check your Dropbox configuration.")
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
        st.info("Waiting for documents to load from Dropbox...")
    else:
        try:
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        except Exception:
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
