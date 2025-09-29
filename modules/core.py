# modules/core.py
import os, io, re
from typing import Optional
from datetime import date, datetime, timedelta, time
import pandas as pd
import psycopg
import streamlit as st
from psycopg import errors as pg_errors
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError
import requests
import bcrypt
import unicodedata
from pathlib import Path
from googleapiclient.errors import HttpError

# --------- Secrets / env ---------
NEON_URL = st.secrets.get("NEON_DATABASE_URL") or os.getenv("NEON_DATABASE_URL")
PEPPER = (st.secrets.get("PASSWORD_PEPPER") or os.getenv("PASSWORD_PEPPER") or "").encode()
SCOPES = ["https://www.googleapis.com/auth/drive"]
ROOT_FOLDER_ID = os.getenv("DRIVE_ROOT_FOLDER_ID") or st.secrets.get("DRIVE_ROOT_FOLDER_ID")
# Admin (texto plano en secrets/env)
ADMIN_USER = os.getenv("CARMEN_USER") or st.secrets.get("CARMEN_USER", "carmen")
ADMIN_PASSWORD = os.getenv("CARMEN_PASSWORD") or st.secrets.get("CARMEN_PASSWORD")

# Agenda
PASO_MIN: int = 30
BLOQUEO_DIAS_MIN: int = 2  # hoy y mañana bloqueados (paciente agenda desde el día 3)

# --------- CONEXIÓN + DB ---------
@st.cache_resource
def _connect():
    if not NEON_URL:
        st.error("Falta NEON_DATABASE_URL en Secrets."); st.stop()
    # keepalives para conexiones serverless (Neon)
    return psycopg.connect(
        NEON_URL,
        autocommit=True,
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )

def conn():
    """Devuelve una conexión viva; si está cerrada o sin uso, reconecta."""
    c = _connect()
    try:
        # psycopg3: atributo .closed puede existir; además ping simple
        if getattr(c, "closed", False):
            raise psycopg.OperationalError("closed")
        with c.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception:
        # si falló, limpiamos el recurso cacheado y reconectamos
        try:
            st.cache_resource.clear()
        except Exception:
            pass
        c = _connect()
    return c

def exec_sql(q_ps: str, p: tuple = ()):
    with conn().cursor() as cur:
        cur.execute(q_ps, p)
    # invalidar caché de lecturas para que se vea el cambio
    try:
        st.cache_data.clear()
    except Exception:
        pass

def df_sql(q_ps: str, p: tuple = ()):
    # usar conn() cada vez para evitar objetos conexión zombis en pandas
    with conn() as c:
        return pd.read_sql_query(q_ps, c, params=p)

