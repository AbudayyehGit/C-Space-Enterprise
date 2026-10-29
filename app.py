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


def get_audit_trail(
