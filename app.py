# app_pacientes_streamlit_clean.py
# Gestión de pacientes con Postgres (Neon) + Google Drive (PDFs/Fotos)
# Vista Admin y Vista Paciente (solo lectura)

import os
import io
import re
import uuid
import hashlib
from pathlib import Path
from datetime import date

import pandas as pd
import psycopg
import streamlit as st
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError

# =========================
# Configuración básica UI
# =========================
st.set_page_config(page_title="Pacientes", page_icon="🩺", layout="wide")

# =========================
# Conexión BD (Neon / Postgres)
# =========================
NEON_URL = st.secrets.get("NEON_DATABASE_URL") or os.getenv("NEON_DATABASE_URL")

@st.cache_resource
def conn():
    if not NEON_URL:
        st.stop()
    return psycopg.connect(NEON_URL, autocommit=True)

def exec_sql(q_ps: str, p: tuple = ()):  # non-SELECT
    with conn().cursor() as cur:
        cur.execute(q_ps, p)

def df_sql(q_ps: str, p: tuple = ()):  # SELECT → DataFrame
    return pd.read_sql_query(q_ps, conn(), params=p)

# =========================
# Esquema (idempotente)
# =========================

def setup_db():
    exec_sql(
        """
        CREATE TABLE IF NOT EXISTS pacientes(
          id         BIGSERIAL PRIMARY KEY,
          nombre     TEXT NOT NULL,
          fecha_nac  TEXT,
          telefono   TEXT,
          correo     TEXT,
          notas      TEXT,
          token      TEXT UNIQUE,
          drive_folder_id TEXT
        )
        """
    )

    exec_sql(
        """
        CREATE TABLE IF NOT EXISTS mediciones(
          id              BIGSERIAL PRIMARY KEY,
          paciente_id     BIGINT NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
          fecha           TEXT NOT NULL,
          rutina_pdf      TEXT,
          plan_pdf        TEXT,
          peso_kg         DOUBLE PRECISION,
          grasa_pct       DOUBLE PRECISION,
          musculo_pct     DOUBLE PRECISION,
          brazo_rest      DOUBLE PRECISION,
          brazo_flex      DOUBLE PRECISION,
          pecho_rest      DOUBLE PRECISION,
          pecho_flex      DOUBLE PRECISION,
          cintura_cm      DOUBLE PRECISION,
          cadera_cm       DOUBLE PRECISION,
          pierna_cm       DOUBLE PRECISION,
          pantorrilla_cm  DOUBLE PRECISION,
          notas           TEXT,
          drive_cita_folder_id TEXT,
          CONSTRAINT mediciones_unq UNIQUE (paciente_id, fecha)
        )
        """
    )

    exec_sql(
        """
        CREATE TABLE IF NOT EXISTS fotos(
          id           BIGSERIAL PRIMARY KEY,
          paciente_id  BIGINT NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
          fecha        TEXT NOT NULL,
          drive_file_id TEXT,
          web_view_link TEXT,
          filename     TEXT
        )
        """
    )

setup_db()

# =========================
# Google Drive
# =========================
SCOPES = ["https://www.googleapis.com/auth/drive"]
ROOT_FOLDER_ID = st.secrets.get("DRIVE_ROOT_FOLDER_ID")  # opcional (raíz donde crear las carpetas de pacientes)

@st.cache_resource
def get_drive():
    # 1) OAuth (cuota del usuario)
    if "google_oauth" in st.secrets:
        i = st.secrets["google_oauth"]
        creds = Credentials(
            token=None,
            refresh_token=i["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=i["client_id"],
            client_secret=i["client_secret"],
            scopes=SCOPES,
        )
        return build("drive", "v3", credentials=creds)
    # 2) Service Account (recomendado en Unidad Compartida)
    i = dict(st.secrets["gcp_service_account"])  # type: ignore
    creds = service_account.Credentials.from_service_account_info(i, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)

def make_anyone_reader(file_id: str):
    try:
        get_drive().permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
            supportsAllDrives=True,
        ).execute()
    except HttpError as e:
        st.info(f"[Drive] No pude hacer público {file_id}: {e}")

def drive_image_view_url(file_id: str) -> str:
    return f"https://lh3.googleusercontent.com/d/{file_id}=s0"