def setup_db():
    # pacientes (SIN token)
    exec_sql("""
    CREATE TABLE IF NOT EXISTS pacientes (
      id BIGSERIAL PRIMARY KEY,
      nombre TEXT NOT NULL,
      fecha_nac TEXT,
      telefono TEXT,
      correo TEXT,
      notas TEXT,
      drive_folder_id TEXT,
      password_hash TEXT,
      creado_en TIMESTAMP DEFAULT now()
    );
    """)
    # unique teléfono (idempotente)
    try:
        exec_sql("ALTER TABLE pacientes ADD CONSTRAINT uq_pacientes_telefono UNIQUE (telefono);")
    except Exception:
        pass
    # limpia columna token si existe
    try:
        exec_sql("ALTER TABLE pacientes DROP COLUMN IF EXISTS token;")
    except Exception:
        pass

    # citas
    exec_sql("""
    CREATE TABLE IF NOT EXISTS citas (
      id SERIAL PRIMARY KEY,
      fecha DATE NOT NULL,
      hora TIME NOT NULL,
      paciente_id BIGINT REFERENCES pacientes(id) ON DELETE SET NULL,
      nota TEXT,
      creado_en TIMESTAMP DEFAULT now(),
      UNIQUE (fecha, hora)
    );
    """)
    exec_sql("CREATE INDEX IF NOT EXISTS idx_citas_fecha ON citas(fecha);")

    # mediciones
    exec_sql("""
    CREATE TABLE IF NOT EXISTS mediciones(
      id BIGSERIAL PRIMARY KEY,
      paciente_id BIGINT NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
      fecha TEXT NOT NULL,
      rutina_pdf TEXT,
      plan_pdf TEXT,
      peso_kg DOUBLE PRECISION,
      grasa_pct DOUBLE PRECISION,
      musculo_pct DOUBLE PRECISION,
      brazo_rest DOUBLE PRECISION,
      brazo_flex DOUBLE PRECISION,
      pecho_rest DOUBLE PRECISION,
      pecho_flex DOUBLE PRECISION,
      cintura_cm DOUBLE PRECISION,
      cadera_cm DOUBLE PRECISION,
      pierna_cm DOUBLE PRECISION,
      pantorrilla_cm DOUBLE PRECISION,
      notas TEXT,
      drive_cita_folder_id TEXT,
      cita_id INTEGER REFERENCES citas(id) ON DELETE SET NULL,
      CONSTRAINT mediciones_unq UNIQUE (paciente_id, fecha)
    );
    """)

    # fotos
    exec_sql("""
    CREATE TABLE IF NOT EXISTS fotos(
      id BIGSERIAL PRIMARY KEY,
      paciente_id BIGINT NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
      fecha TEXT NOT NULL,
      drive_file_id TEXT,
      web_view_link TEXT,
      filename TEXT
    );
    """)

def setup_db_safe():
    try:
        setup_db()
    except Exception:
        # fuerza reconexión y reintenta una vez
        try:
            st.cache_resource.clear()
        except Exception:
            pass
        setup_db()


# --------- AUTH ---------
def is_admin_ok(user: str, password: str) -> bool:
    return bool(ADMIN_USER) and bool(ADMIN_PASSWORD) and (user == ADMIN_USER) and (password == ADMIN_PASSWORD)

def normalize_tel(t: str) -> str:
    return re.sub(r'[-\s]+', '', (t or '').strip().lower())

def _peppered(pw: str) -> bytes:
    return (pw.encode() + PEPPER) if PEPPER else pw.encode()

def hash_password(pw: str) -> str:
    return bcrypt.hashpw(_peppered(pw), bcrypt.gensalt()).decode()

# --- Alta por Carmen (con opcionales) ---
def registrar_paciente_admin(
    nombre: str,
    telefono: str,
    password_6d: str,
    fecha_nac: str | None = None,
    correo: str | None = None,
) -> int:
    """
    Registra paciente con contraseña definida por Carmen (6 dígitos) y opcionales fecha_nac/correo.
    - Valida contraseña 6 dígitos.
    - Crea carpeta en Drive y la enlaza.
    - Devuelve el id del paciente.
    """
    if not re.fullmatch(r"\d{6}", str(password_6d or "").strip()):
        raise ValueError("La contraseña debe ser exactamente 6 dígitos.")

    tel = normalize_tel(telefono)
    pw_hash = hash_password(password_6d)

    with conn().cursor() as cur:
        cur.execute(
            """
            INSERT INTO pacientes (nombre, telefono, password_hash, fecha_nac, correo)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (telefono) DO NOTHING
            RETURNING id
            """,
            (nombre.strip(), tel, pw_hash, (fecha_nac or None), (correo or None)),
        )
        row = cur.fetchone()

    if not row:
        # Teléfono ya existe → obtenemos id
        d = df_sql("SELECT id FROM pacientes WHERE telefono=%s LIMIT 1", (tel,))
        if d.empty:
            raise RuntimeError("No se pudo registrar ni encontrar el paciente.")
        pid = int(d.iloc[0]["id"])
    else:
        pid = int(row[0])

    # Asegurar carpeta de Drive (idempotente)
    try:
        folder_id = ensure_patient_folder(nombre.strip(), pid)
        exec_sql("UPDATE pacientes SET drive_folder_id=%s WHERE id=%s", (folder_id, pid))
    except Exception as e:
        st.warning(f"[Drive] No se pudo crear la carpeta del paciente: {e}")

    try:
        st.cache_data.clear()
    except Exception:
        pass

    return pid

