import sqlite3
from pathlib import Path

DB = Path("data/patients.db")

con = sqlite3.connect(DB)
cur = con.cursor()

# --- Verificar si existen las columnas ---
cur.execute("PRAGMA table_info(mediciones);")
cols = [c[1] for c in cur.fetchall()]

if "rutina_pdf" not in cols:
    cur.execute("ALTER TABLE mediciones ADD COLUMN rutina_pdf TEXT;")
    print("✅ Columna rutina_pdf agregada")

if "plan_pdf" not in cols:
    cur.execute("ALTER TABLE mediciones ADD COLUMN plan_pdf TEXT;")
    print("✅ Columna plan_pdf agregada")

con.commit()
con.close()
print("🚀 Listo, columnas verificadas/agregadas en mediciones")
