#!/usr/bin/env python3
"""
Italian Inheritance Document Scanner
Reads documents from Dropbox API (App folder), extracts text,
parses structured data (heirs, assets, valuations), and generates reports.
"""

import io
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import dropbox

# File type handlers — all take a file path and return text
def read_txt(path):
    encodings = ['utf-8', 'latin-1', 'cp1252']
    for enc in encodings:
        try:
            return Path(path).read_text(encoding=enc)
        except (UnicodeDecodeError, Exception):
            continue
    return None

def read_pdf(path):
    try:
        import pdfplumber
        text = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text.append(t)
        return '\n\n'.join(text) if text else None
    except Exception as e:
        return None

def read_docx(path):
    try:
        from docx import Document
        doc = Document(path)
        return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        return None

def read_xlsx(path):
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        text = []
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            text.append(f"--- Sheet: {sheet} ---")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) if c is not None else '' for c in row]
                if any(cells):
                    text.append('\t'.join(cells))
        return '\n'.join(text) if text else None
    except Exception as e:
        return None

def read_csv(path):
    try:
        return Path(path).read_text(encoding='utf-8')
    except Exception:
        try:
            return Path(path).read_text(encoding='latin-1')
        except Exception:
            return None

def read_image(path):
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(path)
        text = pytesseract.image_to_string(img, lang='ita+eng')
        return text if text.strip() else None
    except Exception:
        return None

HANDLERS = {
    '.txt': read_txt,
    '.pdf': read_pdf,
    '.docx': read_docx,
    '.doc': read_docx,
    '.xlsx': read_xlsx,
    '.xls': read_xlsx,
    '.csv': read_csv,
    '.png': read_image,
    '.jpg': read_image,
    '.jpeg': read_image,
    '.tiff': read_image,
    '.tif': read_image,
    '.bmp': read_image,
}


def _get_secret(key):
    """Read a secret from Streamlit secrets or environment variables."""
    try:
        import streamlit as st
        return st.secrets.get(key, "") or os.environ.get(key, "")
    except Exception:
        return os.environ.get(key, "")


def get_dropbox_client():
    """Create Dropbox client using refresh token (preferred) or legacy access token."""
    refresh_token = _get_secret("DROPBOX_REFRESH_TOKEN")
    app_key = _get_secret("DROPBOX_APP_KEY")
    app_secret = _get_secret("DROPBOX_APP_SECRET")

    if refresh_token and app_key and app_secret:
        return dropbox.Dropbox(
            oauth2_refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret,
        )

    # Fallback to legacy short-lived token
    token = _get_secret("DROPBOX_TOKEN")
    if token:
        return dropbox.Dropbox(token)

    return None


def scan_dropbox(dbx, folder_path=""):
    """Recursively scan Dropbox folder and extract text from all supported documents."""
    documents = []

    try:
        result = dbx.files_list_folder(folder_path, recursive=True)
    except Exception as e:
        print(f"Error listing Dropbox folder: {e}")
        return documents

    entries = list(result.entries)
    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)

    files = [e for e in entries if isinstance(e, dropbox.files.FileMetadata)]
    supported = [f for f in files if Path(f.name).suffix.lower() in HANDLERS]

    if not supported:
        return documents

    for entry in supported:
        ext = Path(entry.name).suffix.lower()
        handler = HANDLERS.get(ext)
        rel_path = entry.path_display.lstrip('/')
        folder = str(Path(rel_path).parent) if str(Path(rel_path).parent) != '.' else 'root'

        # Download to temp file
        try:
            _, response = dbx.files_download(entry.path_lower)
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(response.content)
                tmp_path = tmp.name

            text = handler(tmp_path)
            os.unlink(tmp_path)

            if text and text.strip():
                documents.append({
                    'path': rel_path,
                    'folder': folder,
                    'filename': entry.name,
                    'type': ext,
                    'text': text.strip(),
                    'scanned_at': datetime.now().isoformat(),
                    'size_bytes': entry.size,
                })
        except Exception as e:
            print(f"  Error processing {entry.name}: {e}")

    return documents


def upload_to_dropbox(dbx, file_bytes, filename, folder_path=""):
    """Upload a file to Dropbox App folder."""
    path = f"{folder_path}/{filename}" if folder_path else f"/{filename}"
    dbx.files_upload(file_bytes, path, mode=dropbox.files.WriteMode.overwrite)


def get_dropbox_fingerprint(dbx, folder_path=""):
    """Return a string fingerprint of the Dropbox folder state.

    Built from sorted file paths, sizes, and content hashes so any
    add/remove/modify of a file produces a different fingerprint.
    """
    try:
        result = dbx.files_list_folder(folder_path, recursive=True)
        entries = list(result.entries)
        while result.has_more:
            result = dbx.files_list_folder_continue(result.cursor)
            entries.extend(result.entries)

        files = [e for e in entries if isinstance(e, dropbox.files.FileMetadata)]
        parts = sorted(f"{f.path_lower}:{f.size}:{f.content_hash}" for f in files)
        return "|".join(parts)
    except Exception:
        return None


def parse_heirs(documents):
    """Parse heir information from document text."""
    heirs = []
    for doc in documents:
        text = doc['text']
        lines = text.split('\n')
        in_heirs = False
        for line in lines:
            line = line.strip()
            if 'eredi' in line.lower() or 'heirs' in line.lower():
                in_heirs = True
                continue
            if in_heirs and line and line[0].isdigit():
                heir = parse_heir_line(line)
                if heir:
                    heir['source_file'] = doc['path']
                    heirs.append(heir)
            elif in_heirs and ('immobili' in line.lower() or 'beni' in line.lower() or line == ''):
                if line and 'immobili' in line.lower():
                    in_heirs = False
    return heirs


def parse_heir_line(line):
    """Parse a single heir line."""
    line = re.sub(r'^\d+[\.\)\s]+', '', line).strip()
    if not line:
        return None

    heir = {}

    name_match = re.match(r'([A-Za-zÀ-ÿ]+)', line)
    if name_match:
        heir['name'] = name_match.group(1)

    dob_match = re.search(r'\((\d{2}/\d{2}/\d{4})\)', line)
    if dob_match:
        heir['date_of_birth'] = dob_match.group(1)

    if 'coniugat' in line.lower():
        heir['marital_status'] = 'married'
        heir['marital_status_it'] = 'coniugato/a'
    elif 'stato libero' in line.lower() or 'libero' in line.lower():
        heir['marital_status'] = 'unmarried'
        heir['marital_status_it'] = 'stato libero'
    elif 'vedov' in line.lower():
        heir['marital_status'] = 'widowed'
        heir['marital_status_it'] = 'vedovo/a'

    children_match = re.search(r'(\d+)\s+figli[oa]?e?', line)
    if children_match:
        heir['num_children'] = int(children_match.group(1))

    heir['raw_text'] = line.rstrip(';').strip()

    return heir if heir.get('name') else None


def parse_assets(documents):
    """Parse asset/property information from document text."""
    assets = []
    for doc in documents:
        text = doc['text']
        lines = text.split('\n')
        in_assets = False
        for line in lines:
            line = line.strip()
            if any(kw in line.lower() for kw in ['immobili', 'beni', 'properties', 'assets']):
                in_assets = True
                continue
            if in_assets and line:
                assets.append({
                    'description': line.rstrip(';').strip(),
                    'source_file': doc['path'],
                    'raw_text': line,
                })
    return assets
