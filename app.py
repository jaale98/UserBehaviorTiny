from flask import Flask, request, jsonify, g, Response
import sqlite3, json, time, os
from pathlib import Path

DB_PATH = "app.db"

app = Flask(__name__)

# ---------- DB helpers ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ui_elements (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      key TEXT UNIQUE NOT NULL,
      type TEXT NOT NULL CHECK (type IN ('button','text_input')),
      label TEXT NOT NULL
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      event_type TEXT NOT NULL CHECK (event_type IN ('click','text_submit')),
      ui_element_id INTEGER NOT NULL,
      payload TEXT,
      created_at INTEGER NOT NULL,
      FOREIGN KEY (ui_element_id) REFERENCES ui_elements(id)
    )""")
    # seed a few elements if table empty
    cur.execute("SELECT COUNT(*) AS c FROM ui_elements")
    if cur.fetchone()["c"] == 0:
        cur.executemany(
            "INSERT INTO ui_elements (key, type, label) VALUES (?, ?, ?)",
            [
                ("btn_red", "button", "Red Button"),
                ("btn_blue", "button", "Blue Button"),
                ("txt_note", "text_input", "Note"),
                ("txt_idea", "text_input", "Idea"),
            ],
        )
    db.commit()
    db.close()

if not Path(DB_PATH).exists():
    init_db()

# ---------- API ----------
@app.get("/elements")
def list_elements():
    db = get_db()
    rows = db.execute("SELECT id, key, type, label FROM ui_elements ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/events")
def create_event():
    data = request.get_json(silent=True) or {}
    element_key = data.get("element_key")
    event_type = data.get("event_type")
    payload = data.get("payload")

    if event_type not in ("click", "text_submit"):
        return jsonify({"error": "invalid event_type"}), 400
    if not element_key:
        return jsonify({"error": "element_key required"}), 400
    if event_type == "text_submit" and not (payload and str(payload).strip()):
        return jsonify({"error": "payload required for text_submit"}), 400

    db = get_db()
    row = db.execute("SELECT id FROM ui_elements WHERE key = ?", (element_key,)).fetchone()
    if not row:
        return jsonify({"error": "unknown element_key"}), 400

    now = int(time.time())
    db.execute(
        "INSERT INTO events (event_type, ui_element_id, payload, created_at) VALUES (?,?,?,?)",
        (event_type, row["id"], payload, now),
    )
    db.commit()

    evt_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    created = db.execute(
        """SELECT e.id, e.event_type, e.payload, e.created_at,
                  u.key AS element_key, u.label AS element_label, u.type AS element_type
           FROM events e JOIN ui_elements u ON e.ui_element_id = u.id
           WHERE e.id = ?""",
        (evt_id,),
    ).fetchone()
    return jsonify(dict(created)), 201

# ---------- Page (single file, no CORS since same origin) ----------
INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"><title>UserBehavior (tiny)</title>
</head>
<body>
  <h1>UserBehavior — tiny demo</h1>
  <p>Click buttons or press Enter in inputs. Events are saved.</p>
  <div id="elements" style="display:grid;grid-template-columns:repeat(3,minmax(150px,1fr));gap:12px;"></div>
  <pre id="status" style="margin-top:1rem;"></pre>
<script>
async function loadElements(){
  const res = await fetch('/elements');
  const els = await res.json();
  const root = document.getElementById('elements');
  root.innerHTML = '';
  els.forEach(el=>{
    if(el.type==='button'){
      const b = document.createElement('button');
      b.textContent = el.label;
      b.onclick = ()=>sendEvent(el.key,'click');
      root.appendChild(b);
    } else {
      const i = document.createElement('input');
      i.placeholder = el.label;
      i.onkeypress = (e)=>{
        if(e.key==='Enter' && i.value.trim()){
          sendEvent(el.key,'text_submit', i.value.trim());
          i.value='';
        }
      };
      root.appendChild(i);
    }
  });
}
async function sendEvent(element_key, event_type, payload=null){
  const body = {element_key, event_type};
  if(payload!==null) body.payload=payload;
  const res = await fetch('/events',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)
  });
  const txt = await res.text();
  document.getElementById('status').textContent = res.status + " " + txt;
}
loadElements();
</script>
</body>
</html>"""

@app.get("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")

if __name__ == "__main__":
    app.run(debug=True)