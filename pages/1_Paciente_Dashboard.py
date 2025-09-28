# pages/1_Paciente_Dashboard.py
import streamlit as st
from datetime import date, datetime, timedelta
from modules.core import (generar_slots, slots_ocupados, agendar_cita_autenticado,
                          df_sql, to_drive_preview)

st.set_page_config(page_title="Paciente — Dashboard", page_icon="🧑", layout="wide")

# Guardia de sesión
if st.session_state.get("role") != "paciente" or not st.session_state.get("paciente"):
    st.switch_page("app.py")

p = st.session_state.paciente
pid = int(p["id"])

st.title(f"👋 Hola, {p['nombre']}")
st.caption("Elige qué quieres hacer")

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

st.divider()
if st.button("Cerrar sesión"):
    st.session_state.role = None
    st.session_state.paciente = None
    st.switch_page("app.py")
