import re
import json
import pandas as pd
import streamlit as st
import oracledb

from langchain_community.llms import Ollama

# =============================================================================
# STREAMLIT CONFIG
# =============================================================================

st.set_page_config(
    page_title="Oracle Conversational DBA Assistant",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.title("🛡️ Oracle Conversational DBA Assistant")
st.markdown("Powered by **qwen3-coder:30b** + Ollama · Oracle 19c+")

# =============================================================================
# ORACLE DATABASE CONFIG
# =============================================================================

DB_CONFIG = {
    "user": "system",
    "password": "oracle",
    "dsn": "localhost:1521/XEPDB1",
}

# =============================================================================
# OLLAMA MODEL
# =============================================================================

llm = Ollama(
    model="qwen3-coder:30b",
    temperature=0
)

# =============================================================================
# INTENT ANALYSIS PROMPT
# =============================================================================

INTENT_PROMPT = """
YOU ARE AN ORACLE DBA AI ASSISTANT.

ANALYZE THE USER MESSAGE BELOW.

RETURN ONLY VALID JSON — NO MARKDOWN, NO EXPLANATION, NO EXTRA TEXT.

POSSIBLE STATUS VALUES:

1. "CHAT"      — General conversation, greetings, non-DBA questions
2. "SQL"       — Clear Oracle DBA request, enough info to generate SQL
3. "AMBIGUOUS" — DBA-related but missing key details (time range, schema, object name, limit, etc.)
4. "DANGEROUS" — User requests DML, DDL, DROP, TRUNCATE, GRANT, PL/SQL blocks, or destructive operations

JSON FORMAT:

{
  "status": "SQL",
  "message": "Generating SQL for active sessions",
  "missing_info": []
}

FOR AMBIGUOUS STATUS, populate missing_info with the list of what is unclear.
Each item in missing_info must be a short phrase describing what is missing.

EXAMPLES OF AMBIGUOUS REQUESTS AND THEIR missing_info:
- "show me big tables" → missing_info: ["which schema or all schemas?", "what size threshold in MB?", "how many rows to return?"]
- "find slow queries" → missing_info: ["what time range (last 1h / 24h / week)?", "what defines slow (elapsed time threshold)?", "top N queries?"]
- "check users" → missing_info: ["what about users (locked / expired / active / all)?", "specific schema or all?"]
- "show invalid objects" → missing_info: ["which schema or all?", "which object types (TABLE / INDEX / VIEW / all)?"]
- "tablespace usage" → missing_info: ["specific tablespace name or all?", "show details or summary?"]

FOR SQL STATUS: missing_info must be empty [].
FOR CHAT STATUS: missing_info must be empty [].
FOR DANGEROUS STATUS: missing_info must be empty [].
"""

# =============================================================================
# CLARIFICATION QUESTION PROMPT
# =============================================================================

CLARIFICATION_PROMPT = """
YOU ARE AN ORACLE DBA AI ASSISTANT.

THE USER SENT A DBA REQUEST BUT IT IS MISSING DETAILS.

YOUR JOB IS TO ASK THE USER EXACTLY THE RIGHT QUESTIONS TO GATHER MISSING INFO.

RULES:
- RETURN ONLY VALID JSON — NO MARKDOWN, NO EXTRA TEXT
- GENERATE 1 TO 3 QUESTIONS MAXIMUM
- EACH QUESTION MUST HAVE 2 TO 4 SHORT OPTION LABELS
- QUESTIONS MUST BE SPECIFIC TO THE USER REQUEST
- OPTIONS MUST BE SHORT (1-5 WORDS EACH)
- ALWAYS INCLUDE A "ALL / ANY / NO PREFERENCE" TYPE OPTION WHERE RELEVANT
- NEVER ASK QUESTIONS THAT ARE ALREADY ANSWERED IN THE REQUEST

JSON FORMAT:
{
  "questions": [
    {
      "id": "time_range",
      "question": "What time range do you want to check?",
      "options": ["Last 1 hour", "Last 24 hours", "Last 7 days", "All time"]
    },
    {
      "id": "top_n",
      "question": "How many results do you want?",
      "options": ["Top 5", "Top 10", "Top 20", "All"]
    }
  ]
}

USER ORIGINAL REQUEST:
{user_request}

MISSING INFORMATION IDENTIFIED:
{missing_info}
"""

# =============================================================================
# SQL SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """
YOU ARE AN EXPERT ORACLE DATABASE ADMINISTRATOR AND ORACLE SQL GENERATOR.

GENERATE ONLY VALID ORACLE SQL FOR ORACLE DATABASE 19C+.

STRICT RULES:
1. RETURN ONLY EXECUTABLE ORACLE SQL
2. NEVER EXPLAIN ANYTHING
3. NEVER ADD MARKDOWN
4. NEVER ADD COMMENTS
5. NEVER ADD SEMICOLON
6. NEVER GENERATE PL/SQL
7. NEVER USE LIMIT — USE FETCH FIRST N ROWS ONLY
8. USE ONLY ORACLE SYNTAX
9. USE ONLY REAL ORACLE VIEWS AND COLUMNS
10. NEVER INVENT COLUMNS OR TABLES
11. PREFER SIMPLE SAFE READ-ONLY SQL
12. RETURN ONLY ONE SQL QUERY
13. OUTPUT SQL IN UPPERCASE ONLY
14. NEVER RETURN ANY TEXT BEFORE OR AFTER SQL
15. ALL KEYWORDS, TABLE NAMES, COLUMN NAMES, ALIASES IN UPPERCASE

PREFERRED VIEWS BY TOPIC:
- USERS:         DBA_USERS
- SESSIONS:      V$SESSION
- INVALID OBJECTS: DBA_OBJECTS
- SQL CACHE:     V$SQL
- TABLESPACE:    DBA_DATA_FILES, DBA_FREE_SPACE
- RMAN BACKUP:   V$RMAN_BACKUP_JOB_DETAILS
- LOCKS:         DBA_BLOCKERS, V$LOCK, DBA_WAITERS
- TOP SQL:       V$SQL (ORDER BY ELAPSED_TIME, CPU_TIME, BUFFER_GETS)
- INDEXES:       DBA_INDEXES, DBA_IND_COLUMNS
- CONSTRAINTS:   DBA_CONSTRAINTS
- SEGMENTS/SIZE: DBA_SEGMENTS
- PARAMETERS:    V$PARAMETER
- REDO/ARCHIVE:  V$LOG, V$ARCHIVED_LOG
- WAIT EVENTS:   V$SESSION_WAIT, V$SYSTEM_EVENT

FINAL OUTPUT: RETURN ONLY EXECUTABLE ORACLE SQL IN FULL UPPERCASE.
"""

# =============================================================================
# SESSION STATE
# =============================================================================

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "pending_sql" not in st.session_state:
    st.session_state.pending_sql = None

if "clarification_state" not in st.session_state:
    st.session_state.clarification_state = None
    # Structure: {
    #   "original_request": str,
    #   "questions": [...],
    #   "answers": {},
    #   "current_question_index": int
    # }

# =============================================================================
# ANALYZE INTENT
# =============================================================================

def analyze_intent(user_message: str) -> dict:
    prompt = f"{INTENT_PROMPT}\n\nUSER MESSAGE:\n{user_message}"
    try:
        raw = llm.invoke(prompt)
        raw = re.sub(r"```json|```", "", raw).strip()
        return json.loads(raw)
    except Exception:
        return {"status": "SQL", "message": "Generating SQL", "missing_info": []}

# =============================================================================
# GENERATE CLARIFICATION QUESTIONS
# =============================================================================

def generate_clarification_questions(user_request: str, missing_info: list) -> list:
    prompt = CLARIFICATION_PROMPT.replace("{user_request}", user_request)
    prompt = prompt.replace("{missing_info}", "\n".join(f"- {m}" for m in missing_info))
    try:
        raw = llm.invoke(prompt)
        raw = re.sub(r"```json|```", "", raw).strip()
        data = json.loads(raw)
        return data.get("questions", [])
    except Exception:
        return []

# =============================================================================
# BUILD CONTEXT FROM CLARIFICATION ANSWERS
# =============================================================================

def build_enriched_request(original_request: str, questions: list, answers: dict) -> str:
    context_parts = [f"Original request: {original_request}"]
    for q in questions:
        qid = q["id"]
        if qid in answers:
            context_parts.append(f"{q['question']} → {answers[qid]}")
    return "\n".join(context_parts)

# =============================================================================
# GENERATE SQL
# =============================================================================

def generate_sql(enriched_request: str) -> str:
    history = ""
    for msg in st.session_state.chat_history[-10:]:
        if msg["type"] == "text":
            history += f"{msg['role']}: {msg['content']}\n"

    prompt = f"""
{SYSTEM_PROMPT}

CONVERSATION HISTORY:
{history}

USER REQUEST (WITH CONTEXT):
{enriched_request}

SQL:
"""
    raw = llm.invoke(prompt).strip()
    raw = re.sub(r"```sql|```", "", raw).strip()
    raw = re.sub(r'\bLIMIT\s+(\d+)\b', r'FETCH FIRST \1 ROWS ONLY', raw, flags=re.IGNORECASE)
    return raw.upper()

# =============================================================================
# SQL SAFETY VALIDATOR
# =============================================================================

DANGEROUS_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "MERGE", "GRANT", "REVOKE", "EXECUTE", "BEGIN",
    "DECLARE", "COMMIT", "ROLLBACK", "RENAME", "COMMENT"
]

def validate_sql(sql: str) -> dict:
    upper = sql.upper().strip()
    if not upper.startswith("SELECT"):
        return {"safe": False, "reason": "Only SELECT queries are allowed."}
    for kw in DANGEROUS_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            return {"safe": False, "reason": f"Restricted keyword detected: {kw}"}
    return {"safe": True, "reason": "Safe"}

# =============================================================================
# EXECUTE QUERY
# =============================================================================

def execute_query(sql: str) -> dict:
    try:
        with oracledb.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute(sql.rstrip().rstrip(";"))
                if cur.description is None:
                    return {"success": True, "columns": [], "rows": []}
                columns = [col[0] for col in cur.description]
                rows = cur.fetchmany(100)
                clean_rows = [
                    [str(v) if v is not None else None for v in row]
                    for row in rows
                ]
                return {"success": True, "columns": columns, "rows": clean_rows}
    except Exception as e:
        return {"success": False, "error": str(e)}

# =============================================================================
# RENDER CHAT HISTORY
# =============================================================================

for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        if message["type"] == "text":
            st.markdown(message["content"])
        elif message["type"] == "sql":
            st.code(message["content"], language="sql")
        elif message["type"] == "dataframe":
            df = pd.DataFrame(message["rows"], columns=message["columns"])
            st.dataframe(df, use_container_width=True)

# =============================================================================
# CLARIFICATION FLOW — RENDER CURRENT QUESTION AS BUTTONS
# =============================================================================

if st.session_state.clarification_state:
    cs = st.session_state.clarification_state
    questions = cs["questions"]
    current_idx = cs["current_question_index"]

    if current_idx < len(questions):
        q = questions[current_idx]
        answered_count = len(cs["answers"])
        total = len(questions)

        with st.chat_message("assistant"):
            st.markdown(
                f"**Question {answered_count + 1} of {total}:** {q['question']}"
            )
            cols = st.columns(len(q["options"]))
            for i, option in enumerate(q["options"]):
                if cols[i].button(option, key=f"clarify_{current_idx}_{i}"):
                    cs["answers"][q["id"]] = option
                    cs["current_question_index"] += 1
                    st.rerun()

    else:
        # All questions answered → generate SQL
        enriched = build_enriched_request(
            cs["original_request"],
            cs["questions"],
            cs["answers"]
        )

        answer_summary = " · ".join(
            f"{q['question'].rstrip('?')}: **{cs['answers'].get(q['id'], '—')}**"
            for q in cs["questions"]
            if q["id"] in cs["answers"]
        )

        with st.chat_message("assistant"):
            st.markdown(f"Got it — {answer_summary}")
            with st.spinner("Generating Oracle SQL..."):
                sql = generate_sql(enriched)

            validation = validate_sql(sql)

            st.markdown("#### 📝 Generated Oracle SQL")
            st.code(sql, language="sql")

            if validation["safe"]:
                st.info("Do you want to execute this query? Reply `yes` or `no`")
                st.session_state.pending_sql = sql
            else:
                st.error(f"Execution denied — {validation['reason']}")

        st.session_state.chat_history.append({
            "role": "assistant",
            "type": "sql",
            "content": sql
        })
        st.session_state.clarification_state = None

# =============================================================================
# USER INPUT
# =============================================================================

user_input = st.chat_input("Ask an Oracle DBA question...")

# =============================================================================
# HANDLE USER INPUT
# =============================================================================

if user_input:

    st.session_state.chat_history.append({
        "role": "user", "type": "text", "content": user_input
    })
    with st.chat_message("user"):
        st.markdown(user_input)

    lower = user_input.lower().strip()

    # =========================================================================
    # PENDING EXECUTION CONFIRMATION
    # =========================================================================

    if st.session_state.pending_sql:

        YES_WORDS = {"yes", "execute", "run", "ok", "proceed", "go", "do it", "confirm", "sure", "yep", "yeah"}
        NO_WORDS  = {"no", "cancel", "stop", "nope", "abort", "skip", "don't", "nah"}

        if lower in YES_WORDS or any(w in lower for w in YES_WORDS):
            sql = st.session_state.pending_sql
            validation = validate_sql(sql)
            with st.chat_message("assistant"):
                st.markdown("#### 🚀 Executing query")
                st.code(sql, language="sql")
                if not validation["safe"]:
                    st.error(validation["reason"])
                    st.session_state.chat_history.append({
                        "role": "assistant", "type": "text",
                        "content": f"Execution blocked: {validation['reason']}"
                    })
                else:
                    with st.spinner("Running against Oracle..."):
                        result = execute_query(sql)
                    if result["success"]:
                        if result["rows"]:
                            df = pd.DataFrame(result["rows"], columns=result["columns"])
                            st.success(f"✅ {len(result['rows'])} row(s) returned")
                            st.dataframe(df, use_container_width=True)
                            st.session_state.chat_history.append({
                                "role": "assistant", "type": "dataframe",
                                "columns": result["columns"], "rows": result["rows"]
                            })
                        else:
                            st.info("Query executed. No rows returned.")
                            st.session_state.chat_history.append({
                                "role": "assistant", "type": "text",
                                "content": "Query executed. No rows returned."
                            })
                    else:
                        st.error(result["error"])
                        st.session_state.chat_history.append({
                            "role": "assistant", "type": "text",
                            "content": f"Oracle error: {result['error']}"
                        })
            st.session_state.pending_sql = None

        elif lower in NO_WORDS or any(w in lower for w in NO_WORDS):
            with st.chat_message("assistant"):
                st.info("Query cancelled. Ask me anything else.")
            st.session_state.chat_history.append({
                "role": "assistant", "type": "text",
                "content": "Query execution cancelled."
            })
            st.session_state.pending_sql = None

        else:
            # User said something else while pending — treat as new request
            st.session_state.pending_sql = None
            st.rerun()

    # =========================================================================
    # NORMAL FLOW — INTENT ANALYSIS
    # =========================================================================

    else:

        with st.spinner("Analyzing request..."):
            intent = analyze_intent(user_input)

        status      = intent.get("status", "SQL")
        message     = intent.get("message", "")
        missing_info = intent.get("missing_info", [])

        with st.chat_message("assistant"):

            # -----------------------------------------------------------------
            # CHAT
            # -----------------------------------------------------------------
            if status == "CHAT":
                response = llm.invoke(user_input)
                st.markdown(response)
                st.session_state.chat_history.append({
                    "role": "assistant", "type": "text", "content": response
                })

            # -----------------------------------------------------------------
            # DANGEROUS
            # -----------------------------------------------------------------
            elif status == "DANGEROUS":
                msg = (
                    "⛔ This operation is not allowed.\n\n"
                    "This assistant supports **read-only Oracle SELECT queries** only. "
                    "Operations like INSERT, UPDATE, DELETE, DROP, TRUNCATE, GRANT, "
                    "or PL/SQL blocks are blocked for safety."
                )
                st.error(msg)
                st.session_state.chat_history.append({
                    "role": "assistant", "type": "text", "content": msg
                })

            # -----------------------------------------------------------------
            # AMBIGUOUS — start clarification flow
            # -----------------------------------------------------------------
            elif status == "AMBIGUOUS" and missing_info:
                with st.spinner("Preparing clarification questions..."):
                    questions = generate_clarification_questions(user_input, missing_info)

                if questions:
                    st.markdown("I need a few details before generating the SQL:")
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "type": "text",
                        "content": "I need a few details before generating the SQL:"
                    })
                    st.session_state.clarification_state = {
                        "original_request": user_input,
                        "questions": questions,
                        "answers": {},
                        "current_question_index": 0
                    }
                    st.rerun()
                else:
                    # Fallback: generate without clarification
                    with st.spinner("Generating Oracle SQL..."):
                        sql = generate_sql(user_input)
                    validation = validate_sql(sql)
                    st.markdown("#### 📝 Generated Oracle SQL")
                    st.code(sql, language="sql")
                    if validation["safe"]:
                        st.info("Do you want to execute this query? Reply `yes` or `no`")
                        st.session_state.pending_sql = sql
                    else:
                        st.error(f"Execution denied — {validation['reason']}")
                    st.session_state.chat_history.append({
                        "role": "assistant", "type": "sql", "content": sql
                    })

            # -----------------------------------------------------------------
            # SQL — direct generation
            # -----------------------------------------------------------------
            else:
                with st.spinner("Generating Oracle SQL..."):
                    sql = generate_sql(user_input)
                validation = validate_sql(sql)
                st.markdown("#### 📝 Generated Oracle SQL")
                st.code(sql, language="sql")
                if validation["safe"]:
                    st.info("Do you want to execute this query? Reply `yes` or `no`")
                    st.session_state.pending_sql = sql
                else:
                    st.error(f"Execution denied — {validation['reason']}")
                st.session_state.chat_history.append({
                    "role": "assistant", "type": "sql", "content": sql
                })