def cambiar_password_paciente(paciente_id: int, pw_actual: str, pw_nueva6: str) -> None:
    """
    Cambia la contraseña de un paciente verificando la actual.
    La nueva debe ser 6 dígitos.
    """
    if not re.fullmatch(r"\d{6}", str(pw_nueva6 or "")):
        raise ValueError("La nueva contraseña debe ser exactamente 6 dígitos.")

    d = df_sql("SELECT password_hash FROM pacientes WHERE id=%s LIMIT 1", (paciente_id,))
    if d.empty:
        raise ValueError("Paciente no encontrado.")

    pw_hash = d.iloc[0].get("password_hash")
    # Si no tenía password previa, también pedimos la 'actual' por seguridad mínima
    if not pw_hash or not check_password(pw_actual or "", str(pw_hash)):
        raise ValueError("La contraseña actual no es válida.")

    exec_sql("UPDATE pacientes SET password_hash=%s WHERE id=%s", (hash_password(pw_nueva6), paciente_id))
    try: st.cache_data.clear()
    except: pass


def check_password(pw: str, pw_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_peppered(pw), (pw_hash or "").encode())
    except Exception:
        return False

def registrar_paciente(nombre: str, telefono: str, password: str) -> int:
    tel = normalize_tel(telefono)
    pw_hash = hash_password(password)
    with conn().cursor() as cur:
        cur.execute(
            "INSERT INTO pacientes (nombre, telefono, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (nombre.strip(), tel, pw_hash),
        )
        pid = int(cur.fetchone()[0])
    # carpeta de Drive al registro
    try:
        folder_id = ensure_patient_folder(nombre.strip(), pid)
        exec_sql("UPDATE pacientes SET drive_folder_id=%s WHERE id=%s", (folder_id, pid))
    except Exception as e:
        st.warning(f"[Drive] No se pudo crear la carpeta del paciente (puedes reintentar desde Admin): {e}")
    try: st.cache_data.clear()
    except: pass
    return pid

def login_paciente(telefono: str, password: str) -> Optional[dict]:
    tel = normalize_tel(telefono)
    d = df_sql("SELECT id, nombre, telefono, password_hash FROM pacientes WHERE telefono=%s LIMIT 1", (tel,))
    if d.empty: return None
    r = d.iloc[0]
    if r.get("password_hash") and check_password(password, str(r["password_hash"])):
        return {"id": int(r["id"]), "nombre": r["nombre"], "telefono": r["telefono"]}
    return None

# --------- DRIVE HELPERS ---------
@st.cache_resource
def get_drive():
    # 1) OAuth (si configuras google_oauth en secrets)
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

def delete_paciente(pid: int, remove_drive_folder: bool = True, send_to_trash: bool = True) -> bool:
    """
    Elimina definitivamente al paciente `pid`.
    - Borra en cascada mediciones y fotos (por FK).
    - Deja las citas con paciente_id = NULL (por FK).
    - Opcionalmente manda a papelera (o borra) la carpeta de Drive del paciente.
    """
    try:
        # 1) Traer datos del paciente (para carpeta)
        d = df_sql("SELECT nombre, drive_folder_id FROM pacientes WHERE id=%s LIMIT 1", (pid,))
        if d.empty:
            return False

        folder_id = (d.loc[0, "drive_folder_id"] or "").strip()

        # 2) Eliminar carpeta de Drive (opcional)
        if remove_drive_folder and folder_id:
            try:
                drv = get_drive()
                if send_to_trash:
                    drv.files().update(
                        fileId=folder_id,
                        body={"trashed": True},
                        supportsAllDrives=True
                    ).execute()
                else:
                    drv.files().delete(fileId=folder_id, supportsAllDrives=True).execute()
            except Exception as e:
                # No bloquea el borrado en DB si falla Drive
                st.info(f"[Drive] No se pudo eliminar/trash la carpeta del paciente: {e}")

        # 3) Eliminar paciente (cascade hará el resto)
        exec_sql("DELETE FROM pacientes WHERE id=%s", (pid,))

        try:
            st.cache_data.clear()
        except Exception:
            pass
        return True
    except Exception as e:
        st.error(f"No se pudo eliminar el paciente: {e}")
        return False

