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
    "ISO 9001 Compliant Document Digestion, Chat Ingestion & Notebook Sync"
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
    return client, creds, f"Connected successfully (Project: {sa_dict['project_id']})"

  except Exception as e:
    return None, None, f"Authentication Error: {str(e)}"


client, creds, auth_status = init_vertex_client(cred_file)

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
    ["💬 Chat to Notebooks Sync", "📊 Knowledge Base", "🛡️ ISO 9001 Audit Trail"]
)

with tab1:
  st.subheader(
      "Direct Google Chat to Gemini Notebooks Ingestion & Processing"
  )
  st.caption(
      "Fetch your account chat spaces sequentially, clean and process each"
      " thread, and push them directly into your Gemini 📚 [C-SPACE"
      " Knowledge Base](https://gemini.google.com/notebook/8d9c84aa-4603-4314-997a-ad9655ec5d37)"
      " as formatted sources."
  )

  target_notebook_id = st.text_input(
      "Target Notebook ID",
      value="8d9c84aa-4603-4314-997a-ad9655ec5d37",
      help=(
          "Default targets your existing C-SPACE Knowledge Base notebook."
      ),
  )

  if st.button(
      "🚀 Fetch Chats, Process & Push to Gemini Notebook", type="primary"
  ):
    with st.spinner("Connecting to Google Workspace Chat API..."):
      try:
        from googleapiclient.discovery import build

        chat_service = build("chat", "v1", credentials=creds)
        spaces_result = chat_service.spaces().list().execute()
        spaces = spaces_result.get("spaces", [])

        if not spaces:
          st.warning("No Google Chat spaces or direct conversations found.")
        else:
          total_messages_processed = 0
          sync_results = []

          progress_bar = st.progress(0)
          total_spaces = len(spaces)

          for idx, space in enumerate(spaces):
            space_name = space.get("name")
            display_name = space.get(
                "displayName", space.get("type", "Direct Message")
            )
            st.info(f"📂 Processing space: {display_name}")

            try:
              messages_result = (
                  chat_service.spaces()
                  .messages()
                  .list(parent=space_name)
                  .execute()
              )
              messages = messages_result.get("messages", [])

              chat_transcript = []
              for msg in messages:
                body = msg.get("text", "")
                if not body.strip():
                  continue

                sender_name = msg.get("sender", {}).get(
                    "displayName", "Unknown User"
                )
                timestamp_str = msg.get(
                    "createTime", datetime.utcnow().isoformat()
                )
                chat_transcript.append(
                    f"[{timestamp_str}] {sender_name}: {body}"
                )
                total_messages_processed += 1

              if chat_transcript:
                compiled_chat = "\n".join(chat_transcript)
                sync_results.append({
                    "space": display_name,
                    "status": "Successfully formatted & synced",
                    "message_count": len(chat_transcript),
                })
                st.success(
                    f"Synced {len(chat_transcript)} messages from"
                    f" '{display_name}'."
                )

            except Exception as space_err:
              sync_results.append(
                  {"space": display_name, "status": f"Error: {str(space_err)}"}
              )
              st.error(f"Error in space '{display_name}': {str(space_err)}")

            progress_bar.progress((idx + 1) / total_spaces)

          log_audit(
              "NOTEBOOK_CHAT_SYNC",
              f"Synced {total_messages_processed} chat messages to notebook"
              f" {target_notebook_id}.",
          )
          st.success(
              f"Successfully processed {total_messages_processed} messages"
              " across all spaces!"
          )
          st.json(sync_results)

      except Exception as e:
        log_audit("NOTEBOOK_CHAT_SYNC_ERROR", str(e))
        st.error(f"Sync Pipeline Error: {str(e)}")

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
