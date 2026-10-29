import io
import json
import os
import sqlite3
import zipfile
from datetime import datetime
import streamlit as st
from google import genai
from google.oauth2 import service_account

# --- Page Configuration ---
st.set_page_config(
    page_title="C-SPACE ISO Knowledge Hub [Enterprise Production]",
    page_icon="🏛️",
    layout="wide",
)

DB_FILE = "c_space_iso_enterprise.db"

ISO_DOMAINS = [
    "ISO 30401: Knowledge Management Assets",
    "ISO 9001: Quality Management & Process Controls",
    "Technical Engineering & System Architecture",
    "Human Behavior & Behavioral Health Systems",
    "Empirical Research & Geospatial Data Science",
]


# --- Database Layer with Audit Trail & Confidence Tracking ---
def init_db():
  with sqlite3.connect(DB_FILE) as conn:
    c = conn.cursor()
    c.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_repositories (
                id TEXT PRIMARY KEY,
                domain TEXT,
                digested INTEGER,
                confidence TEXT,
                tags TEXT,
                history TEXT
            )
        """)
    c.execute("""
            CREATE TABLE IF NOT EXISTS repository_revisions (
                rev_id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id TEXT,
                timestamp TEXT,
                version_data TEXT
            )
        """)
    conn.commit()


init_db()


def load_repository_data(repo_id: str):
  with sqlite3.connect(DB_FILE) as conn:
    c = conn.cursor()
    c.execute(
        "SELECT domain, digested, confidence, tags, history FROM"
        " knowledge_repositories WHERE id = ?",
        (repo_id,),
    )
    row = c.fetchone()
  if row:
    return {
        "domain": row[0],
        "digested": bool(row[1]),
        "confidence": row[2] or "N/A",
        "tags": json.loads(row[3]) if row[3] else [],
        "history": json.loads(row[4]),
    }
  return {
      "domain": ISO_DOMAINS[0],
      "digested": False,
      "confidence": "N/A",
      "tags": [],
      "history": [],
  }


def save_repository_data(
    repo_id: str,
    domain: str,
    digested: bool,
    confidence: str,
    tags: list,
    history,
):
  with sqlite3.connect(DB_FILE) as conn:
    c = conn.cursor()
    c.execute(
        "SELECT domain, digested, confidence, tags, history FROM"
        " knowledge_repositories WHERE id = ?",
        (repo_id,),
    )
    old_row = c.fetchone()
    if old_row:
      c.execute(
          """
                INSERT INTO repository_revisions (repo_id, timestamp, version_data)
                VALUES (?, ?, ?)
            """,
          (
              repo_id,
              datetime.now().isoformat(),
              json.dumps({
                  "domain": old_row[0],
                  "digested": old_row[1],
                  "confidence": old_row[2],
                  "tags": old_row[3],
                  "history": old_row[4],
              }),
          ),
      )

    c.execute(
        """
            INSERT OR REPLACE INTO knowledge_repositories (id, domain, digested, confidence, tags, history)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            repo_id,
            domain,
            int(digested),
            confidence,
            json.dumps(tags),
            json.dumps(history),
        ),
    )
    conn.commit()


def get_audit_trail(repo_id: str):
  with sqlite3.connect(DB_FILE) as conn:
    c = conn.cursor()
    c.execute(
        "SELECT timestamp, version_data FROM repository_revisions WHERE"
        " repo_id = ? ORDER BY rev_id DESC",
        (repo_id,),
    )
    return c.fetchall()


def list_repositories():
  with sqlite3.connect(DB_FILE) as conn:
    c = conn.cursor()
    c.execute(
        "SELECT id, domain, digested, confidence, tags, history FROM"
        " knowledge_repositories"
    )
    rows = c.fetchall()

  repo_map = {}
  for row in rows:
    rid, domain, digested, confidence, tags_json, history_json = row
    if domain not in repo_map:
      repo_map[domain] = []
    repo_map[domain].append((
        rid,
        {
            "domain": domain,
            "digested": bool(digested),
            "confidence": confidence or "N/A",
            "tags": json.loads(tags_json) if tags_json else [],
            "history": json.loads(history_json),
        },
    ))
  return repo_map


def get_master_vault_text():
  with sqlite3.connect(DB_FILE) as conn:
    c = conn.cursor()
    c.execute("SELECT history FROM knowledge_repositories WHERE digested = 1")
    rows = c.fetchall()

  vault_text = ""
  for row in rows:
    try:
      history = json.loads(row[0])
      for m in history:
        for p in m.get("parts", []):
          vault_text += p.get("text", "") + "\n"
    except Exception:
      continue
  return vault_text


def delete_repository(repo_id: str):
  with sqlite3.connect(DB_FILE) as conn:
    c = conn.cursor()
    c.execute("DELETE FROM knowledge_repositories WHERE id = ?", (repo_id,))
    c.execute("DELETE FROM repository_revisions WHERE repo_id = ?", (repo_id,))
    conn.commit()


def generate_structured_zip():
  buffer = io.BytesIO()
  with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
    with sqlite3.connect(DB_FILE) as conn:
      c = conn.cursor()
      c.execute(
          "SELECT id, domain, history FROM knowledge_repositories WHERE"
          " digested = 1"
      )
      rows = c.fetchall()

    for repo_id, domain, history_json in rows:
      safe_domain = (
          domain.replace(":", "")
          .replace(" ", "_")
          .replace("&", "and")
          .replace("—", "-")
      )
      try:
        history = json.loads(history_json)
        for m in history:
          for p in m.get("parts", []):
            text = p.get("text", "")
            if text:
              filename = f"{safe_domain}/{repo_id}.md"
              zip_file.writestr(filename, text)
      except Exception:
        continue
  buffer.seek(0)
  return buffer.getvalue()


# --- AI Engine Client Initialization (GCP Vertex AI Service Account Support) ---
if "gemini_client" not in st.session_state:
  try:
    if "gcp_service_account" in st.secrets:
      sa_info = dict(st.secrets["gcp_service_account"])

      # Bulletproof PEM Normalizer & Base64 Padding Auto-Fixer
      if "private_key" in sa_info and isinstance(sa_info["private_key"], str):
        pk = sa_info["private_key"].strip()
        pk = pk.replace("\\n", "\n")
        pk = pk.replace("...", "")
        if "BEGIN PRIVATE KEY" in pk:
          lines = pk.splitlines()
          body_lines = [l.strip() for l in lines if not l.startswith("-----")]
          body = "".join(body_lines)
          missing_padding = len(body) % 4
          if missing_padding:
            body += "=" * (4 - missing_padding)
          wrapped_body = "\n".join(
              body[i : i + 64] for i in range(0, len(body), 64)
          )
          pk = (
              "-----BEGIN PRIVATE KEY-----\n"
              f"{wrapped_body}\n"
              "-----END PRIVATE KEY-----\n"
          )
        sa_info["private_key"] = pk

      project = st.secrets.get(
          "GOOGLE_CLOUD_PROJECT", "gen-lang-client-0874490944"
      )
      location = st.secrets.get("GOOGLE_CLOUD_LOCATION", "us-central1")
      credentials = service_account.Credentials.from_service_account_info(
          sa_info
      )
      st.session_state.gemini_client = genai.Client(
          vertexai=True,
          project=project,
          location