def _slug(s: str) -> str:
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^\w\s.-]', '', s, flags=re.UNICODE).strip().lower()
    s = re.sub(r'\s+', '_', s); s = re.sub(r'_+', '_', s)
    return s.strip('_')

def _escape_for_q(s: str) -> str:
    # Escapa comillas simples para la query de Drive
    return s.replace("'", "\\'")

def _purge_drive_files_with_prefix(parent_id: str, name_prefix: str) -> int:
    """Mueve a papelera todos los archivos en `parent_id` cuyo nombre empiece con `name_prefix`."""
    try:
        drv = get_drive()
        safe = name_prefix.replace("'", "\\'")
        q = f"'{parent_id}' in parents and trashed=false and name contains '{safe}'"
        resp = drv.files().list(
            q=q, fields="files(id,name)", pageSize=1000,
            supportsAllDrives=True, includeItemsFromAllDrives=True
        ).execute()
        n = 0
        for f in resp.get("files", []):
            if f.get("name","").startswith(name_prefix):
                drv.files().update(
                    fileId=f["id"], body={"trashed": True},
                    supportsAllDrives=True
                ).execute()
                n += 1
        return n
    except Exception:
        return 0

def upload_pdf_named(pid: int, fecha_str: str, kind: str, file_bytes: bytes) -> dict:
    kind = _slug(kind or "pdf")
    folder_id = ensure_cita_folder(pid, fecha_str)
    target = f"{fecha_str}_{kind}.pdf"
    _purge_drive_files_with_prefix(folder_id, f"{fecha_str}_{kind}")
    return upload_pdf_to_folder(file_bytes, target, folder_id)

def upload_image_named(pid: int, fecha_str: str, base_name: str, file_bytes: bytes, mime: str) -> dict:
    """
    Sube imagen con nombre `YYYY-MM-DD_slug.ext` (conserva extensión).
    No purga; permite múltiples fotos por fecha.
    """
    folder_id = ensure_cita_folder(pid, fecha_str)
    slug = _slug(Path(base_name).stem or "foto")
    ext = Path(base_name).suffix.lower() or ".jpg"
    target = f"{fecha_str}_{slug}{ext}"
    return upload_image_to_folder(file_bytes, target, folder_id, mime)

def _escape_for_q(s: str) -> str:
    return s.replace("'", "\\'")