def drive_image_download_url(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=download&id={file_id}"

# -------- Carpetas por paciente / cita --------

def ensure_patient_folder(nombre: str, pid: int) -> str:
    drive = get_drive()
    folder_name = f"{pid:05d} - {nombre}"
    escaped = folder_name.replace("'", "\\'")
    q = (
        "mimeType='application/vnd.google-apps.folder' and trashed=false "
        f"and name='{escaped}' "
        + (f"and '{ROOT_FOLDER_ID}' in parents" if ROOT_FOLDER_ID else "")
    )
    res = drive.files().list(
        q=q,
        fields="files(id)",
        pageSize=1,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    f = res.get("files", [])
    if f:
        return f[0]["id"]
    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if ROOT_FOLDER_ID:
        meta["parents"] = [ROOT_FOLDER_ID]
    folder = drive.files().create(
        body=meta,
        fields="id",
        supportsAllDrives=True,
    ).execute()
    return folder["id"]

def ensure_cita_folder(pid: int, fecha_str: str) -> str:
    d = df_sql("SELECT drive_folder_id FROM pacientes WHERE id=%s", (pid,))
    if d.empty or not (d.loc[0, "drive_folder_id"] or "").strip():
        raise RuntimeError("El paciente no tiene carpeta de Drive asignada.")
    patient_folder_id = d.loc[0, "drive_folder_id"].strip()

    m = df_sql(
        "SELECT drive_cita_folder_id FROM mediciones WHERE paciente_id=%s AND fecha=%s",
        (pid, fecha_str),
    )
    if not m.empty and (m.loc[0, "drive_cita_folder_id"] or "").strip():
        return m.loc[0, "drive_cita_folder_id"].strip()

    drive = get_drive()
    q = (
        "mimeType='application/vnd.google-apps.folder' and trashed=false "
        f"and name='{fecha_str}' and '{patient_folder_id}' in parents"
    )
    res = drive.files().list(
        q=q,
        fields="files(id)",
        pageSize=1,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files", [])
    if files:
        cita_folder_id = files[0]["id"]
    else:
        meta = {
            "name": fecha_str,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [patient_folder_id],
        }
        cita_folder_id = (
            drive.files()
            .create(body=meta, fields="id", supportsAllDrives=True)
            .execute()["id"]
        )

    exec_sql(
        """
        INSERT INTO mediciones (paciente_id, fecha, drive_cita_folder_id)
        VALUES (%s,%s,%s)
        ON CONFLICT (paciente_id, fecha)
        DO UPDATE SET drive_cita_folder_id = EXCLUDED.drive_cita_folder_id
        """,
        (pid, fecha_str, cita_folder_id),
    )
    return cita_folder_id

# -------- Subidas a Drive --------

def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^\w\s.-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")

def _ext_of(filename: str, default_ext: str) -> str:
    ext = Path(filename).suffix.lower()
    return ext if ext else default_ext

def _ensure_unique_name(drive, parent_id: str, name: str) -> str:
    base, ext = Path(name).stem, Path(name).suffix
    safe_base = base.replace("'", "\\'")
    q = (
        "trashed=false and "
        f"'{parent_id}' in parents and "
        f"name contains '{safe_base}'"
    )
    res = drive.files().list(
        q=q,
        fields="files(name)",
        pageSize=100,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    existing = {f["name"] for f in res.get("files", [])}
    if name not in existing:
        return name
    i = 2
    while True:
        cand = f"{base}-{i}{ext}"
        if cand not in existing:
            return cand
        i += 1

def upload_pdf_to_folder(file_bytes: bytes, filename: str, folder_id: str) -> dict:
    drive = get_drive()
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="application/pdf", resumable=False)
    meta = {"name": filename, "parents": [folder_id]}
    f = (
        drive.files()
        .create(body=meta, media_body=media, fields="id,webViewLink", supportsAllDrives=True)
        .execute()
    )
    make_anyone_reader(f["id"])
    return f

def upload_image_to_folder(file_bytes: bytes, filename: str, folder_id: str, mime: str) -> dict:
    drive = get_drive()
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime, resumable=False)
    meta = {"name": filename, "parents": [folder_id]}
    f = (
        drive.files()
        .create(body=meta, media_body=media, fields="id,webViewLink,thumbnailLink", supportsAllDrives=True)
        .execute()
    )
    make_anyone_reader(f["id"])
    return f

def to_drive_preview(url: str) -> str:
    if not url:
        return ""
    u = url.strip()
    if "drive.google.com" in u:
        if "/view" in u:
            u = u.replace("/view", "/preview")
        elif not u.endswith("/preview"):
            u = u.rstrip("/") + "/preview"
    return u

# -------- Reglas utilitarias --------

def get_patient_folder_id(pid: int) -> str:
    d = df_sql("SELECT drive_folder_id FROM pacientes WHERE id=%s", (pid,))
    if d.empty or not (d.loc[0, "drive_folder_id"] or "").strip():
        raise RuntimeError("El paciente no tiene carpeta de Drive asignada.")
    return d.loc[0, "drive_folder_id"].strip()

def enforce_patient_pdf_quota(patient_folder_id: str, keep: int = 10, send_to_trash: bool = True):
    drive = get_drive()

    def _list_pdfs_in(folder_id: str):
        files, page_token = [], None
        while True:
            resp = drive.files().list(
                q=f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false",
                fields="nextPageToken, files(id, name, createdTime)",
                orderBy="createdTime asc",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            files.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return files

    all_pdfs = _list_pdfs_in(patient_folder_id)
    # subcarpetas de cita
    subs, page_token = [], None
    while True:
        resp = drive.files().list(
            q=f"'{patient_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="nextPageToken, files(id)",
            pageSize=1000,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        subs.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    for sf in subs:
        all_pdfs.extend(_list_pdfs_in(sf["id"]))

    if len(all_pdfs) > keep:
        excess = len(all_pdfs) - keep
        all_pdfs.sort(key=lambda x: x.get("createdTime", ""))
        to_remove = all_pdfs[:excess]
        for f in to_remove:
            if send_to_trash:
                drive.files().update(fileId=f["id"], body={"trashed": True}, supportsAllDrives=True).execute()
            else:
                drive.files().delete(fileId=f["id"], supportsAllDrives=True).execute()

# =========================
# Dominio: Pacientes / Citas / Fotos
# =========================

def delete_drive_file(file_id: str):
    try:
        get_drive().files().delete(fileId=file_id).execute()
    except Exception:
        pass

def delete_foto(photo_id: int):
    fila = df_sql("SELECT drive_file_id FROM fotos WHERE id = %s", (photo_id,))
    if fila.empty:
        st.warning("No se encontró la foto en la base.")
        return
    file_id = fila.loc[0, "drive_file_id"]
    if file_id:
        delete_drive_file(file_id)
    exec_sql("DELETE FROM fotos WHERE id = %s", (photo_id,))

def sha256(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()

ADMIN_USER = "Carmen"
ADMIN_PASSWORD_HASH = sha256("admin123")  # cámbialo o usa st.secrets["ADMIN_PASSWORD"]

def is_admin_ok(user, password):
    return (user == ADMIN_USER) and (sha256(password) == ADMIN_PASSWORD_HASH)

def get_paciente_by_token(tok: str):
    d = df_sql("SELECT * FROM pacientes WHERE token = %s", (tok,))
    return None if d.empty else d.iloc[0]

def get_or_create_token(pid: int):
    d = df_sql("SELECT token FROM pacientes WHERE id = %s", (pid,))
    if d.empty:
        return None
    tok = d.loc[0, "token"]
    if not tok:
        tok = uuid.uuid4().hex[:8]
        exec_sql("UPDATE pacientes SET token = %s WHERE id = %s", (tok, pid))
    return tok

@st.cache_data(ttl=30)
def buscar_pacientes(filtro: str):
    if not filtro:
        return pd.DataFrame(columns=["id", "nombre"])
    return df_sql(
        "SELECT id, nombre FROM pacientes WHERE nombre ILIKE %s ORDER BY nombre",
        (f"%{filtro}%",),
    )

def query_mediciones(pid: int):
    return df_sql(
        """
        SELECT fecha, rutina_pdf, plan_pdf
        FROM mediciones
        WHERE paciente_id = %s
        ORDER BY fecha DESC
        """,
        (pid,),
    )

def delete_cita(pid: int, fecha_str: str, remove_drive: bool = False, send_to_trash: bool = True):
    m = df_sql(
        "SELECT drive_cita_folder_id FROM mediciones WHERE paciente_id=%s AND fecha=%s",
        (pid, fecha_str),
    )
    cita_folder_id = (m.loc[0, "drive_cita_folder_id"].strip() if not m.empty and m.loc[0, "drive_cita_folder_id"] else None)
    exec_sql("DELETE FROM fotos WHERE paciente_id=%s AND fecha=%s", (pid, fecha_str))
    exec_sql("DELETE FROM mediciones WHERE paciente_id=%s AND fecha=%s", (pid, fecha_str))
    if remove_drive and cita_folder_id:
        drive = get_drive()
        try:
            if send_to_trash:
                drive.files().update(fileId=cita_folder_id, body={"trashed": True}, supportsAllDrives=True).execute()
            else:
                drive.files().delete(fileId=cita_folder_id, supportsAllDrives=True).execute()
        except Exception as e:
            st.info(f"[Drive] No pude eliminar la carpeta de la cita ({cita_folder_id}): {e}")

def upsert_medicion(pid: int, fecha: str, rutina_pdf: str | None, plan_pdf: str | None):
    exec_sql(
        """
        INSERT INTO mediciones (paciente_id, fecha, rutina_pdf, plan_pdf)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (paciente_id, fecha)
        DO UPDATE SET rutina_pdf = EXCLUDED.rutina_pdf, plan_pdf = EXCLUDED.plan_pdf
        """,
        (pid, fecha, rutina_pdf, plan_pdf),
    )

def save_image(file, pid: int, fecha_str: str):
    drive = get_drive()
    folder_id = ensure_cita_folder(pid, fecha_str.strip())
    ya = df_sql(
        "SELECT COUNT(*)::int FROM fotos WHERE paciente_id=%s AND fecha=%s",
        (pid, fecha_str),
    )
    n = int(ya.iloc[0, 0]) + 1
    ext = _ext_of(file.name, ".jpg")
    base = f"{fecha_str.strip()}_foto_{n:03d}{ext}"
    target_name = _ensure_unique_name(drive, folder_id, _slugify(base))
    mime = file.type or "image/jpeg"
    f = upload_image_to_folder(file.read(), target_name, folder_id, mime)
    exec_sql(
        """
        INSERT INTO fotos (paciente_id, fecha, drive_file_id, web_view_link, filename)
        VALUES (%s,%s,%s,%s,%s)
        """,
        (pid, fecha_str, f["id"], f["webViewLink"], target_name),
    )
    return f["id"]

# =========================
# UI (Admin / Paciente)
# =========================

st.title("🩺 Gestión de Pacientes")

with st.sidebar:
    st.markdown("## Acceso")
    tabs = st.tabs(["👩‍⚕️ Admin", "🧑 Paciente"])
    with tabs[0]:
        a_user = st.text_input("Usuario", value=ADMIN_USER, disabled=True)
        a_pass = st.text_input("Contraseña", type="password")
        admin_login = st.button("Entrar como Admin")
    with tabs[1]:
        token_from_url = st.query_params.get("token", [None])[0] if hasattr(st, "query_params") else None
        p_token = st.text_input("Token de acceso (o link con ?token=...)", value=token_from_url or "")
        patient_login = st.button("Entrar como Paciente")

if "role" not in st.session_state:
    st.session_state.role = None
if "paciente" not in st.session_state:
    st.session_state.paciente = None

if admin_login:
    if is_admin_ok(a_user, a_pass):
        st.session_state.role = "admin"
        st.session_state.paciente = None
        st.success("Acceso admin concedido ✅")
        st.rerun()
    else:
        st.error("Credenciales inválidas")

if patient_login:
    pac = get_paciente_by_token(p_token.strip()) if p_token.strip() else None
    if pac is None:
        st.error("Token inválido o vacío")
    else:
        st.session_state.role = "paciente"
        st.session_state.paciente = dict(pac)
        st.success(f"Bienvenido, {pac['nombre']} ✅")
        st.rerun()

role = st.session_state.role

if "google_oauth" not in st.secrets:
    st.warning(
        "⚠️ Usando **Service Account**. Para evitar `storageQuotaExceeded`, usa OAuth o una Unidad Compartida en Drive."
    )

# ---------- ADMIN ----------
if role == "admin":
    st.subheader("👩‍⚕️ Vista de administración (Carmen)")

    # Crear paciente
    if st.button("➕ Nuevo paciente"):
        @st.dialog("➕ Nuevo paciente")
        def nuevo_paciente():
            with st.form("form_nuevo_paciente", clear_on_submit=True):
                nombre = st.text_input("Nombre completo *")
                fnac = st.date_input("Fecha de nacimiento", value=date(2000, 1, 1))
                tel = st.text_input("Teléfono")
                mail = st.text_input("Correo")
                notas = st.text_area("Notas")
                enviar = st.form_submit_button("Guardar")
            if enviar:
                if not nombre.strip():
                    st.error("El nombre es obligatorio."); return
                dup = df_sql("SELECT id FROM pacientes WHERE nombre = %s", (nombre.strip(),))
                if not dup.empty:
                    st.warning("Ya existe un paciente con ese nombre."); return
                tok = uuid.uuid4().hex[:8]
                new_row = df_sql(
                    """
                    INSERT INTO pacientes (nombre, fecha_nac, telefono, correo, notas, token)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                    (nombre.strip(), str(fnac), tel.strip(), mail.strip(), notas.strip(), tok),
                )
                new_id = int(new_row.iloc[0]["id"])
                folder_id = ensure_patient_folder(nombre.strip(), new_id)
                exec_sql("UPDATE pacientes SET drive_folder_id=%s WHERE id=%s", (folder_id, new_id))
                st.success("Paciente creado y carpeta en Drive lista ✅"); st.rerun()
        nuevo_paciente()

    # Buscar paciente
    with st.form("form_buscar_paciente"):
        filtro = st.text_input("Buscar paciente", placeholder="Ej. Ana, Juan…")
        do_search = st.form_submit_button("Buscar")
    if do_search:
        if len(filtro.strip()) < 2:
            st.warning("Escribe al menos 2 letras para buscar.")
        else:
            st.session_state["buscados_df"] = buscar_pacientes(filtro.strip())
    buscados = st.session_state.get("buscados_df", pd.DataFrame(columns=["id", "nombre"]))
    if buscados.empty:
        st.caption("Escribe arriba y pulsa **Buscar** para ver resultados.")
        st.stop()

    st.markdown("#### Resultados")
    c1, c2 = st.columns([2, 1])
    with c1:
        pac_sel = st.selectbox("Paciente", buscados["nombre"].tolist(), key="adm_pac")
        pid = int(buscados.loc[buscados["nombre"] == pac_sel, "id"].iloc[0])
        if st.button("🗑️ Eliminar", key=f"del_{pid}"):
            st.session_state["_del_pid"] = pid
            st.session_state["_del_name"] = pac_sel
        if st.session_state.get("_del_pid") is not None:
            @st.dialog("Confirmar eliminación")
            def _confirm_delete_dialog():
                st.warning(f"Se eliminará **{st.session_state['_del_name']}** y todos sus datos.")
                d1, d2 = st.columns(2)
                with d1:
                    if st.button("❌ Cancelar"):
                        st.session_state.pop("_del_pid", None)
                        st.session_state.pop("_del_name", None)
                with d2:
                    if st.button("✅ Sí, eliminar"):
                        # eliminar dependencias y paciente
                        exec_sql("DELETE FROM fotos WHERE paciente_id=%s", (pid,))
                        exec_sql("DELETE FROM mediciones WHERE paciente_id=%s", (pid,))
                        exec_sql("DELETE FROM pacientes WHERE id=%s", (pid,))
                        st.session_state.pop("_del_pid", None)
                        st.session_state.pop("_del_name", None)
                        st.cache_data.clear()
                        st.session_state["buscados_df"] = buscar_pacientes(filtro.strip())
                        st.success("Paciente eliminado ✅"); st.rerun()
            _confirm_delete_dialog()
    with c2:
        if st.button("📋 Copiar token del paciente", use_container_width=True):
            tok = get_or_create_token(pid)
            st.code(tok, language="")
            st.caption("Usa este token para el acceso del paciente.")

    tab_info, tab_medidas, tab_pdfs, tab_fotos = st.tabs(["🧾 Perfil", "📏 Mediciones", "📂 PDFs", "🖼️ Fotos"])

    # --- Mediciones ---
    with tab_medidas:
        with st.expander("➕ Nueva cita / Guardar o actualizar por fecha", expanded=False):
            with st.form("form_medicion"):
                f = st.text_input("Fecha de la medición (YYYY-MM-DD)", value=str(date.today()))
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
                notas_med = st.text_area("Notas de la medición", "")
                guardar_med = st.form_submit_button("Guardar/Actualizar medición")
            if guardar_med:
                def nz(x):
                    return None if x in (0, 0.0) else x
                exec_sql(
                    """
                    INSERT INTO mediciones (paciente_id, fecha)
                    VALUES (%s, %s) ON CONFLICT (paciente_id, fecha) DO NOTHING
                    """,
                    (pid, f.strip()),
                )
                exec_sql(
                    """
                    UPDATE mediciones
                    SET peso_kg=%s, grasa_pct=%s, musculo_pct=%s, brazo_rest=%s, brazo_flex=%s,
                        pecho_rest=%s, pecho_flex=%s, cintura_cm=%s, cadera_cm=%s, pierna_cm=%s,
                        pantorrilla_cm=%s, notas=%s
                    WHERE paciente_id=%s AND fecha=%s
                    """,
                    (
                        nz(peso_kg), nz(grasa), nz(musc), nz(brazo_r), nz(brazo_f), nz(pecho_r), nz(pecho_f),
                        nz(cintura), nz(cadera), nz(pierna), nz(pantorrilla), (notas_med.strip() or None),
                        pid, f.strip(),
                    ),
                )
                st.success("Medición guardada ✅"); st.rerun()

        # Editar cita existente
        citas_m = df_sql("SELECT fecha FROM mediciones WHERE paciente_id=%s ORDER BY fecha DESC", (pid,))
        if not citas_m.empty:
            with st.expander("✏️ Editar una cita existente", expanded=False):
                fecha_sel_m = st.selectbox("Editar medición de fecha", citas_m["fecha"].tolist(), key=f"med_fecha_{pid}")
                actual_m = df_sql("SELECT * FROM mediciones WHERE paciente_id=%s AND fecha=%s", (pid, fecha_sel_m)).iloc[0]
                cols = st.columns(6)
                def val(x): return float(x) if x is not None else 0.0
                campos = [
                    ("peso_kg", "Peso (kg)", 0), ("grasa_pct", "% Grasa", 1), ("musculo_pct", "% Músculo", 2),
                    ("brazo_rest", "Brazo reposo", 3), ("brazo_flex", "Brazo flex", 4), ("pecho_rest", "Pecho reposo", 5),
                    ("pecho_flex", "Pecho flex", 0), ("cintura_cm", "Cintura (cm)", 1), ("cadera_cm", "Cadera (cm)", 2),
                    ("pierna_cm", "Pierna (cm)", 3), ("pantorrilla_cm", "Pantorrilla (cm)", 4),
                ]
                new_vals = {}
                for key, label, col_idx in campos:
                    with cols[col_idx]:
                        new_vals[key] = st.number_input(label, value=val(actual_m[key]), step=0.1, key=f"med_edit_{key}_{pid}_{fecha_sel_m}")
                notas_edit = st.text_area("Notas", actual_m["notas"] or "", key=f"med_edit_notas_{pid}_{fecha_sel_m}")
                cA, cB, cC = st.columns(3)
                with cA:
                    if st.button("💾 Guardar cambios", key=f"save_edit_{pid}_{fecha_sel_m}"):
                        exec_sql(
                            """
                            UPDATE mediciones
                            SET peso_kg=%s, grasa_pct=%s, musculo_pct=%s, brazo_rest=%s, brazo_flex=%s,
                                pecho_rest=%s, pecho_flex=%s, cintura_cm=%s, cadera_cm=%s, pierna_cm=%s,
                                pantorrilla_cm=%s, notas=%s
                            WHERE paciente_id=%s AND fecha=%s
                            """,
                            (
                                new_vals["peso_kg"] or None, new_vals["grasa_pct"] or None, new_vals["musculo_pct"] or None,
                                new_vals["brazo_rest"] or None, new_vals["brazo_flex"] or None, new_vals["pecho_rest"] or None,
                                new_vals["pecho_flex"] or None, new_vals["cintura_cm"] or None, new_vals["cadera_cm"] or None,
                                new_vals["pierna_cm"] or None, new_vals["pantorrilla_cm"] or None,
                                (notas_edit.strip() or None), pid, fecha_sel_m,
                            ),
                        )
                        st.success("Mediciones actualizadas ✅"); st.rerun()
                with cB:
                    if st.button("🧹 Vaciar medidas", key=f"clear_edit_{pid}_{fecha_sel_m}"):
                        exec_sql(
                            """
                            UPDATE mediciones
                            SET peso_kg=NULL, grasa_pct=NULL, musculo_pct=NULL, brazo_rest=NULL, brazo_flex=NULL,
                                pecho_rest=NULL, pecho_flex=NULL, cintura_cm=NULL, cadera_cm=NULL, pierna_cm=NULL,
                                pantorrilla_cm=NULL, notas=NULL
                            WHERE paciente_id = %s AND fecha = %s
                            """,
                            (pid, fecha_sel_m),
                        )
                        st.success("Mediciones vaciadas ✅"); st.rerun()
                with cC:
                    if st.button("🗑️ Eliminar cita (+ opcional Drive)", key=f"del_cita_{pid}_{fecha_sel_m}"):
                        delete_cita(pid, fecha_sel_m, remove_drive=True, send_to_trash=True)
                        st.success(f"Cita {fecha_sel_m} eliminada. Carpeta enviada a papelera (si existía)."); st.rerun()

        st.markdown("#### 📜 Historial")
        hist = df_sql(
            """
            SELECT fecha,
                   peso_kg AS peso_KG, grasa_pct AS grasa, musculo_pct AS musculo,
                   brazo_rest AS brazo_rest_CM, brazo_flex AS brazo_flex_CM,
                   pecho_rest AS pecho_rest_CM, pecho_flex AS pecho_flex_CM,
                   cintura_cm AS cintura_CM, cadera_cm AS cadera_CM,
                   pierna_cm AS pierna_CM, pantorrilla_cm AS pantorrilla_CM
            FROM mediciones
            WHERE paciente_id = %s
            ORDER BY fecha DESC
            """,
            (pid,),
        )
        if hist.empty:
            st.info("Sin mediciones aún.")
        else:
            st.dataframe(hist, use_container_width=True, hide_index=True)

    # --- Perfil ---
    with tab_info:
        datos = df_sql("SELECT * FROM pacientes WHERE id = %s", (pid,))
        row = datos.iloc[0]
        with st.form("form_edit_paciente"):
            nombre = st.text_input("Nombre", row["nombre"])
            fnac = st.text_input("Fecha de nacimiento (YYYY-MM-DD)", row["fecha_nac"] or "")
            tel = st.text_input("Teléfono", row["telefono"] or "")
            mail = st.text_input("Correo", row["correo"] or "")
            notas = st.text_area("Notas", row["notas"] or "")
            guardar = st.form_submit_button("Guardar cambios")
        if guardar:
            exec_sql(
                """
                UPDATE pacientes SET nombre=%s, fecha_nac=%s, telefono=%s, correo=%s, notas=%s
                WHERE id=%s
                """,
                (nombre.strip(), fnac.strip(), tel.strip(), mail.strip(), notas.strip(), pid),
            )
            st.success("Perfil actualizado ✅"); st.rerun()

    # --- PDFs ---
    with tab_pdfs:
        st.caption("Sube y consulta los PDFs de cada cita (YYYY-MM-DD).")
        fecha_pdf = st.text_input("Fecha de la cita", value=str(date.today()), key=f"pdf_fecha_{pid}")
        col_u1, col_u2 = st.columns(2)
        with col_u1:
            up_rutina = st.file_uploader("Seleccionar **Rutina (PDF)**", type=["pdf"], key=f"up_rutina_tab_{pid}")
        with col_u2:
            up_plan = st.file_uploader("Seleccionar **Plan alimenticio (PDF)**", type=["pdf"], key=f"up_plan_tab_{pid}")

        b1, b2 = st.columns(2)
        with b1:
            if up_rutina and st.button("⬆️ Subir Rutina a Drive", key=f"btn_rutina_tab_{pid}"):
                with st.spinner("Subiendo Rutina a Drive..."):
                    cita_folder = ensure_cita_folder(pid, fecha_pdf.strip())
                    drive = get_drive()
                    ext = _ext_of(up_rutina.name, ".pdf")
                    target_name = _ensure_unique_name(drive, cita_folder, _slugify(f"{fecha_pdf.strip()}_rutina{ext}"))
                    pdf = upload_pdf_to_folder(up_rutina.read(), target_name, cita_folder)
                    exec_sql(
                        """
                        INSERT INTO mediciones (paciente_id, fecha, rutina_pdf)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (paciente_id, fecha)
                        DO UPDATE SET rutina_pdf = EXCLUDED.rutina_pdf
                        """,
                        (pid, fecha_pdf.strip(), pdf["webViewLink"]),
                    )
                    patient_folder_id = get_patient_folder_id(pid)
                    enforce_patient_pdf_quota(patient_folder_id, keep=10, send_to_trash=True)
                    st.success("Rutina subida y enlazada ✅"); st.rerun()
        with b2:
            if up_plan and st.button("⬆️ Subir Plan a Drive", key=f"btn_plan_tab_{pid}"):
                with st.spinner("Subiendo Plan a Drive..."):
                    cita_folder = ensure_cita_folder(pid, fecha_pdf.strip())
                    drive = get_drive()
                    ext = _ext_of(up_plan.name, ".pdf")
                    target_name = _ensure_unique_name(drive, cita_folder, _slugify(f"{fecha_pdf.strip()}_plan{ext}"))
                    pdf = upload_pdf_to_folder(up_plan.read(), target_name, cita_folder)
                    exec_sql(
                        """
                        INSERT INTO mediciones (paciente_id, fecha, plan_pdf)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (paciente_id, fecha)
                        DO UPDATE SET plan_pdf = EXCLUDED.plan_pdf
                        """,
                        (pid, fecha_pdf.strip(), pdf["webViewLink"]),
                    )
                    patient_folder_id = get_patient_folder_id(pid)
                    enforce_patient_pdf_quota(patient_folder_id, keep=10, send_to_trash=True)
                    st.success("Plan subido y enlazado ✅"); st.rerun()

        st.divider()
        citas = query_mediciones(pid)
        if citas.empty:
            st.info("Este paciente aún no tiene PDFs registrados.")
        else:
            fecha_sel = st.selectbox("Ver PDFs de la cita", citas["fecha"].tolist(), key=f"pdfs_ver_{pid}")
            actual = citas.loc[citas["fecha"] == fecha_sel].iloc[0]
            r, p = (actual["rutina_pdf"] or "").strip(), (actual["plan_pdf"] or "").strip()
            cL, cR = st.columns(2)
            with cL:
                st.markdown("**Rutina**"); st.link_button("🔗 Abrir Rutina (PDF)", r, disabled=(not bool(r)))
            with cR:
                st.markdown("**Plan alimenticio**"); st.link_button("🔗 Abrir Plan (PDF)", p, disabled=(not bool(p)))
            with st.expander("👁️ Vista previa (Drive)"):
                if r: st.components.v1.iframe(to_drive_preview(r), height=360)
                if p: st.components.v1.iframe(to_drive_preview(p), height=360)
            if st.button("🧹 Vaciar ambos enlaces de esta cita", key=f"vaciar_pdf_{pid}_{fecha_sel}"):
                exec_sql(
                    "UPDATE mediciones SET rutina_pdf=NULL, plan_pdf=NULL WHERE paciente_id=%s AND fecha=%s",
                    (pid, fecha_sel),
                )
                st.success("PDFs vaciados ✅"); st.rerun()

    # --- Fotos ---
    with tab_fotos:
        if "_photos_css_loaded_admin" not in st.session_state:
            st.markdown(
                """
                <style>
                  .photo-card { background:#111;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.2);display:flex;flex-direction:column;align-items:center; }
                  .photo-card img { height:220px;width:auto;object-fit:contain;display:block;margin:auto; }
                </style>
                """,
                unsafe_allow_html=True,
            )
            st.session_state._photos_css_loaded_admin = True

        st.caption("Sube fotos asociadas a una **cita/fecha** (YYYY-MM-DD).")
        colA, colB = st.columns([2, 1])
        with colA:
            fecha_f = st.text_input("Fecha", value=str(date.today()))
            up = st.file_uploader("Agregar fotos", accept_multiple_files=True, type=["jpg", "jpeg", "png", "webp"])
        with colB:
            if st.button("⬆️ Subir"):
                if not up:
                    st.warning("Selecciona al menos una imagen.")
                else:
                    for f in up:
                        save_image(f, pid, fecha_f.strip())
                    st.success("Fotos subidas ✅"); st.rerun()

        gal = df_sql(
            """
            SELECT id, fecha, drive_file_id
            FROM fotos WHERE paciente_id = %s ORDER BY fecha DESC
            """,
            (pid,),
        )
        if gal.empty:
            st.info("Sin fotos aún.")
        else:
            def _chunk(lst, n):
                for i in range(0, len(lst), n):
                    yield lst[i : i + n]
            for fch in sorted(gal["fecha"].unique(), reverse=True):
                st.markdown(f"### 🗓️ {fch}")
                fila = gal[gal["fecha"] == fch].reset_index(drop=True).to_dict("records")
                for fila4 in _chunk(fila, 4):
                    cols = st.columns(4, gap="medium")
                    for i, r in enumerate(fila4):
                        with cols[i]:
                            img_url = drive_image_view_url(r["drive_file_id"]) if r.get("drive_file_id") else ""
                            dl_url = drive_image_download_url(r["drive_file_id"]) if r.get("drive_file_id") else None
                            st.markdown(f"""
                            <div class="photo-card">
                              <img src="{img_url}" alt="foto">
                            </div>
                            """, unsafe_allow_html=True)
                            cdl, cdel = st.columns([1, 1])
                            with cdl:
                                if dl_url: st.link_button("⬇️ Descargar", dl_url)
                                else: st.caption("—")
                            with cdel:
                                del_key = f"admin_foto_del_{pid}_{fch}_{int(r['id'])}"
                                if st.button("🗑️ Eliminar", key=del_key):
                                    st.session_state._delete_photo_id = int(r["id"])  # set flag
                if "_delete_photo_id" in st.session_state:
                    @st.dialog("Confirmar eliminación")
                    def _confirm_delete_dialog():
                        st.warning("Esta acción eliminará la foto de Drive y de la base de datos.")
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("✅ Sí, borrar", key=f"dlg_del_ok_{st.session_state['_delete_photo_id']}"):
                                delete_foto(st.session_state["_delete_photo_id"])
                                st.session_state.pop("_delete_photo_id", None)
                                st.success("Foto eliminada ✅"); st.rerun()
                        with c2:
                            if st.button("❌ Cancelar", key=f"dlg_del_cancel_{st.session_state['_delete_photo_id']}"):
                                st.session_state.pop("_delete_photo_id", None)
                                st.info("Operación cancelada")
                    _confirm_delete_dialog()
                    break

# ---------- PACIENTE (solo lectura) ----------
elif role == "paciente":
    pac = st.session_state.paciente
    st.subheader(f"🧑 Portal del paciente — {pac['nombre']}")
    st.caption("Vista de solo lectura. Si necesitas cambios, contacta a tu coach.")

    with st.expander("🧾 Datos del perfil"):
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Nombre:**", pac["nombre"])
            st.write("**Fecha de nacimiento:**", pac["fecha_nac"] or "—")
            st.write("**Teléfono:**", pac["telefono"] or "—")
        with c2:
            st.write("**Correo:**", pac["correo"] or "—")
            st.write("**Notas:**"); st.write(pac["notas"] or "—")

    st.markdown("### 📂 Tus PDFs de citas")
    citas = query_mediciones(int(pac["id"]))
    if citas.empty:
        st.info("Aún no tienes PDFs registrados.")
    else:
        fecha_sel = st.selectbox("Fecha de la cita", citas["fecha"].tolist(), key=f"pdfs_fecha_ro_{pac['id']}")
        actual = citas.loc[citas["fecha"] == fecha_sel].iloc[0]
        r, p = (actual["rutina_pdf"] or "").strip(), (actual["plan_pdf"] or "").strip()
        c1, c2 = st.columns(2)
        with c1: st.link_button("🔗 Abrir Rutina (PDF)", r, disabled=(not bool(r)))
        with c2: st.link_button("🔗 Abrir Plan (PDF)", p, disabled=(not bool(p)))
        with st.expander("👁️ Vista previa (Drive)"):
            if r: st.components.v1.iframe(to_drive_preview(r), height=360)
            if p: st.components.v1.iframe(to_drive_preview(p), height=360)

    st.markdown("### 📏 Tus mediciones")
    hist_ro = df_sql(
        """
        SELECT fecha,
               peso_kg AS peso_KG, grasa_pct AS grasa, musculo_pct AS musculo,
               brazo_rest AS brazo_rest_CM, brazo_flex AS brazo_flex_CM,
               pecho_rest AS pecho_rest_CM, pecho_flex AS pecho_flex_CM,
               cintura_cm AS cintura_CM, cadera_cm AS cadera_CM,
               pierna_cm AS pierna_CM, pantorrilla_cm AS pantorrilla_CM,
               notas
        FROM mediciones
        WHERE paciente_id = %s
        ORDER BY fecha DESC
        """,
        (int(pac["id"]),),
    )
    if hist_ro.empty:
        st.info("Aún no hay mediciones registradas.")
    else:
        st.dataframe(hist_ro, use_container_width=True, hide_index=True)

    st.markdown("### 🖼️ Tus fotos")
    gal = df_sql(
        """
        SELECT fecha, drive_file_id, filename
        FROM fotos
        WHERE paciente_id = %s
        ORDER BY fecha DESC
        """,
        (int(pac["id"]),),
    )
    if "_photos_css_loaded_patient" not in st.session_state:
        st.markdown(
            """
            <style>
              .photo-card { background:#111;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.2);display:flex;flex-direction:column;align-items:center;margin-bottom:6px; }
              .photo-card img { height:220px;width:auto;object-fit:contain;display:block;margin:auto; }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.session_state._photos_css_loaded_patient = True

    def _chunk(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i : i + n]

    for fch in sorted(gal["fecha"].unique(), reverse=True):
        st.markdown(f"### 🗓️ {fch}")
        fila = gal[gal["fecha"] == fch].reset_index(drop=True).to_dict("records")
        for fila4 in _chunk(fila, 4):
            cols = st.columns(4, gap="medium")
            for i, r in enumerate(fila4):
                with cols[i]:
                    img_url = drive_image_view_url(r["drive_file_id"]) if r.get("drive_file_id") else ""
                    dl_url = drive_image_download_url(r["drive_file_id"]) if r.get("drive_file_id") else None
                    st.markdown(
                        f"""
                        <div class=\"photo-card\"><img src=\"{img_url}\" alt=\"foto\"></div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if dl_url:
                        st.link_button("⬇️ Descargar", dl_url)
                    else:
                        st.caption("—")

else:
    st.info("Elige un modo de acceso en la barra lateral (Admin o Paciente).")


