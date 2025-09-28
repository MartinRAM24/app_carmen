# pages/1_Paciente_Dashboard.py
import streamlit as st
from datetime import date, datetime, timedelta
from modules.core import (
    generar_slots, slots_ocupados, agendar_cita_autenticado,
    df_sql, to_drive_preview,
    drive_image_view_url, drive_image_download_url)
import pandas as pd


st.set_page_config(page_title="Paciente — Dashboard", page_icon="🧑", layout="wide")

CUSTOM_CSS = """
/* Sidebar */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #7B1E3C 0%, #800020 100%);
  color: #FFFFFF;
}
[data-testid="stSidebar"] * { color: #FFFFFF !important; }

/* Área principal en blanco */
main.block-container {
  background: #FFFFFF;
  padding-top: 1.2rem;
  padding-bottom: 3rem;
  border-radius: 12px;
}

/* Tarjetas internas (expanders, tabs, forms) */
section[data-testid="stSidebarNav"] { background: transparent; }

/* ===== Expanders: gris medio agradable ===== */
div[data-testid="stExpander"] > details {
  background: #2B2F36 !important;       /* panel cerrado */
  border: 1px solid #3A3F47 !important;
  border-radius: 12px !important;
}
div[data-testid="stExpander"] > details[open] {
  background: #2F343C !important;       /* panel abierto */
}
div[data-testid="stExpander"] summary {
  background: #2B2F36 !important;       /* tira del header */
  color: #EAECEF !important;
  border-radius: 12px !important;
}

/* ===== Inputs en gris (texto/number/textarea/select/date/time/multiselect) ===== */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stDateInput"] input,
[data-testid="stTimeInput"] input,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stMultiSelect"] div[role="combobox"],
/* file uploader caja */
[data-testid="stFileUploader"] section[data-testid="stFileDropzone"] {
  background: #2F3136 !important;
  color: #F5F6F7 !important;
  border: 1px solid #4A4D55 !important;
  border-radius: 10px !important;
}

/* Placeholders más claros */
[data-testid="stTextInput"] input::placeholder,
[data-testid="stNumberInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder,
[data-testid="stDateInput"] input::placeholder,
[data-testid="stTimeInput"] input::placeholder {
  color: #B8B9BE !important;
}

/* Desplegable del select */
div[data-baseweb="popover"] div[role="listbox"] {
  background: #2F3136 !important;
  color: #F5F6F7 !important;
  border: 1px solid #4A4D55 !important;
}



/* Botones primarios */
button[kind="primary"] {
  background: #800020 !important;
  color: #FFFFFF !important;
  border-radius: 10px !important;
  border: 0 !important;
}
button[kind="primary"]:hover { filter: brightness(0.9); }

/* Links */
a, .stLinkButton button { color: #7B1E3C !important; }

/* DataFrames */
.stDataFrame div[data-testid="stTable"] {
  border-radius: 10px;
  overflow: hidden;
}

div[data-baseweb="notification"] {
  background-color: #800020 !important; 
  color: #FFFFFF !important;
}

/* Encabezados */
h1, h2, h3, h4 { color: #111827; }
"""

st.markdown(f"<style>{CUSTOM_CSS}</style>", unsafe_allow_html=True)

# Guardia de sesión
if st.session_state.get("role") != "paciente" or not st.session_state.get("paciente"):
    st.switch_page("app.py")

p = st.session_state.paciente
pid = int(p["id"])

st.title(f"👋 Hola, {p['nombre']}")
st.caption("Elige qué quieres hacer")

# =========================
# 🗓️ Mi próxima cita (NUEVO)
# =========================
prox = df_sql(
    """
    SELECT fecha, hora, nota
    FROM citas
    WHERE paciente_id=%s AND fecha >= CURRENT_DATE
    ORDER BY fecha, hora
    LIMIT 1
    """,
    (pid,),
)

st.subheader("🗓️ Mi próxima cita")
if prox.empty:
    st.info("Aún no tienes una próxima cita agendada.")
else:
    r = prox.iloc[0]
    # fecha puede venir como str/obj; la normalizamos
    f = pd.to_datetime(r["fecha"]).date()
    # hora puede venir como datetime.time o str
    h_raw = r["hora"]
    h_txt = h_raw.strftime("%H:%M") if hasattr(h_raw, "strftime") else str(h_raw)[:5]
    dias = (f - date.today()).days
    txt_dias = "hoy" if dias == 0 else (f"en {dias} días" if dias > 0 else "pasada")

    st.markdown(
        f"""
        **Fecha:** {f.strftime('%d/%m/%Y')}  
        **Hora:** {h_txt}  
        **Estado:** {txt_dias}  
        """.strip()
    )
    if (r.get("nota") or "").strip():
        st.caption(f"Nota: {r['nota']}")

st.divider()

c1, c2 = st.columns(2)

