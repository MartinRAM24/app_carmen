import sqlite3
from pathlib import Path
from datetime import date
import pandas as pd
import streamlit as st

DB = Path("data/patients.db")

def conn():
    return sqlite3.connect(DB, check_same_thread=False)

@st.cache_data(ttl=30)
def buscar_pacientes(q: str):
    con = conn()
    like = f"%{q.strip()}%" if q else "%"
    df = pd.read_sql_query("""
        SELECT id, nombre, edad, telefono, notas, fotos_URL
        FROM pacientes
        WHERE nombre LIKE ?
        ORDER BY nombre
    """, con, params=(like,))
    con.close()
    return df

def exec_sql(sql, params=()):
    con = conn()
    cur = con.cursor()
    cur.execute(sql, params)
    con.commit()
    con.close()
    st.cache_data.clear()

def query_df(sql, params=()):
    con = conn()
    df = pd.read_sql_query(sql, con, params=params)
    con.close()
    return df

st.set_page_config(page_title="Pacientes de Carmen", page_icon="🩺", layout="wide")
st.title("🩺 Pacientes de Carmen")
st.caption("Busca pacientes, registra mediciones por cita y abre la carpeta de fotos en Google Drive.")

# --- BUSCADOR + NUEVO PACIENTE ---
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
              VALUES (?, ?, ?, ?, ?)
              ON CONFLICT(nombre) DO UPDATE SET
                edad=excluded.edad,
                telefono=excluded.telefono,
                notas=excluded.notas,
                fotos_URL=excluded.fotos_URL
            """, (nombre.strip(), edad if edad > 0 else None, telefono, notas_pac, url))
            st.success("Paciente guardado.")

st.divider()

# --- REGISTRAR MEDICIÓN ---
st.subheader("📝 Registrar medición (cita)")
todos = buscar_pacientes("")  # todos
if todos.empty:
    st.info("Primero crea al menos un paciente.")
else:
    nombre_sel = st.selectbox("Paciente", todos["nombre"].tolist())
    pid = int(todos[todos["nombre"] == nombre_sel].iloc[0]["id"])

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
              VALUES (?, ?, ?, ?, ?,
                      ?, ?, ?, ?,
                      ?, ?, ?, ?, ?)
              ON CONFLICT(paciente_id, fecha) DO UPDATE SET
                peso=excluded.peso,
                grasa=excluded.grasa,
                musculo=excluded.musculo,
                brazo_rest=excluded.brazo_rest,
                brazo_flex=excluded.brazo_flex,
                pecho_rest=excluded.pecho_rest,
                pecho_flex=excluded.pecho_flex,
                cintura=excluded.cintura,
                cadera=excluded.cadera,
                pierna_flex=excluded.pierna_flex,
                pantorrilla_flex=excluded.pantorrilla_flex,
                notas=excluded.notas
            """, (pid, str(fecha), peso, grasa, musculo,
                  brazo_rest, brazo_flex, pecho_rest, pecho_flex,
                  cintura, cadera, pierna_flex, pantorrilla_flex, notas))
            st.success("✅ Medición guardada.")

    st.subheader("📊 Historial")
    hist = query_df("""
        SELECT fecha, peso, grasa, musculo,
               brazo_rest, brazo_flex, pecho_rest, pecho_flex,
               cintura, cadera, pierna_flex, pantorrilla_flex, notas
        FROM mediciones
        WHERE paciente_id=?
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

