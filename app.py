import base64
from datetime import datetime
import io
import json
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
# 2. BASE64-DECODED VERTEX AI INITIALIZATION
# ==========================================


def init_vertex_client():
  try:
    if "GCP_SA_B64" in st.secrets:
      sa_json_bytes = base64.b64decode(st.secrets["GCP_SA_B64"])
      sa_dict = json.loads(sa_json_bytes.decode("utf-8"))

      creds = service_account.Credentials.from_service_account_info(sa_dict)
      client = genai.Client(
          vertexai=True,
          project=sa_dict["project_id"],
          location="us-central1",
          credentials=creds,
      )
      return client, "Connected via Base64 GCP Secrets (Zero TOML Errors)"
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
              {"filename": file.name, "status": f"Error: {str(e)}"}
          )

        progress_bar.progress((idx + 1) / len(uploaded_files))

      st.success("Batch digestion complete!")
      st.json(results)

with tab2:
  st.subheader("Digested Knowledge Repository")
  cursor.execute(
      "SELECT id, filename, iso_category, confidence_score, timestamp FROM"
      " documents ORDER BY timestamp DESC"
  )
  rows = cursor.fetchall()

  if rows:
    for row in rows:
      with st.expander(f"📁 {row[1]} [{row[2]}] - Confidence: {row[3]}"):
        st.write(f"**Processed Timestamp:** {row[4]}")
        cursor.execute(
            "SELECT summary, content FROM documents WHERE id = ?", (row[0],)
        )
        doc_data = cursor.fetchone()
        st.markdown(f"**Summary:** {doc_data[0]}")
        with st.text_area("Original Content", doc_data[1], height=150, key=f"content_{row[0]}"):
          pass
  else:
    st.info("No documents digested yet.")

with tab3:
  st.subheader("ISO 9001 Compliance Audit Trail")
  cursor.execute(
      "SELECT action, details, timestamp FROM audit_trail ORDER BY timestamp"
      " DESC LIMIT 50"
  )
  audit_rows = cursor.fetchall()
  if audit_rows:
    for audit in audit_rows:
      st.text(f"[{audit[2]}] {audit[0]}: {audit[1]}️")
  else:
    st.info("Audit log is currently empty.")