with c1:
    st.subheader("📅 Agendar cita")
    with st.expander("Abrir agendador", expanded=False):
        min_day = date.today() + timedelta(days=2)
        fecha = st.date_input("Día (a partir del tercer día)", value=min_day, min_value=min_day)
        libres = [t for t in generar_slots(fecha) if t not in slots_ocupados(fecha)]
        slot = st.selectbox("Horario", [t.strftime("%H:%M") for t in libres]) if libres else None
        nota = st.text_area("Motivo/nota (opcional)")
        if st.button("Confirmar cita", disabled=(slot is None)):
            try:
                h = datetime.strptime(slot, "%H:%M").time()
                agendar_cita_autenticado(fecha, h, paciente_id=pid, nota=nota or None)
                st.success("¡Cita agendada! ✨")
                st.balloons()
                st.rerun()
            except Exception as e:
                st.error(str(e))

    with st.expander("Ver mis fotos", expanded=False):
        gal = df_sql(
            "SELECT fecha, drive_file_id, filename FROM fotos WHERE paciente_id=%s ORDER BY fecha DESC",
            (pid,),
        )
        if gal.empty:
            st.info("Aún no tienes fotos.")
        else:
            # Agrupa por fecha y muestra en cuadrícula
            fechas = sorted(gal["fecha"].unique(), reverse=True)
            fecha_sel = st.selectbox("Fecha", fechas, key=f"pac_fotos_fecha_{pid}")
            sub = gal[gal["fecha"] == fecha_sel].reset_index(drop=True).to_dict("records")

            def _chunk(lst, n):
                for i in range(0, len(lst), n):
                    yield lst[i : i + n]

            for fila4 in _chunk(sub, 4):
                cols = st.columns(4, gap="medium")
                for i, r in enumerate(fila4):
                    with cols[i]:
                        fid = (r.get("drive_file_id") or "").strip()
                        if not fid:
                            continue
                        img_url = drive_image_view_url(fid)
                        dl_url  = drive_image_download_url(fid)
                        st.markdown(
                            f'<div style="background:#111;border-radius:12px;overflow:hidden;display:flex;justify-content:center;"><img src="{img_url}" style="height:220px;object-fit:contain;"></div>',
                            unsafe_allow_html=True,
                        )
                        st.link_button("⬇️ Descargar", dl_url)

with c2:
    st.subheader("🧾 Mis datos y archivos")
    with st.expander("Ver mis datos", expanded=False):
        d = df_sql("SELECT * FROM pacientes WHERE id=%s", (pid,))
        if not d.empty:
            r = d.iloc[0]
            st.write("**Nombre**:", r.get("nombre","—"))
            st.write("**Teléfono**:", r.get("telefono","—"))
            st.write("**Fecha nac.**:", r.get("fecha_nac") or "—")
            st.write("**Correo**:", r.get("correo") or "—")
            st.write("**Notas**:"); st.write(r.get("notas") or "—")

    with st.expander("Ver mis PDFs", expanded=False):
        citas = df_sql("SELECT fecha, rutina_pdf, plan_pdf FROM mediciones WHERE paciente_id=%s ORDER BY fecha DESC", (pid,))
        if citas.empty: st.info("Aún no tienes PDFs.")
        else:
            fecha_sel = st.selectbox("Fecha", citas["fecha"].tolist())
            row = citas[citas["fecha"] == fecha_sel].iloc[0]
            rpdf, ppdf = (row["rutina_pdf"] or "").strip(), (row["plan_pdf"] or "").strip()
            cL, cR = st.columns(2)
            with cL: st.link_button("Abrir Rutina (PDF)", rpdf, disabled=(not bool(rpdf)))
            with cR: st.link_button("Abrir Plan (PDF)", ppdf, disabled=(not bool(ppdf)))
            with st.expander("Vista previa"):
                if rpdf: st.components.v1.iframe(to_drive_preview(rpdf), height=360)
                if ppdf: st.components.v1.iframe(to_drive_preview(ppdf), height=360)

st.subheader("📏 Mis mediciones")

meds = df_sql("""
    SELECT fecha,
           peso_kg AS "Peso (kg)",
           grasa_pct AS "Grasa",
           musculo_pct AS "Músculo",
           brazo_rest AS "Brazo reposo (cm)",
           brazo_flex AS "Brazo flex (cm)",
           pecho_rest AS "Pecho reposo (cm)",
           pecho_flex AS "Pecho flex (cm)",
           cintura_cm AS "Cintura (cm)",
           cadera_cm AS "Cadera (cm)",
           pierna_cm AS "Pierna (cm)",
           pantorrilla_cm AS "Pantorrilla (cm)",
           notas AS "Notas"
    FROM mediciones
    WHERE paciente_id=%s
    ORDER BY fecha DESC
""", (pid,))

if meds.empty:
    st.info("Aún no tienes mediciones registradas.")
else:
    st.dataframe(meds, use_container_width=True, hide_index=True)

st.divider()
if st.button("🚪 Cerrar sesión"):
    st.session_state.role = None
    st.session_state.paciente = None
    st.rerun()

