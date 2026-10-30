base64
from datetime import datetime
import io
import json
import re
import sqlite3
from google import genai
from google.oauth2 import service_account
import streamlit as st

# ==========================================
# 1. PAGE CONFIGURATION & STYLING
# ==========================================
st.set_page_config(
    page_title="C-SPACE GA#8 Knowledge Management System",
    page_icon="🛡️",
    layout="wide",
)

st.title("C-SPACE GA#8 Knowledge Management System")
st.caption(
    "ISO 9001 Compliant Document Digestion & Vertex AI Knowledge Orchestrator"
)

# ==========================================
# 2. BULLETPROOF INDESTRUCTIBLE VERTEX AI INIT
# ==========================================


def init_vertex_client():
  try:
    if "GCP_SA_B64" in st.secrets:
      b64_str = st.secrets["GCP_SA_B64"].strip()

      # Auto-fix Base64 padding
      missing_padding = len(b64_str) % 4
      if missing_padding:
        b64_str += "=" * (4 - missing_padding)

      raw_bytes = base64.b64decode(b64_str)
      raw_text = raw_bytes.decode("utf-8", errors="ignore")

      # Try standard JSON load first; if escape errors occur, use robust regex extraction
      try:
        sa_dict = json.loads(raw_text)
      except Exception:
        sa_dict = {
            "type": "service_account",
            "project_id": re.search(
                r'"project_id"\s*:\s*"([^"]+)"', raw_text
            ).group(1),
            "private_key_id": re.search(
                r'"private_key_id"\s*:\s*"([^"]+)"', raw_text
            ).group(1),
            "private_key": re.search(
                r'"private_key"\s*:\s*"([\s\S]*?)"\s*,\s*"client_email"',
                raw_text,
            )
            .group(1)
            .replace("\\n", "\n")
            .replace("\r\n", "\n")
            .replace("\\\\n", "\n"),
            "client_email": re.search(
                r'"client_email"\s*:\s*"([^"]+)"', raw_text
            ).group(1),
            "token_uri": "https://oauth2.googleapis.com/token",
        }

      # Ensure private key newlines are correct for the crypto library
      if "private_key" in sa_dict:
        pk = sa_dict["private_key"]
        if "-----BEGIN PRIVATE KEY-----" in pk and not "\n" in pk:
          # If it got squashed into a single line, re-insert standard newlines
          pk = pk.replace("-----BEGIN PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----\n") \
                 .replace("-----END PRIVATE KEY-----", "\n-----END PRIVATE KEY-----")
        sa_dict["private_key"] = pk.replace("\\n", "\n").replace("\r\n", "\n")

      creds = service_account.Credentials.from_service_account_info(sa_dict)
      client = genai.Client(
          vertexai=True,
          project=sa_dict["project_id"],
          location="us-central1",
          credentials=creds,
      )
      return client, "Connected via Indestructible Base64 Secrets"
    else:
      return None, "Error: 'GCP_SA_B64' not found in Streamlit secrets."
  except Exception as e:
    return None, f"Authentication Error: {str(e)}"


client, auth_status = init_vertex_client()

with st.sidebar:
  st.header("System Status")
  if client:
    st.success(auth_status)
  else:
    st.error(auth_status)
    st.stop()
  st.markdown("---")
  st.info("Target: GCP Trial Credits ($300 Pool)")


# ==========================================
# 3. DATABASE SETUP (SQLite & ISO 9001 Audit)
# ==========================================
def init_db():
  conn = sqlite3.connect("cspace_iso9001.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            content TEXT,
            summary TEXT,
            confidence_score REAL,
            iso_category TEXT,
            timestamp TEXT
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_trail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            details TEXT,
            timestamp TEXT
        )
    """)
  conn.commit()
  return conn


conn = init_db()
cursor = conn.cursor()


def log_audit(action, details):
  cursor.execute(
      "INSERT INTO audit_trail (action, details, timestamp) VALUES (?, ?, ?)",
      (action, details, datetime.utcnow().isoformat()),
  )
  conn.commit()


# ==========================================
# 4. MAIN APPLICATION INTERFACE
# ==========================================
tab1, tab2, tab3 = st.tabs(
    ["📥 Batch Digestion", "📊 Knowledge Base", "🛡️ ISO 9001 Audit Trail"]
)

with tab1:
  st.subheader("Batch Knowledge Digestion")
  uploaded_files = st.file_uploader(
      "Upload source documents (TXT, MD, JSON)",
      type=["txt", "md", "json"],
      accept_multiple_files=True,
  )

  if st.button("Execute Batch Digestion", type="primary"):
    if not uploaded_files:
      st.warning("Please upload at least one document.")
    else:
      progress_bar = st.progress(0)
      results = []

      for idx, file in enumerate(uploaded_files):
        content = file.read().decode("utf-8")
        prompt = (
            "Analyze the following document for ISO 9001 compliance, provide a"
            " concise summary, categorize it, and assign a confidence score"
            " between 0.0 and 1.0. Return strictly in JSON format with keys:"
            " summary, iso_category, confidence_score.\n\nDocument Content:\n"
            f"{content}"
        )

        try:
          response = client.models.generate_content(
              model="gemini-2.5-flash",
              contents=prompt,
          )

          raw_text = response.text.strip()
          if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()

          parsed = json.loads(raw_text)

          cursor.execute(
              """
                        INSERT INTO documents (filename, content, summary, confidence_score, iso_category, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """,
              (
                  file.name,
                  content,
                  parsed.get("summary", ""),
                  float(parsed.get("confidence_score", 0.0)),
                  parsed.get("iso_category", "General"),
                  datetime.utcnow().isoformat(),
              ),
          )
          conn.commit()

          log_audit("DIGESTION_SUCCESS", f"Processed file: {file.name}")
          results.append(
              {
                  "filename": file.name,
                  "status": "Success",
                  "category": parsed.get("iso_category"),
              }
          )

        except Exception as e:
          log_audit("DIGESTION_ERROR", f"Failed file {file.name}: {str(e)}")
          results.append(
              {"filename": file.name, "
