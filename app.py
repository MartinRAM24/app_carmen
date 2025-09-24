# app.py — Nube: Postgres (Neon) + Streamlit Cloud
import os
from datetime import date
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Pacientes de Carmen", page_icon="🩺", layout="wide")
st.title("🩺 Pacientes de Carmen")
st.caption("Busca pacientes, registra mediciones por cita y abre la carpeta de fotos en Google Drive.")

# ------------------------------
# Conexión a Postgres (Neon)
# ------------------------------
DB_URL = st.secrets.get("DATABASE_URL", os.getenv("DATABASE_URL", ""))  # debe estar en Secrets
if not DB_URL:
    st.error("No se encontró DATABASE_URL en Secrets. Configúralo en Streamlit Cloud → Settings → Secrets.")
    st.stop()

import psycopg  # requiere psycopg[binary] en requirements.txt

def get_conn():
    # autocommit=True para no preocuparnos por commit manual en inserts/updates
    return psycopg.connect(DB_URL, autocommit=True)

# ------------------------------
# Crear tablas si no existen (Postgres)
# ------------------------------
def ensure_schema():
    con = get_conn()
    with con.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS pacientes (
          id          SERIAL PRIMARY KEY,
          nombre      TEXT UNIQUE NOT NULL,
          edad        INT,
          telefono    TEXT,
          notas       TEXT,
          fotos_URL   TEXT
        );""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS mediciones (
          id                 SERIAL PRIMARY KEY,
          paciente_id        INT NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
          fecha              DATE NOT NULL,
          peso               REAL,
          grasa              REAL,
          musculo            REAL,
          brazo_rest         REAL,
          brazo_flex         REAL,
          pecho_rest         REAL,
          pecho_flex         REAL,
          cintura            REAL,
          cadera             REAL,
          pierna_flex        REAL,
          pantorrilla_flex   REAL,
          notas              TEXT,
          UNIQUE (paciente_id, fecha)
        );""")
    con.close()

ensure_schema()
st.caption("🔌 Base de datos: Postgres (Neon)")

# ------------------------------
# Utilidades de lectura/escritura
# ------------------------------
def query_df(sql: str, params=()):
    con = get_conn()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)
    finally:
        con.close()

def exec_sql(sql: str, params=()):
    con = get_conn()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params)
    finally:
        con.close()
    st.cache_data.clear()

# ------------------------------
# Funciones cacheadas
# ------------------------------
@st.cache_data(ttl=30)
def buscar_pacientes(q: str):
    like = f"%{q.strip()}%" if q else "%"
    # Nota: en Postgres el placeholder es %s (no ?)
    return query_df("""
        SELECT id, nombre, edad, telefono, notas, fotos_URL
        FROM pacientes
        WHERE nombre LIKE %s
        ORDER BY nombre
    """, (like,))

# ------------------------------
# UI: Buscador + Nuevo paciente
# ------------------------------
col1, col2 = st.columns([2, 1])

with col1:
    q = st.text_input("🔎 Buscar por nombre", placeholder="Ej. Ana, Juan…")
    resultados = buscar_pacientes(q)
    if resultados.empty:
        st.info("Sin resultados.")
    else:
        df_show = resultados.copy()
        df_show["Carpeta (Drive)"] = df_show["fotos_URL"]
        st.dataframe(
            df_show[["nombre", "edad", "telefono", "notas", "Carpeta (Drive)"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Carpeta (Drive)": st.column_config.LinkColumn(
                    "Carpeta (Drive)", display_text="Abrir carpeta"
                )
            },
        )

with col2:
    st.subheader("➕ Nuevo paciente")
    with st.form("nuevo_paciente"):
        nombre = st.text_input("Nombre *")
        edad = st.number_input("Edad", 0, 120, value=0, step=1)
        telefono = st.text_input("Teléfono")
        notas_pac = st.text_area("Notas", height=80)
        url = st.text_input("URL carpeta Google Drive")
        ok = st.form_submit_button("Crear/Actualizar")
        if ok and nombre.strip():
            exec_sql("""
              INSERT INTO pacientes(nombre, edad, telefono, notas, fotos_URL)
              VALUES (%s, %s, %s, %s, %s)
              ON CONFLICT (nombre) DO UPDATE SET
                edad = EXCLUDED.edad,
                telefono = EXCLUDED.telefono,
                notas = EXCLUDED.notas,
                fotos_URL = EXCLUDED.fotos_URL
            """, (nombre.strip(), edad if edad > 0 else None, telefono, notas_pac, url))
            st.success("Paciente guardado.")

st.divider()

# ------------------------------
# UI: Registrar medición
# ------------------------------
st.subheader("📝 Registrar medición (cita)")
todos = buscar_pacientes("")  # todos
if todos.empty:
    st.info("Primero crea al menos un paciente.")
else:
    nombre_sel = st.selectbox("Paciente", todos["nombre"].tolist())
    pid = int(todos.loc[todos["nombre"] == nombre_sel, "id"].iloc[0])

    with st.form("add_meas"):
        c1, c2, c3, c4 = st.columns(4)
        fecha = c1.date_input("Fecha", value=date.today(), format="YYYY-MM-DD")
        peso = c2.number_input("Peso (kg)", 0.0, step=0.1, value=0.0)
        grasa = c3.number_input("% Grasa", 0.0, 100.0, step=0.1)
        musculo = c4.number_input("% Músculo", 0.0, 100.0, step=0.1)

        st.markdown("**Medidas (cm):**")
        g1, g2, g3, g4 = st.columns(4)
        brazo_rest = g1.number_input("Brazo (descanso)", 0.0, step=0.1)
        brazo_flex = g2.number_input("Brazo (fuerza)", 0.0, step=0.1)
        pecho_rest = g3.number_input("Pecho (descanso)", 0.0, step=0.1)
        pecho_flex = g4.number_input("Pecho (fuerza)", 0.0, step=0.1)

        h1, h2, h3, h4 = st.columns(4)
        cintura = h1.number_input("Cintura", 0.0, step=0.1)
        cadera = h2.number_input("Cadera", 0.0, step=0.1)
        pierna_flex = h3.number_input("Pierna (fuerza)", 0.0, step=0.1)
        pantorrilla_flex = h4.number_input("Pantorrilla (fuerza)", 0.0, step=0.1)

        notas = st.text_area("Notas de la cita", height=80)

        save = st.form_submit_button("Guardar medición")
        if save:
            exec_sql("""
              INSERT INTO mediciones
              (paciente_id, fecha, peso, grasa, musculo,
               brazo_rest, brazo_flex, pecho_rest, pecho_flex,
               cintura, cadera, pierna_flex, pantorrilla_flex, notas)
              VALUES (%s, %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s, %s)
              ON CONFLICT (paciente_id, fecha) DO UPDATE SET
                peso = EXCLUDED.peso,
                grasa = EXCLUDED.grasa,
                musculo = EXCLUDED.musculo,
                brazo_rest = EXCLUDED.brazo_rest,
                brazo_flex = EXCLUDED.brazo_flex,
                pecho_rest = EXCLUDED.pecho_rest,
                pecho_flex = EXCLUDED.pecho_flex,
                cintura = EXCLUDED.cintura,
                cadera = EXCLUDED.cadera,
                pierna_flex = EXCLUDED.pierna_flex,
                pantorrilla_flex = EXCLUDED.pantorrilla_flex,
                notas = EXCLUDED.notas
            """, (pid, str(fecha), peso, grasa, musculo,
                  brazo_rest, brazo_flex, pecho_rest, pecho_flex,
                  cintura, cadera, pierna_flex, pantorrilla_flex, notas))
            st.success("✅ Medición guardada.")
    st.divider()
    st.subheader("📂 Agregar/Actualizar PDFs de una cita")

    # Reusar la lista de pacientes
    todos_pdf = buscar_pacientes("")  # todos
    if todos_pdf.empty:
        st.info("Primero crea al menos un paciente.")
    else:
        pac_sel = st.selectbox("Paciente", todos_pdf["nombre"].tolist(), key="pdfs_pac")
        pid_pdf = int(todos_pdf.loc[todos_pdf["nombre"] == pac_sel, "id"].iloc[0])

        # Traer citas del paciente (con PDFs actuales)
        citas = query_df("""
                         SELECT fecha, rutina_pdf, plan_pdf
                         FROM mediciones
                         WHERE paciente_id = %s
                         ORDER BY fecha DESC
                         """, (pid_pdf,))

        if citas.empty:
            st.info("Este paciente aún no tiene citas registradas.")
        else:
            fecha_sel = st.selectbox("Fecha de la cita", citas["fecha"].tolist(), key="pdfs_fecha")

            # Valores actuales para no pisar por accidente
            actual = citas.loc[citas["fecha"] == fecha_sel].iloc[0]
            rutina_actual = actual["rutina_pdf"] or ""
            plan_actual = actual["plan_pdf"] or ""

            st.caption("Si dejas un campo vacío, se mantiene el valor actual (no se borra).")
            rutina_url = st.text_input("URL Rutina (PDF)", value=rutina_actual, key="rutina_pdf_input")
            plan_url = st.text_input("URL Plan alimenticio (PDF)", value=plan_actual, key="plan_pdf_input")

            colu1, colu2 = st.columns([1, 1])
            with colu1:
                guardar = st.button("Guardar PDFs")
            with colu2:
                limpiar = st.button("Vaciar ambos PDFs (dejar en blanco)")

            if guardar:
                # Mantener el valor previo si el input quedó vacío
                rutina_final = rutina_url.strip() if rutina_url.strip() else rutina_actual
                plan_final = plan_url.strip() if plan_url.strip() else plan_actual

                exec_sql("""
                         UPDATE mediciones
                         SET rutina_pdf = %s,
                             plan_pdf   = %s
                         WHERE paciente_id = %s
                           AND fecha = %s
                         """, (rutina_final or None, plan_final or None, pid_pdf, fecha_sel))
                st.success("PDFs actualizados ✅")

            if limpiar:
                exec_sql("""
                         UPDATE mediciones
                         SET rutina_pdf = NULL,
                             plan_pdf   = NULL
                         WHERE paciente_id = %s
                           AND fecha = %s
                         """, (pid_pdf, fecha_sel))
                st.success("PDFs vaciados ✅")

    st.subheader("📊 Historial")
    hist = query_df("""
        SELECT fecha, peso, grasa, musculo,
               brazo_rest, brazo_flex, pecho_rest, pecho_flex,
               cintura, cadera, pierna_flex, pantorrilla_flex, notas
        FROM mediciones
        WHERE paciente_id = %s
        ORDER BY fecha DESC
    """, (pid,))
    if hist.empty:
        st.info("Sin mediciones aún.")
    else:
        latest = hist.iloc[0]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Peso (kg)", latest["peso"] if pd.notna(latest["peso"]) else "—")
        k2.metric("% Grasa", latest["grasa"] if pd.notna(latest["grasa"]) else "—")
        k3.metric("% Músculo", latest["musculo"] if pd.notna(latest["musculo"]) else "—")
        k4.metric("Cintura (cm)", latest["cintura"] if pd.notna(latest["cintura"]) else "—")
        st.dataframe(hist, use_container_width=True)
