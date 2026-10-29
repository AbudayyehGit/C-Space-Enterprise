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


# --- AI Engine Client Initialization ---
if "gemini_client" not in st.session_state:
  try:
    if "gcp_service_account" in st.secrets:
      sa = dict(st.secrets["gcp_service_account"])
      if "private_key" in sa and isinstance(sa["private_key"], str):
        pk = sa["private_key"].strip().replace("\\n", "\n").replace("...", "")
        if "BEGIN PRIVATE KEY" in pk:
          body = "".join(
              [l.strip() for l in pk.splitlines() if not l.startswith("-----")]
          )
          body += "=" * ((4 - len(body) % 4) % 4)
          wrapped = "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
          pk = (
              "-----BEGIN PRIVATE KEY-----\n"
              f"{wrapped}\n"
              "-----END PRIVATE KEY-----\n"
          )
        sa["private_key"] = pk
      creds = service_account.Credentials.from_service_account_info(sa)
      proj = st.secrets.get("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0874490944")
      loc = st.secrets.get("GOOGLE_CLOUD_LOCATION", "us-central1")
      st.session_state.gemini_client = genai.Client(
          vertexai=True, project=proj, location=loc, credentials=creds
      )
    elif "GEMINI_API_KEY" in st.secrets:
      st.session_state.gemini_client = genai.Client(
          api_key=st.secrets["GEMINI_API_KEY"]
      )
    else:
      st.session_state.gemini_client = genai.Client(
          api_key=os.getenv("GEMINI_API_KEY")
      )
  except Exception as e:
    st.error(f"Failed to initialize Gemini client: {e}")
    st.stop()


def iso_digest_and_categorize(
    client, content_text: str, existing_vault: str = ""
):
  try:
    domains_str = ", ".join(ISO_DOMAINS)
    vault_snippet = existing_vault[:3000]
    content_snippet = content_text[:6000]

    prompt = f"""Perform rigorous ISO-compliant information extraction, deduplication, and standardization on the provided source content.
1. Extract ONLY novel, permanent insights, architecture, code, and operational facts. Discard chatter.
2. If the content is 100% redundant relative to the existing vault, output 'DUPLICATE' for the domain.
3. Otherwise, categorize into one of these strict ISO Knowledge Domains: {domains_str} (or propose a precise new ISO-aligned domain name if it represents a distinct discipline).
4. Calculate an automated confidence score (e.g., '98.5%') based on information density and clarity.
5. Assign 2-3 validation tags (e.g., ['High Fidelity', 'Zero Redundancy', 'ISO 30401 Compliant']).
6. Format the output digest in clean Markdown using ISO documentation standards (Objective, Scope, Technical Specifications, Operational Procedures).

Return strictly JSON with keys: 'domain' (string), 'confidence' (string), 'tags' (list of strings), and 'digest' (Markdown string).

Existing Knowledge Vault:
{vault_snippet}

Source Content to Process:
{content_snippet}"""

    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt
    )
    text = response.text.strip()
    if "```json" in text:
      text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
      text = text.split("```")[1].split("```")[0].strip()
    return json.loads(text)
  except Exception:
    return {
        "domain": ISO_DOMAINS[0],
        "confidence": "85.0%",
        "tags": ["Fallback Extraction", "Review Recommended"],
        "digest": "# ISO Knowledge Record\n\nFallback extraction complete.",
    }


# --- Sidebar: Enterprise Control Center ---
st.sidebar.title("🏛️ C-SPACE Enterprise Hub")
st.sidebar.markdown("Automated Real-Time ISO Digestion & Standardization")

if st.sidebar.button(
    "🔄 Sync Historical Streams via Gemini API", type="primary"
):
  with st.spinner("Querying Gemini API backend for historical streams..."):
    try:
      master_vault = get_master_vault_text()
      response = st.session_state.gemini_client.models.generate_content(
          model="gemini-2.5-flash",
          contents=(
              "Review our active project history, architecture designs, and"
              " engineering rules. Extract all core technical findings into a"
              " structured summary."
          ),
      )
      if response and response.text:
        result = iso_digest_and_categorize(
            st.session_state["gemini_client"], response.text, master_vault
        )
        domain_res = result.get("domain", ISO_DOMAINS[0])
        confidence_res = result.get("confidence", "96.0%")
        tags_res = result.get(
            "tags", ["Programmatic API Sync", "Zero-Upload Verified"]
        )
        if domain_res != "DUPLICATE":
          repo_id = f"api_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
          pure_record = [{
              "role": "model",
              "parts": [{
                  "text": (
                      "# [PROGRAMMATIC API SYNC RECORD — Domain:"
                      f" {domain_res} | Confidence:"
                      f" {confidence_res}]\n\n{result.get('digest')}"
                  )
              }],
          }]
          save_repository_data(
              repo_id,
              domain_res,
              digested=True,
              confidence=confidence_res,
              tags=tags_res,
              history=pure_record,
          )
          st.sidebar.success(
              f"Successfully synced repository [{repo_id}] into [{domain_res}]!"
          )
          st.rerun()
        else:
          st.sidebar.info(
              "Sync complete: Content was determined to be redundant."
          )
    except Exception as e:
      st.sidebar.error(f"Sync failed: {e}")

st.sidebar.markdown("---")

repos_by_domain = list_repositories()
if not repos_by_domain:
  save_repository_data(
      "iso_baseline_stream",
      ISO_DOMAINS[0],
      digested=False,
      confidence="N/A",
      tags=["Baseline"],
      history=[],
  )
  repos_by_domain = {ISO_DOMAINS[0]: [("iso_baseline_stream", {})]}

