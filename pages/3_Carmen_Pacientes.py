# pages/3_Carmen_Pacientes.py
import streamlit as st
from datetime import date
from pathlib import Path                      # <- lo necesitas más abajo para PDFs
from modules.core import (
    df_sql, exec_sql, upsert_medicion, asociar_medicion_a_cita,
    upload_pdf_to_folder, upload_image_to_folder, enforce_patient_pdf_quota,
    get_drive, ensure_cita_folder, drive_image_view_url, drive_image_download_url,
    delete_foto, delete_medicion_dia,             # <- IMPORTANTE
)
import pandas as pd
import re
from modules.core import registrar_paciente_admin
import random

st.set_page_config(page_title="Carmen — Pacientes", page_icon="🧾", layout="wide")
from modules.theme import apply_theme

apply_theme()

if st.session_state.get("role") != "admin":
    st.switch_page("app.py")

st.title("📚 Gestión de Pacientes")

# ===== Alta rápida de paciente (modal) =====
colL, colR = st.columns([1, 5])
with colL:
    if st.button("➕ Nuevo paciente", use_container_width=True):
        @st.dialog("Registrar nuevo paciente")
        def _dlg_nuevo_paciente():
            with st.form("form_nuevo_paciente", clear_on_submit=False):
                nombre_np = st.text_input("Nombre completo *")
                tel_np    = st.text_input("Teléfono *", help="10 dígitos MX o como lo uses normalmente")
                fecha_np  = st.text_input("Fecha de nacimiento (YYYY-MM-DD) — opcional", placeholder="1995-06-25")
                correo_np = st.text_input("Correo — opcional")
                c1, c2 = st.columns([2,1])
                with c1:
                    pw_np = st.text_input("Contraseña (6 dígitos) *", type="password", max_chars=6,
                                          help="Se la puedes compartir al paciente; luego podrá cambiarla.")
                with c2:
                    def _gen_pwd():
                        return f"{random.randint(0, 999999):06d}"
                    if st.form_submit_button("🎲 Generar"):
                        st.session_state["_tmp_pw_np"] = _gen_pwd()
                # si generamos, rellenamos el campo
                if "_tmp_pw_np" in st.session_state and not pw_np:
                    pw_np = st.session_state["_tmp_pw_np"]

                crear = st.form_submit_button("Crear paciente")

            if crear:
                if not (nombre_np.strip() and tel_np.strip() and pw_np):
                    st.error("Completa nombre, teléfono y contraseña (6 dígitos)."); return
                if not re.fullmatch(r"\d{6}", pw_np):
                    st.error("La contraseña debe tener exactamente 6 dígitos."); return
                # Validación ligera de fecha/correo (opcionales)
                if fecha_np and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha_np):
                    st.error("La fecha debe tener formato YYYY-MM-DD (o déjala en blanco)."); return
                if correo_np and "@" not in correo_np:
                    st.error("El correo no parece válido (o déjalo en blanco)."); return

                try:
                    pid_new = registrar_paciente_admin(
                        nombre=nombre_np,
                        telefono=tel_np,
                        password_6d=pw_np,
                        fecha_nac=(fecha_np or None),
                        correo=(correo_np or None),
                    )
                    # limpiar auxiliar
                    st.session_state.pop("_tmp_pw_np", None)
                    st.success(f"Paciente creado (ID {pid_new}) ✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo crear: {e}")

        _dlg_nuevo_paciente()



# Buscar paciente
with st.form("buscar_paciente"):
    q = st.text_input("Buscar por nombre")
    ok = st.form_submit_button("Buscar")
if ok:
    st.session_state["bus_pac_df"] = df_sql(
        "SELECT id, nombre FROM pacientes WHERE nombre ILIKE %s ORDER BY nombre", (f"%{q.strip()}%",)
    )

lista = st.session_state.get("bus_pac_df")

# ✅ Evita evaluar un DataFrame como booleano
if (
    lista is None
    or (isinstance(lista, pd.DataFrame) and lista.empty)
):
    st.caption("Escribe y busca para ver resultados.")
    st.stop()


pac_sel = st.selectbox("Selecciona paciente", lista["nombre"].tolist())
pid = int(lista.loc[lista["nombre"] == pac_sel, "id"].iloc[0])

tab_info, tab_medidas, tab_pdfs, tab_fotos = st.tabs(["🧾 Perfil", "📏 Mediciones", "📂 PDFs", "🖼️ Fotos"])

