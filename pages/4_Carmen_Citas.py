# pages/4_Carmen_Citas.py
import streamlit as st
from datetime import date, datetime
import pandas as pd

from modules.core import (
    generar_slots, citas_por_dia, crear_o_encontrar_paciente, exec_sql,
    actualizar_cita, eliminar_cita
)

st.set_page_config(page_title="Carmen — Citas", page_icon="📆", layout="wide")

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
