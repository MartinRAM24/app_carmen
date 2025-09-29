# pages/4_Carmen_Citas.py
import streamlit as st
from datetime import date, datetime
import pandas as pd

from modules.core import (
    generar_slots, citas_por_dia, crear_o_encontrar_paciente, exec_sql,
    actualizar_cita, eliminar_cita
)


st.set_page_config(page_title="Carmen — Citas", page_icon="📆", layout="wide")

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

if st.session_state.get("role") != "admin":
    st.switch_page("app.py")

st.title("🗓️ Gestión de Citas")

colf, colr = st.columns([1, 2], gap="large")

with colf:
    fecha_sel = st.date_input("Día", value=date.today(), key="fecha_admin_citas")
    opts = [t.strftime("%H:%M") for t in generar_slots(fecha_sel)]
    slot = st.selectbox("Hora", opts) if opts else None
    nombre = st.text_input("Nombre paciente", key="citas_nombre")
    tel = st.text_input("Teléfono", key="citas_tel")
    nota = st.text_area("Nota (opcional)", key="citas_nota")

    if st.button("➕ Crear cita", key="citas_crear"):
        if not slot:
            st.error("Selecciona un día con horarios disponibles.")
        elif not (nombre.strip() and tel.strip()):
            st.error("Nombre y teléfono son obligatorios.")
        else:
            try:
                pid = crear_o_encontrar_paciente(nombre, tel)
                exec_sql("INSERT INTO citas(fecha, hora, paciente_id, nota) VALUES (%s,%s,%s,%s)",
                         (fecha_sel, datetime.strptime(slot, "%H:%M").time(), pid, nota or None))
                st.success("Cita creada."); st.rerun()
            except Exception as e:
                st.error(f"No se pudo crear la cita: {e}")

with colr:
    st.subheader(f"Citas para {fecha_sel.strftime('%d-%m-%Y')}")
    if st.button("🔄 Actualizar lista"):
        try: st.cache_data.clear()
        except: pass
        st.rerun()

    df = citas_por_dia(fecha_sel)
    slots_list = generar_slots(fecha_sel)
    if not slots_list:
        st.info("Día no laborable (domingo).")
        if df.empty: st.info("Tampoco hay citas registradas en este día.")
        else: st.dataframe(df, use_container_width=True)
    else:
        todos_slots = pd.DataFrame({"hora": slots_list})
        todos_slots["hora_txt"] = todos_slots["hora"].map(lambda t: t.strftime("%H:%M")).astype(str)
        df_m = df.copy()
        if "hora" not in df_m.columns: df_m["hora"] = pd.NaT
        df_m["hora_txt"] = df_m["hora"].apply(lambda t: t.strftime("%H:%M") if pd.notna(t) else None).astype(str)
        df_show = todos_slots.merge(df_m, on="hora_txt", how="left")
        cols = ["id_cita","paciente_id","nombre","telefono","fecha","hora","nota"]
        for c in cols:
            if c not in df_show.columns: df_show[c] = None
        df_show["estado"] = df_show["id_cita"].apply(lambda x: "✅ libre" if pd.isna(x) else "🟡 ocupado")
        st.dataframe(df_show[["hora_txt","estado"] + cols], use_container_width=True)

    if not df.empty:
        st.divider()
        st.caption("Editar / eliminar cita")
        ids = df["id_cita"].astype(int).tolist()
        cid = st.selectbox("ID cita", ids, key="citas_edit_id")
        r = df[df.id_cita == cid].iloc[0]
        nombre_e = st.text_input("Nombre", r["nombre"] or "", key="citas_edit_nombre")
        tel_e = st.text_input("Teléfono", r["telefono"] or "", key="citas_edit_tel")
        nota_e = st.text_area("Nota", r["nota"] or "", key="citas_edit_nota")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 Guardar cambios", key="citas_edit_save"):
                if nombre_e.strip() and tel_e.strip():
                    try:
                        actualizar_cita(int(cid), nombre_e, tel_e, nota_e or None)
                        st.success("Actualizado."); st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo actualizar: {e}")
                else:
                    st.error("Nombre y teléfono son obligatorios.")
        with c2:
            ok_del = st.checkbox("Confirmar eliminación", key=f"citas_confirm_del_{cid}")
            if st.button("🗑️ Eliminar", disabled=not ok_del, key=f"citas_btn_del_{cid}"):
                try:
                    n = eliminar_cita(int(cid))
                    st.success("Cita eliminada." if n else "La cita ya no existía."); st.rerun()
                except Exception as e:
                    st.error(f"No se pudo eliminar: {e}")

        # --------- RECORDATORIOS WHATSAPP (CITAS DE MAÑANA) ----------
    from modules.core import enviar_recordatorios_manana

    st.divider()
    st.subheader("🔔 Recordatorios de WhatsApp (citas de mañana)")

    colA, colB = st.columns([1, 3])
    with colA:
        dry = st.checkbox("Modo simulación (no envía)", value=True)

    if st.button("📨 Enviar recordatorios de mañana"):
        try:
            res = enviar_recordatorios_manana(dry_run=dry)
            if res["total"] == 0:
                st.info("No hay citas para mañana.")
            else:
                st.success(f"Procesadas: {res['total']} • Enviados: {res['enviados']} • Fallidos: {res['fallidos']}")
                st.dataframe(pd.DataFrame(res["detalles"]), use_container_width=True, hide_index=True)
        except KeyError:
            st.error("Faltan credenciales de WhatsApp en Secrets.")
        except Exception as e:
            st.error(f"No se pudieron enviar los recordatorios: {e}")

st.divider()

# Atajos opcionales a otras páginas (si quieres; o confía en el sidebar)
if st.button("Ir a Gestion Hoy →"):
    st.switch_page("pages/2_Carmen_Hoy.py")
if st.button("Ir a Gestión de Pacientes →"):
    st.switch_page("pages/3_Carmen_Pacientes.py")

# Cerrar sesión (sustituye al antiguo st.page_link)
if st.button("🚪 Cerrar sesión"):
    st.session_state.role = None
    st.session_state.paciente = None
    st.rerun()