# ---- PERFIL ----
with tab_info:
    datos = df_sql("SELECT * FROM pacientes WHERE id=%s", (pid,))
    if datos.empty:
        st.info("Paciente no encontrado.")
    else:
        row = datos.iloc[0]
        with st.form("form_edit_paciente"):
            nombre = st.text_input("Nombre", row["nombre"] or "")
            fnac = st.text_input("Fecha de nacimiento (YYYY-MM-DD)", row["fecha_nac"] or "")
            tel = st.text_input("Teléfono", row["telefono"] or "")
            mail = st.text_input("Correo", row["correo"] or "")
            notas = st.text_area("Notas", row["notas"] or "")
            guardar = st.form_submit_button("Guardar cambios")
        if guardar:
            exec_sql("""
                UPDATE pacientes
                SET nombre=%s, fecha_nac=%s, telefono=%s, correo=%s, notas=%s
                WHERE id=%s
            """, (nombre.strip(), fnac.strip() or None, tel.strip() or None, mail.strip() or None, notas.strip() or None, pid))
            st.success("Perfil actualizado ✅"); st.rerun()

# ---- MEDICIONES ----
with tab_medidas:
    with st.expander("➕ Nueva medición / Guardar por fecha", expanded=True):
        with st.form(f"form_medicion_{pid}"):
            f = st.text_input("Fecha (YYYY-MM-DD)", value=str(date.today()), key=f"med_fecha_{pid}")
            c1, c2, c3 = st.columns(3)
            with c1:
                peso_kg = st.number_input("Peso (kg)", min_value=0.0, step=0.1, value=0.0)
                grasa = st.number_input("% Grasa", min_value=0.0, step=0.1, value=0.0)
                musc = st.number_input("% Músculo", min_value=0.0, step=0.1, value=0.0)
            with c2:
                brazo_r = st.number_input("Brazo (reposo)", min_value=0.0, step=0.1, value=0.0)
                brazo_f = st.number_input("Brazo (flex)", min_value=0.0, step=0.1, value=0.0)
                pecho_r = st.number_input("Pecho (reposo)", min_value=0.0, step=0.1, value=0.0)
            with c3:
                pecho_f = st.number_input("Pecho (flex)", min_value=0.0, step=0.1, value=0.0)
                cintura = st.number_input("Cintura (cm)", min_value=0.0, step=0.1, value=0.0)
                cadera = st.number_input("Cadera (cm)", min_value=0.0, step=0.1, value=0.0)
            pierna = st.number_input("Pierna (cm)", min_value=0.0, step=0.1, value=0.0)
            pantorrilla = st.number_input("Pantorrilla (cm)", min_value=0.0, step=0.1, value=0.0)
            notas_med = st.text_area("Notas", "")
            guardar_med = st.form_submit_button("Guardar/Actualizar medición")
        if guardar_med:
            def nz(x): return None if x in (0, 0.0) else x
            exec_sql("INSERT INTO mediciones (paciente_id, fecha) VALUES (%s,%s) ON CONFLICT DO NOTHING", (pid, f.strip()))
            exec_sql("""
                UPDATE mediciones
                SET peso_kg=%s, grasa_pct=%s, musculo_pct=%s, brazo_rest=%s, brazo_flex=%s,
                    pecho_rest=%s, pecho_flex=%s, cintura_cm=%s, cadera_cm=%s, pierna_cm=%s,
                    pantorrilla_cm=%s, notas=%s
                WHERE paciente_id=%s AND fecha=%s
            """, (nz(peso_kg), nz(grasa), nz(musc), nz(brazo_r), nz(brazo_f), nz(pecho_r), nz(pecho_f),
                  nz(cintura), nz(cadera), nz(pierna), nz(pantorrilla), (notas_med.strip() or None), pid, f.strip()))
            try: asociar_medicion_a_cita(pid, f.strip())
            except Exception: pass
            st.success("Medición guardada ✅"); st.rerun()

    hist = df_sql("""
        SELECT fecha,
               peso_kg AS peso_KG, grasa_pct AS grasa, musculo_pct AS musculo,
               brazo_rest AS brazo_rest_CM, brazo_flex AS brazo_flex_CM,
               pecho_rest AS pecho_rest_CM, pecho_flex AS pecho_flex_CM,
               cintura_cm AS cintura_CM, cadera_cm AS cadera_CM,
               pierna_cm AS pierna_CM, pantorrilla_cm AS pantorrilla_CM,
               notas
        FROM mediciones WHERE paciente_id=%s
        ORDER BY fecha DESC
    """, (pid,))
    if hist.empty: st.info("Sin mediciones aún.")
    else: st.dataframe(hist, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 🗑️ Eliminar medición de un día")
    fechas_disp = df_sql("SELECT fecha FROM mediciones WHERE paciente_id=%s ORDER BY fecha DESC", (pid,))
    if fechas_disp.empty:
        st.caption("No hay días con mediciones.")
    else:
        fecha_del = st.selectbox("Fecha a eliminar", fechas_disp["fecha"].tolist())
        col_opts = st.columns(3)
        with col_opts[0]:
            opt_rm_drive = st.checkbox("Eliminar carpeta de Drive de esa fecha", value=True)
        with col_opts[1]:
            opt_trash = st.checkbox("Enviar a Papelera (recomendado)", value=True)
        with col_opts[2]:
            opt_del_cita = st.checkbox("Eliminar cita del día", value=False)
        confirm = st.checkbox("Confirmo que deseo eliminar esa medición")
        if st.button("🗑️ Eliminar medición del día", disabled=not confirm):
            delete_medicion_dia(pid, str(fecha_del), remove_drive_folder=opt_rm_drive,
                                send_to_trash=opt_trash, delete_cita_row=opt_del_cita)
            st.success(f"Medición del {fecha_del} eliminada ✅"); st.rerun()

# ---- PDFs ----
with tab_pdfs:
    st.caption("Sube y consulta los PDFs de cada fecha (YYYY-MM-DD).")
    fecha_pdf = st.text_input("Fecha", value=str(date.today()), key=f"pdf_fecha_{pid}")
    c1, c2 = st.columns(2)
    with c1:
        up_rutina = st.file_uploader("Rutina (PDF)", type=["pdf"])
        if up_rutina and st.button("⬆️ Subir Rutina"):
            try:
                cita_folder = ensure_cita_folder(pid, fecha_pdf.strip())
                drive = get_drive()
                ext = Path(up_rutina.name).suffix or ".pdf"
                target = _safe = f"{fecha_pdf.strip()}_rutina{ext}"
                # _ensure_unique_name está dentro del core; lo “simulamos” llamando por Drive directamente:
                # pero más fácil: usamos nombre tal cual; si choca, Drive crea -2, etc.
                pdf = upload_pdf_to_folder(up_rutina.read(), target, cita_folder)
                upsert_medicion(pid, fecha_pdf.strip(), rutina_pdf=pdf["webViewLink"], plan_pdf=None)
                # limitar a 10 PDFs
                pf = df_sql("SELECT drive_folder_id FROM pacientes WHERE id=%s",(pid,))
                if not pf.empty and (pf.loc[0,"drive_folder_id"] or "").strip():
                    enforce_patient_pdf_quota(pf.loc[0,"drive_folder_id"].strip(), keep=10, send_to_trash=True)
                st.success("Rutina subida y enlazada ✅"); st.rerun()
            except Exception as e:
                st.error(f"No se pudo subir: {e}")
    with c2:
        up_plan = st.file_uploader("Plan (PDF)", type=["pdf"])
        if up_plan and st.button("⬆️ Subir Plan"):
            try:
                cita_folder = ensure_cita_folder(pid, fecha_pdf.strip())
                drive = get_drive()
                ext = Path(up_plan.name).suffix or ".pdf"
                target = f"{fecha_pdf.strip()}_plan{ext}"
                pdf = upload_pdf_to_folder(up_plan.read(), target, cita_folder)
                upsert_medicion(pid, fecha_pdf.strip(), rutina_pdf=None, plan_pdf=pdf["webViewLink"])
                pf = df_sql("SELECT drive_folder_id FROM pacientes WHERE id=%s",(pid,))
                if not pf.empty and (pf.loc[0,"drive_folder_id"] or "").strip():
                    from modules.core import enforce_patient_pdf_quota
                    enforce_patient_pdf_quota(pf.loc[0,"drive_folder_id"].strip(), keep=10, send_to_trash=True)
                st.success("Plan subido y enlazado ✅"); st.rerun()
            except Exception as e:
                st.error(f"No se pudo subir: {e}")

    st.divider()
    citas = df_sql("SELECT fecha, rutina_pdf, plan_pdf FROM mediciones WHERE paciente_id=%s ORDER BY fecha DESC", (pid,))
    if citas.empty:
        st.info("Este paciente aún no tiene PDFs.")
    else:
        fecha_sel = st.selectbox("Ver PDFs de la cita", citas["fecha"].tolist())
        actual = citas.loc[citas["fecha"] == fecha_sel].iloc[0]
        r, p = (actual["rutina_pdf"] or "").strip(), (actual["plan_pdf"] or "").strip()
        cl, cr = st.columns(2)
        with cl: st.link_button("🔗 Abrir Rutina (PDF)", r, disabled=(not bool(r)))
        with cr: st.link_button("🔗 Abrir Plan (PDF)", p, disabled=(not bool(p)))
        with st.expander("👁️ Vista previa (Drive)"):
            from modules.core import to_drive_preview
            if r: st.components.v1.iframe(to_drive_preview(r), height=360)
            if p: st.components.v1.iframe(to_drive_preview(p), height=360)

# ---- FOTOS ----
with tab_fotos:
    st.caption("Sube fotos asociadas a una **fecha** (YYYY-MM-DD).")
    colA, colB = st.columns([2, 1])
    with colA:
        fecha_f = st.text_input("Fecha", value=str(date.today()), key=f"fotos_fecha_{pid}")
        up_imgs = st.file_uploader("Agregar fotos", accept_multiple_files=True, type=["jpg","jpeg","png","webp"])
    with colB:
        if st.button("⬆️ Subir fotos"):
            if not up_imgs:
                st.warning("Selecciona al menos una imagen.")
            else:
                folder_id = ensure_cita_folder(pid, fecha_f.strip())
                drv = get_drive()
                for fimg in up_imgs:
                    ext = Path(fimg.name).suffix or ".jpg"
                    mime = fimg.type or "image/jpeg"
                    target_name = f"{fecha_f.strip()}_{Path(fimg.name).stem}{ext}"
                    f = upload_image_to_folder(fimg.read(), target_name, folder_id, mime)
                    exec_sql("""
                        INSERT INTO fotos (paciente_id, fecha, drive_file_id, web_view_link, filename)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (pid, fecha_f.strip(), f["id"], f.get("webViewLink",""), target_name))
                asociar_medicion_a_cita(pid, fecha_f.strip())
                st.success("Fotos subidas ✅"); st.rerun()

    gal = df_sql("SELECT id, fecha, drive_file_id FROM fotos WHERE paciente_id=%s ORDER BY fecha DESC", (pid,))
    if gal.empty:
        st.info("Sin fotos aún.")
    else:
        def _chunk(lst, n):
            for i in range(0, len(lst), n):
                yield lst[i:i+n]
        for fch in sorted(gal["fecha"].unique(), reverse=True):
            st.markdown(f"### 🗓️ {fch}")
            fila = gal[gal["fecha"] == fch].reset_index(drop=True).to_dict("records")
            for fila4 in _chunk(fila, 4):
                cols = st.columns(4, gap="medium")
                for i, r in enumerate(fila4):
                    with cols[i]:
                        img_url = drive_image_view_url(r["drive_file_id"]) if r.get("drive_file_id") else ""
                        dl_url = drive_image_download_url(r["drive_file_id"]) if r.get("drive_file_id") else None
                        st.markdown(f'<div style="background:#111;border-radius:12px;overflow:hidden;display:flex;justify-content:center;"><img src="{img_url}" style="height:220px;object-fit:contain;"></div>', unsafe_allow_html=True)
                        if dl_url:
                            st.link_button("⬇️ Descargar", dl_url)
                        if st.button("🗑️ Eliminar", key=f"del_foto_{pid}_{r['id']}"):
                            st.session_state["_delete_photo_id"] = int(r["id"])
            if "_delete_photo_id" in st.session_state:
                @st.dialog("Confirmar eliminación")
                def _confirm_delete_dialog():
                    st.warning("Esta acción eliminará la foto de Drive y de la base de datos.")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ Sí, borrar"):
                            delete_foto(st.session_state["_delete_photo_id"])
                            st.session_state.pop("_delete_photo_id", None)
                            st.success("Foto eliminada ✅"); st.rerun()
                    with c2:
                        if st.button("❌ Cancelar"):
                            st.session_state.pop("_delete_photo_id", None)
                            st.info("Operación cancelada")
                _confirm_delete_dialog()
                break

st.divider()

# Atajos opcionales a otras páginas (si quieres; o confía en el sidebar)
if st.button("Ir a Gestion Hoy →"):
    st.switch_page("pages/2_Carmen_Hoy.py")
if st.button("Ir a Gestión de Citas →"):
    st.switch_page("pages/4_Carmen_Citas.py")

# Cerrar sesión (sustituye al antiguo st.page_link)
if st.button("🚪 Cerrar sesión"):
    st.session_state.role = None
    st.session_state.paciente = None
    st.rerun()
