# pages/1_Paciente_Dashboard.py
import streamlit as st
from datetime import date, datetime, timedelta
from modules.core import (
    generar_slots, slots_ocupados, agendar_cita_autenticado,
    df_sql, to_drive_preview,
    drive_image_view_url, drive_image_download_url)


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
                        st.caption(r.get("filename") or "")
                        st.link_button("⬇️ Descargar", dl_url, key=f"pac_foto_dl_{pid}_{fid}")


st.divider()
if st.button("Cerrar sesión"):
    st.session_state.role = None
    st.session_state.paciente = None
    st.switch_page("app.py")
