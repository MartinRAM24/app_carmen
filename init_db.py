# init_db.py
import sqlite3
from pathlib import Path

DB = Path("data/patients.db")
DB.parent.mkdir(exist_ok=True)

schema = """
CREATE TABLE IF NOT EXISTS pacientes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre TEXT NOT NULL UNIQUE,
  edad INTEGER, telefono TEXT, notas TEXT, fotos_URL TEXT
);
CREATE TABLE IF NOT EXISTS mediciones (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paciente_id INTEGER NOT NULL,
  fecha TEXT NOT NULL,           -- YYYY-MM-DD
  peso REAL, grasa REAL, musculo REAL,
  brazo_rest REAL, brazo_flex REAL, pecho_rest REAL, pecho_flex REAL, cintura REAL, cadera REAL, pierna_flex REAL, 
  pantorrilla_flex REAL, notas TEXT,
  UNIQUE(paciente_id, fecha),
  FOREIGN KEY (paciente_id) REFERENCES pacientes(id) ON DELETE CASCADE
);
"""

con = sqlite3.connect(DB)
cur = con.cursor()
for stmt in schema.strip().split(";"):
    s = stmt.strip()
    if s:
        cur.execute(s)
con.commit()
con.close()
print(f"BD creada en {DB.resolve()}")
