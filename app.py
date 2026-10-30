from datetime import datetime
import io
import json
import os
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
# 2. SIDEBAR CREDENTIALS UPLOADER & INIT
# ==========================================
st.sidebar.header("🔐 Authentication")
cred_file = st.sidebar.file_uploader(
    "Upload GCP Service Account JSON Key", type=["json"]
)


def init_vertex_client(uploaded_file):
  try:
    sa_dict = None

    if uploaded_file is not None:
      bytes_data = uploaded_file.getvalue()
      sa_dict = json.loads(bytes_data.decode("utf-8"))
    elif "GCP_SA_JSON" in st.secrets:
      sa_json_raw = st.secrets["GCP_SA_JSON"]
      sa_dict = (
          sa_json_raw
          if isinstance(sa_json_raw, dict)
          else json.loads(sa_json_raw)
      )

    if not sa_dict:
      return (
          None,
          "Awaiting GCP Service Account JSON key upload in the sidebar...",
      )

    temp_cred_path = "/tmp/gcp_sa_temp.json"
    with open(temp_cred_path, "w") as f:
      json.dump(sa_dict, f)

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_cred_path

    creds = service_account.Credentials.from_service_account_info(sa_dict)
    client = genai.Client(
        vertexai=True,
        project=sa_dict["project_id"],
        location="us-central1",
        credentials=creds,
    )
    return client, f"Connected successfully (Project: {sa_dict['project_id']})"

  except Exception as e:
    return None, f"Authentication Error: {str(e)}"


client, auth_status = init_vertex_client(cred_file)

with st.sidebar:
  st.markdown("---")
  st.header("System Status")
  if client:
    st.success(auth_status)
  else:
    st.warning(auth_status)
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
    ["✍️ Direct Scratchpad", "📊 Knowledge Base", "🛡️ ISO 9001 Audit Trail"]
)

with tab1:
  st.subheader("Direct In-Browser Text Digestion")
  st.caption(
      "Paste your source notes, requirements, or documentation directly below"
      " for instant zero-file ingestion."
  )

  doc_title = st.text_input(
      "Document Title / Identifier", value="ISO-Draft-Note-01"
  )
  scratchpad_content = st.text_area(
      "Paste Content Here", height=200, placeholder="Enter text..."
  )

  if st.button("Analyze & Digest Text", type="primary"):
    if not scratchpad_content.strip():
      st.warning("Please enter some text to analyze.")
    else:
      prompt = (
          "Analyze the following document for ISO 9001 compliance, provide a"
          " concise summary, categorize it, and assign a confidence score"
          " between 0.0 and 1.0. Return strictly in JSON format with keys:"
          " summary, iso_category, confidence_score.\n\nDocument Content:\n"
          f"{scratchpad_content}"
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
                doc_title,
                scratchpad_content,
                parsed.get("summary", ""),
                float(parsed.get("confidence_score", 0.0)),
                parsed.get("iso_category", "General"),
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()

        log_audit("DIGESTION_SUCCESS", f"Processed scratchpad: {doc_title}")
        st.success("Digestion complete!")
        st.json(parsed)

      except Exception as e:
        log_audit("DIGESTION_ERROR", f"Failed scratchpad {doc_title}: {str(e)}")
        st.error(f"Digestion Error: {str(e)}")

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
        st.text_area(
            "Original Content",
            doc_data[1],
            height=150,
            key=f"content_{row[0]}",
        )
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
      st.text(f"[{audit[2]}] {audit[0]}: {audit[1]}")
  else:
    st.info("Audit log is currently empty.")