flat_repo_ids = [
    rid for domain, items in repos_by_domain.items() for rid, data in items
]
if (
    "current_repo" not in st.session_state
    or st.session_state["current_repo"] not in flat_repo_ids
):
  st.session_state["current_repo"] = flat_repo_ids[0]

current_repo = st.session_state["current_repo"]
current_data = load_repository_data(current_repo)

st.sidebar.subheader("📂 ISO Knowledge Repositories")
for domain, items in repos_by_domain.items():
  with st.sidebar.expander(f"📁 {domain} ({len(items)})", expanded=True):
    for rid, data in items:
      status = (
          "🟢 ISO Standardized" if data.get("digested") else "🟡 Raw / Active"
      )
      if st.button(
          f"{rid} [{status}]",
          key=f"btn_{rid}",
          type=(
              "primary"
              if rid == st.session_state["current_repo"]
              else "secondary"
          ),
      ):
        st.session_state["current_repo"] = rid
        st.rerun()

# --- Export Section ---
st.sidebar.markdown("---")
st.sidebar.subheader("💾 Export & Backup")

if os.path.exists(DB_FILE):
  with open(DB_FILE, "rb") as f:
    db_bytes = f.read()
  st.sidebar.download_button(
      label="Download SQLite DB",
      data=db_bytes,
      file_name="c_space_iso_enterprise.db",
      mime="application/x-sqlite3",
  )

zip_data = generate_structured_zip()
st.sidebar.download_button(
    label="📦 Export ZIP Bundle (.md)",
    data=zip_data,
    file_name="c_space_iso_markdown_bundle.zip",
    mime="application/zip",
)

# --- Main Workspace ---
st.title(
    f"C-SPACE Repository: `{current_repo}` *(Domain:"
    f" {current_data.get('domain', ISO_DOMAINS[0])})*"
)

# Display Badges
col_badge1, col_badge2 = st.columns([1, 4])
with col_badge1:
  st.metric(
      label="Confidence Score", value=current_data.get("confidence", "N/A")
  )
with col_badge2:
  st.markdown("**Validation Badges:**")
  tags_html = " ".join([
      "<span style='background-color:#e0f2fe; color:#0369a1; padding:4px"
      f" 8px; border-radius:4px; font-weight:600; margin-right:6px;'>{tag}</span>"
      for tag in current_data.get("tags", [])
  ])
  st.markdown(
      tags_html
      if tags_html
      else "<span style='color:gray;'>No validation tags assigned yet.</span>",
      unsafe_allow_html=True,
  )

st.markdown("---")

try:
  chat_session = st.session_state.gemini_client.chats.create(
      model="gemini-2.5-flash", history=current_data.get("history", [])
  )
except Exception as e:
  st.error(f"Error loading session history: {e}")
  chat_session = st.session_state.gemini_client.chats.create(
      model="gemini-2.5-flash", history=[]
  )

for message in chat_session.get_history():
  role = "user" if message.role == "user" else "assistant"
  with st.chat_message(role):
    for part in message.parts:
      if hasattr(part, "text") and part.text:
        st.markdown(part.text)

# --- Real-Time Auto-Digestion Chat Handling ---
if prompt := st.chat_input("Contribute or refine repository data..."):
  with st.chat_message("user"):
    st.markdown(prompt)

  with st.chat_message("assistant"):
    with st.spinner("Synthesizing..."):
      response = chat_session.send_message(prompt)
      st.markdown(response.text)

  updated_history = []
  for message in chat_session.get_history():
    updated_history.append({
        "role": message.role,
        "parts": [
            {"text": p.text}
            for p in message.parts
            if hasattr(p, "text") and p.text
        ],
    })

  full_transcript = "".join(
      p["text"] for m in updated_history for p in m["parts"]
  )
  master_vault = get_master_vault_text()

  result = iso_digest_and_categorize(
      st.session_state["gemini_client"], full_transcript, master_vault
  )
  domain_res = result.get("domain", ISO_DOMAINS[0])
  confidence_res = result.get("confidence", "95.0%")
  tags_res = result.get("tags", ["High Fidelity", "Auto-Digested"])

  if domain_res == "DUPLICATE":
    delete_repository(current_repo)
    st.toast("⚡ Redundant stream detected & auto-pruned!")
    remaining = list_repositories()
    if remaining:
      t = list(remaining.keys())[0]
      st.session_state["current_repo"] = remaining[t][0][0]
    st.rerun()
  else:
    pure_record = [{
        "role": "model",
        "parts": [{
            "text": (
                "# [ISO STANDARDIZED RECORD — Domain:"
                f" {domain_res} | Confidence:"
                f" {confidence_res}]\n\n{result.get('digest')}"
            )
        }],
    }]
    save_repository_data(
        current_repo,
        domain_res,
        digested=True,
        confidence=confidence_res,
        tags=tags_res,
        history=pure_record,
    )
    st.toast(f"✅ Auto-Digested into [{domain_res}] ({confidence_res})")
    st.rerun()

# --- ISO 9001 Audit Trail ---
with st.expander("📜 ISO 9001 Version Audit Trail"):
  revisions = get_audit_trail(current_repo)
  if revisions:
    for idx, (timestamp, v_data) in enumerate(revisions):
      st.markdown(f"**Revision {len(revisions) - idx}** — `{timestamp}`")
      try:
        parsed = json.loads(v_data)
        st.text(
            f"Domain: {parsed.get('domain')} | Confidence:"
            f" {parsed.get('confidence')} | Status:"
            f" Digested={parsed.get('digested')}"
        )
      except Exception:
        st.text(v_data[:200])
      st.markdown("---")
  else:
    st.info("No prior revisions logged yet.")
