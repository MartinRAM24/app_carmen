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
                         WHERE paciente_id = ?
                         ORDER BY fecha DESC
                         """, (pid_pdf,))

        if citas.empty:
            st.info("Este paciente aún no tiene citas registradas.")
        else:
            fecha_sel = st.selectbox("Fecha de la cita", citas["fecha"].tolist(), key="pdfs_fecha")
            fecha_key = str(fecha_sel)  # para usar en keys de widgets


            # --- Utilidades para mostrar enlaces bonitos ---
            def to_drive_preview(url: str) -> str:
                if not url:
                    return ""
                url = url.strip()
                if "drive.google.com" in url:
                    url = url.split("?")[0]
                    if "/view" in url:
                        url = url.replace("/view", "/preview")
                    elif "/preview" not in url:
                        url = url[:-1] + "preview" if url.endswith("/") else url + "/preview"
                return url


            def show_link(label: str, url: str):
                if not url:
                    st.write(f"• {label}: _vacío_")
                    return
                cols = st.columns([0.35, 0.65])
                with cols[0]:
                    st.link_button(f"🔗 {label}", url)
                with cols[1]:
                    # key único por fecha para evitar colisiones al cambiar de cita
                    st.text_input(f"URL {label}", url, key=f"show_{label}_{fecha_key}", disabled=True)


            # Valores actuales
            actual = citas.loc[citas["fecha"] == fecha_sel].iloc[0]
            rutina_actual = (actual["rutina_pdf"] or "").strip()
            plan_actual = (actual["plan_pdf"] or "").strip()

            # Inputs editables (keys por fecha)
            st.caption("Si dejas un campo vacío, se mantiene el valor actual (no se borra).")
            rutina_url = st.text_input("URL Rutina (PDF)", value=rutina_actual, key=f"rutina_pdf_input_{fecha_key}")
            plan_url = st.text_input("URL Plan alimenticio (PDF)", value=plan_actual, key=f"plan_pdf_input_{fecha_key}")

            colu1, colu2 = st.columns([1, 1])
            with colu1:
                guardar = st.button("Guardar PDFs")
            with colu2:
                limpiar = st.button("Vaciar ambos PDFs (dejar en blanco)")

            # --- Mostrar enlaces guardados (clicables) ---
            st.markdown("### 📎 Enlaces guardados")
            show_link("Rutina (PDF)", rutina_actual)
            show_link("Plan alimenticio (PDF)", plan_actual)

            # --- (Opcional) Preview embebido si es Drive ---
            with st.expander("👁️ Vista previa rápida (Google Drive)"):
                if rutina_actual:
                    st.markdown("**Rutina**")
                    st.components.v1.iframe(to_drive_preview(rutina_actual), height=360)
                if plan_actual:
                    st.markdown("**Plan alimenticio**")
                    st.components.v1.iframe(to_drive_preview(plan_actual), height=360)

            # --- Acciones ---
            if guardar:
                rutina_final = rutina_url.strip() if rutina_url.strip() else rutina_actual
                plan_final = plan_url.strip() if plan_url.strip() else plan_actual

                exec_sql("""
                         UPDATE mediciones
                         SET rutina_pdf = ?,
                             plan_pdf   = ?
                         WHERE paciente_id = ?
                           AND fecha = ?
                         """, (rutina_final or None, plan_final or None, pid_pdf, fecha_sel))

                st.success("PDFs actualizados ✅")
                st.rerun()  # refresca valores sin tocar session_state de los widgets

            if limpiar:
                exec_sql("""
                         UPDATE mediciones
                         SET rutina_pdf = NULL,
                             plan_pdf   = NULL
                         WHERE paciente_id = ?
                           AND fecha = ?
                         """, (pid_pdf, fecha_sel))
                st.success("PDFs vaciados ✅")
                st.rerun()

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