def _siguiente_indice_foto(parent_id: str, fecha_prefix: str) -> int:
    """
    Busca el siguiente índice disponible para nombres tipo `YYYY-MM-DD_foto_XX.ext`.
    """
    drv = get_drive()
    safe = fecha_prefix.replace("'", "\\'")
    q = f"'{parent_id}' in parents and trashed=false and name contains '{safe}_foto_'"
    resp = drv.files().list(
        q=q, fields="files(name)", pageSize=1000,
        supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute()
    max_idx = 0
    for f in resp.get("files", []):
        name = f.get("name","")
        # buscar patrón ..._foto_XX
        m = re.search(r"_foto_(\d+)", name)
        if m:
            max_idx = max(max_idx, int(m.group(1)))
    return max_idx + 1



def ensure_patient_folder(nombre: str, pid: int) -> str:
    drive = get_drive()
    folder_name = f"{pid:05d} - {nombre}"
    escaped = folder_name.replace("'", "\\'")
    q = ("mimeType='application/vnd.google-apps.folder' and trashed=false "
         f"and name='{escaped}' " + (f"and '{ROOT_FOLDER_ID}' in parents" if ROOT_FOLDER_ID else ""))
    res = drive.files().list(
        q=q, fields="files(id)", pageSize=1,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    f = res.get("files", [])
    if f: return f[0]["id"]
    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if ROOT_FOLDER_ID: meta["parents"] = [ROOT_FOLDER_ID]
    folder = drive.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
    return folder["id"]

def ensure_cita_folder(pid: int, fecha_str: str) -> str:
    # si ya está guardada la carpeta
    m = df_sql("SELECT drive_cita_folder_id FROM mediciones WHERE paciente_id=%s AND fecha=%s", (pid, fecha_str))
    if not m.empty and (m.loc[0, "drive_cita_folder_id"] or "").strip():
        return m.loc[0, "drive_cita_folder_id"].strip()

    # asegurar carpeta de paciente
    d = df_sql("SELECT nombre, drive_folder_id FROM pacientes WHERE id=%s", (pid,))
    if d.empty:
        raise RuntimeError("Paciente no existe.")
    patient_folder_id = (d.loc[0, "drive_folder_id"] or "").strip()
    if not patient_folder_id:
        folder_id = ensure_patient_folder(d.loc[0, "nombre"].strip(), pid)
        exec_sql("UPDATE pacientes SET drive_folder_id=%s WHERE id=%s", (folder_id, pid))
        patient_folder_id = folder_id

    drive = get_drive()
    q = ("mimeType='application/vnd.google-apps.folder' and trashed=false "
         f"and name='{fecha_str}' and '{patient_folder_id}' in parents")
    res = drive.files().list(
        q=q, fields="files(id)", pageSize=1,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files", [])
    if files:
        cita_folder_id = files[0]["id"]
    else:
        meta = {"name": fecha_str, "mimeType": "application/vnd.google-apps.folder", "parents": [patient_folder_id]}
        cita_folder_id = drive.files().create(body=meta, fields="id", supportsAllDrives=True).execute()["id"]

    exec_sql("""
        INSERT INTO mediciones (paciente_id, fecha, drive_cita_folder_id)
        VALUES (%s,%s,%s)
        ON CONFLICT (paciente_id, fecha)
        DO UPDATE SET drive_cita_folder_id = EXCLUDED.drive_cita_folder_id
    """, (pid, fecha_str, cita_folder_id))
    return cita_folder_id

def upload_pdf_to_folder(file_bytes: bytes, filename: str, folder_id: str) -> dict:
    drive = get_drive()
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="application/pdf", resumable=False)
    meta = {"name": filename, "parents": [folder_id]}
    f = drive.files().create(body=meta, media_body=media, fields="id,webViewLink", supportsAllDrives=True).execute()
    make_anyone_reader(f["id"])
    return f

def upload_image_to_folder(file_bytes: bytes, filename: str, folder_id: str, mime: str) -> dict:
    drive = get_drive()
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime, resumable=False)
    meta = {"name": filename, "parents": [folder_id]}
    f = drive.files().create(body=meta, media_body=media, fields="id,webViewLink,thumbnailLink", supportsAllDrives=True).execute()
    make_anyone_reader(f["id"])
    return f

def to_drive_preview(url: str) -> str:
    if not url: return ""
    u = url.strip()
    if "drive.google.com" in u:
        if "/view" in u: u = u.replace("/view", "/preview")
        elif not u.endswith("/preview"): u = u.rstrip("/") + "/preview"
    return u

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

    # PDFs en raíz
    all_pdfs = _list_pdfs_in(patient_folder_id)
    # PDFs en subcarpetas (fechas)
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

    # Mantener últimos 'keep'
    if len(all_pdfs) > keep:
        excess = len(all_pdfs) - keep
        all_pdfs.sort(key=lambda x: x.get("createdTime", ""))
        to_remove = all_pdfs[:excess]
        for f in to_remove:
            try:
                if send_to_trash:
                    drive.files().update(fileId=f["id"], body={"trashed": True}, supportsAllDrives=True).execute()
                else:
                    drive.files().delete(fileId=f["id"], supportsAllDrives=True).execute()
            except Exception as e:
                st.info(f"[Drive] No se pudo depurar PDF {f.get('name')}: {e}")

def delete_drive_file(file_id: str, send_to_trash: bool = True) -> bool:
    try:
        drv = get_drive()
        if send_to_trash:
            drv.files().update(fileId=file_id, body={"trashed": True}, supportsAllDrives=True).execute()
        else:
            drv.files().delete(fileId=file_id, supportsAllDrives=True).execute()
        return True
    except Exception as e:
        st.info(f"[Drive] No se pudo eliminar el archivo {file_id}: {e}")
        return False

def delete_foto(photo_id: int, send_to_trash: bool = True) -> bool:
    fila = df_sql("SELECT drive_file_id FROM fotos WHERE id = %s", (photo_id,))
    if fila.empty:
        st.warning("No se encontró la foto en la base.")
        return False
    drive_id = (fila.loc[0, "drive_file_id"] or "").strip()
    if drive_id:
        delete_drive_file(drive_id, send_to_trash=send_to_trash)
    exec_sql("DELETE FROM fotos WHERE id = %s", (photo_id,))
    try: st.cache_data.clear()
    except: pass
    return True

# --------- AGENDA / CITAS ---------
# Paciente NO puede agendar hoy ni mañana (a partir del día 3)
BLOQUEO_DIAS_MIN: int = 2

def is_fecha_permitida(fecha: date) -> bool:
    return fecha >= (date.today() + timedelta(days=BLOQUEO_DIAS_MIN))

def _bloques_del_dia(fecha: date) -> list[tuple[time, time]]:
    wd = fecha.weekday()  # 0=lun ... 6=dom
    if 0 <= wd <= 4:
        return [(time(10,0), time(12,0)), (time(14,0), time(16,30)), (time(18,30), time(19,0))]
    elif wd == 5:
        return [(time(8,0), time(14,0))]
    else:
        return []

def generar_slots(fecha: date) -> list[time]:
    slots: list[time] = []
    delta = timedelta(minutes=PASO_MIN)
    for ini, fin in _bloques_del_dia(fecha):
        t = datetime.combine(fecha, ini); tfin = datetime.combine(fecha, fin)
        while t < tfin:
            slots.append(t.time()); t += delta
    return slots

def is_fecha_permitida(fecha: date) -> bool:
    return fecha >= (date.today() + timedelta(days=BLOQUEO_DIAS_MIN))

@st.cache_data(ttl=5, show_spinner=False)
def slots_ocupados(fecha: date) -> set:
    d = df_sql("SELECT hora FROM citas WHERE fecha=%s ORDER BY hora", (fecha,))
    return set(d["hora"].tolist()) if not d.empty else set()

def crear_o_encontrar_paciente(nombre: str, telefono: str) -> int:
    tel = normalize_tel(telefono)
    d = df_sql("SELECT id FROM pacientes WHERE telefono = %s LIMIT 1", (tel,))
    if not d.empty: return int(d.iloc[0]["id"])
    with conn().cursor() as cur:
        cur.execute("INSERT INTO pacientes(nombre, telefono) VALUES (%s, %s) RETURNING id", (nombre.strip(), tel))
        new_id = int(cur.fetchone()[0])
    try: st.cache_data.clear()
    except: pass
    return new_id

def ya_tiene_cita_en_dia(paciente_id: int, fecha: date) -> bool:
    d = df_sql("SELECT 1 FROM citas WHERE paciente_id=%s AND fecha=%s LIMIT 1", (paciente_id, fecha))
    return not d.empty

def ya_tiene_cita_en_ventana_7dias(paciente_id: int, fecha_ref: date) -> bool:
    d = df_sql("""
        SELECT 1 FROM citas
        WHERE paciente_id=%s
          AND fecha BETWEEN (%s::date - INTERVAL '6 days') AND (%s::date + INTERVAL '6 days')
        LIMIT 1
    """, (paciente_id, fecha_ref, fecha_ref))
    return not d.empty

def agendar_cita_autenticado(fecha: date, hora: time, paciente_id: int, nota: Optional[str] = None):
    # Bloqueo duro: hoy y mañana no se puede (mínimo día 3)
    if not is_fecha_permitida(fecha):
        raise ValueError("La fecha seleccionada no está permitida. Debe ser a partir del tercer día.")

    if ya_tiene_cita_en_dia(paciente_id, fecha):
        raise ValueError("Ya tienes una cita ese día. Solo se permite una por día.")

    if ya_tiene_cita_en_ventana_7dias(paciente_id, fecha):
        raise ValueError("Solo se permite una cita cada 7 días (respecto a la fecha elegida).")

    try:
        exec_sql(
            "INSERT INTO citas(fecha, hora, paciente_id, nota) VALUES (%s, %s, %s, %s)",
            (fecha, hora, paciente_id, nota)
        )
    except pg_errors.UniqueViolation:
        raise ValueError("Ese horario ya fue tomado. Elige otro.")


def citas_por_dia(fecha: date):
    return df_sql("""
        SELECT c.id AS id_cita, c.fecha, c.hora, p.id AS paciente_id, p.nombre, p.telefono, c.nota
        FROM citas c LEFT JOIN pacientes p ON p.id = c.paciente_id
        WHERE c.fecha = %s ORDER BY c.hora
    """, (fecha,))

def actualizar_cita(cita_id: int, nombre: str, telefono: str, nota: Optional[str]):
    pid = crear_o_encontrar_paciente(nombre.strip(), telefono.strip())
    exec_sql("UPDATE citas SET paciente_id=%s, nota=%s WHERE id=%s", (pid, nota, cita_id))

def eliminar_cita(cita_id: int) -> int:
    with conn().cursor() as cur:
        cur.execute("DELETE FROM citas WHERE id=%s", (cita_id,)); n = cur.rowcount or 0
    try: st.cache_data.clear()
    except: pass
    return n

# --------- MEDICIONES / PDFs / FOTOS ---------
def upsert_medicion(pid: int, fecha: str, rutina_pdf: str | None, plan_pdf: str | None):
    exec_sql(
        """
        INSERT INTO mediciones (paciente_id, fecha, rutina_pdf, plan_pdf)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (paciente_id, fecha)
        DO UPDATE SET
          rutina_pdf = COALESCE(EXCLUDED.rutina_pdf, mediciones.rutina_pdf),
          plan_pdf   = COALESCE(EXCLUDED.plan_pdf,   mediciones.plan_pdf)
        """,
        (pid, fecha, rutina_pdf, plan_pdf),
    )

def asociar_medicion_a_cita(pid: int, fecha_str: str):
    d = df_sql("SELECT id FROM citas WHERE paciente_id=%s AND fecha=%s ORDER BY hora ASC LIMIT 1", (pid, fecha_str))
    if not d.empty:
        cid = int(d.loc[0, "id"])
        exec_sql("UPDATE mediciones SET cita_id=%s WHERE paciente_id=%s AND fecha=%s", (cid, pid, fecha_str))

def delete_medicion_dia(
    pid: int,
    fecha_str: str,
    remove_drive_folder: bool = True,
    send_to_trash: bool = True,
    delete_cita_row: bool = False,
) -> None:
    m = df_sql("SELECT drive_cita_folder_id FROM mediciones WHERE paciente_id=%s AND fecha=%s", (pid, fecha_str))
    cita_folder_id = (m.loc[0, "drive_cita_folder_id"].strip()
                      if not m.empty and (m.loc[0, "drive_cita_folder_id"] or "").strip()
                      else None)
    fotos = df_sql("SELECT id, drive_file_id FROM fotos WHERE paciente_id=%s AND fecha=%s", (pid, fecha_str))
    for _, r in fotos.iterrows():
        if r.get("drive_file_id"):
            delete_drive_file(str(r["drive_file_id"]), send_to_trash=send_to_trash)
        exec_sql("DELETE FROM fotos WHERE id=%s", (int(r["id"]),))
    exec_sql("DELETE FROM mediciones WHERE paciente_id=%s AND fecha=%s", (pid, fecha_str))
    if remove_drive_folder and cita_folder_id:
        try:
            drv = get_drive()
            if send_to_trash:
                drv.files().update(fileId=cita_folder_id, body={"trashed": True}, supportsAllDrives=True).execute()
            else:
                drv.files().delete(fileId=cita_folder_id, supportsAllDrives=True).execute()
        except Exception as e:
            st.info(f"[Drive] No se pudo eliminar la carpeta de la cita ({cita_folder_id}): {e}")
    if delete_cita_row:
        try:
            exec_sql("DELETE FROM citas WHERE paciente_id=%s AND fecha=%s", (pid, fecha_str))
        except Exception:
            pass
    try: st.cache_data.clear()
    except: pass

# ========== WHATSAPP / RECORDATORIOS ==========

def citas_manana():
    """Citas de mañana (fecha = hoy + 1) con datos de paciente."""
    return df_sql(
        """
        SELECT c.id AS id_cita, c.fecha, c.hora, c.nota,
               p.id AS paciente_id, p.nombre, p.telefono
        FROM citas c
        JOIN pacientes p ON p.id = c.paciente_id
        WHERE c.fecha = CURRENT_DATE + INTERVAL '1 day'
        ORDER BY c.hora
        """
    )

def _fmt_fecha_es(v) -> str:
    try: return pd.to_datetime(v).strftime("%d/%m/%Y")
    except Exception: return str(v)

def _fmt_hora_es(v) -> str:
    try: return pd.to_datetime(str(v)).strftime("%H:%M")
    except Exception: return str(v)

def _to_e164_mx(tel: str) -> str | None:
    """Normaliza teléfonos a E.164 (+52XXXXXXXXXX si recibe 10 dígitos de MX)."""
    if not tel: return None
    t = re.sub(r"\D+", "", str(tel))
    if not t: return None
    if str(tel).startswith("+"):
        return str(tel)
    if t.startswith("52"):
        return f"+{t}"
    if len(t) == 10:
        return f"+52{t}"
    return None

def _wa_send_meta(to_e164: str, nombre: str, fecha_txt: str, hora_txt: str):
    """Envía mensaje por plantilla (WhatsApp Cloud API / Meta)."""
    cfg = st.secrets["whatsapp"]
    url = f"https://graph.facebook.com/v19.0/{cfg['PHONE_NUMBER_ID']}/messages"
    headers = {
        "Authorization": f"Bearer {cfg['TOKEN']}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_e164,
        "type": "template",
        "template": {
            "name": cfg["TEMPLATE"],
            "language": {"code": cfg.get("LANG", "es_MX")},
            "components": [
                {"type": "body", "parameters": [
                    {"type": "text", "text": nombre or "Paciente"},
                    {"type": "text", "text": fecha_txt},
                    {"type": "text", "text": hora_txt},
                ]}
            ],
        },
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()

def enviar_recordatorios_manana(dry_run: bool = False) -> dict:
    """
    Envía (o simula) recordatorios de WhatsApp para TODAS las citas de mañana.
    Devuelve resumen {"total", "enviados", "fallidos", "detalles":[...]}.
    """
    df = citas_manana()
    res = {"total": int(len(df)), "enviados": 0, "fallidos": 0, "detalles": []}
    if df.empty:
        return res

    for _, r in df.iterrows():
        nombre = (r.get("nombre") or "").strip()
        tel_raw = (r.get("telefono") or "").strip()
        to = _to_e164_mx(tel_raw)
        fecha_txt = _fmt_fecha_es(r["fecha"])
        hora_txt  = _fmt_hora_es(r["hora"])

        item = {
            "id_cita": int(r["id_cita"]),
            "nombre": nombre,
            "telefono": tel_raw,
            "to_e164": to or "",
            "fecha": fecha_txt,
            "hora": hora_txt,
            "ok": False,
            "error": "",
        }

        if not to:
            item["error"] = "Teléfono inválido/no E.164"
            res["fallidos"] += 1
            res["detalles"].append(item)
            continue

        try:
            if not dry_run:
                _wa_send_meta(to, nombre, fecha_txt, hora_txt)
            item["ok"] = True
            res["enviados"] += 1
        except Exception as e:
            item["error"] = str(e)
            res["fallidos"] += 1

        res["detalles"].append(item)

    return res

