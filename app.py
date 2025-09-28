# =========================
# app.py (unificado) — Carmen Coach
# =========================
import os, io, re, uuid, hashlib, traceback
from typing import Optional
from pathlib import Path
from datetime import date, datetime, timedelta, time

import pandas as pd
import psycopg
import streamlit as st
from psycopg import errors as pg_errors  # UniqueViolation, etc.

# Google Drive (usa Service Account o OAuth; se configuran en st.secrets)
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError

import bcrypt

st.set_page_config(page_title="Carmen Coach — Agenda & Pacientes", page_icon="🩺", layout="wide")

# Ajustes de agenda (slots)
PASO_MIN: int = 30
BLOQUEO_DIAS_MIN: int = 2  # hoy y mañana bloqueados (paciente agenda desde el día 3)

# Secrets / env
NEON_URL = st.secrets.get("NEON_DATABASE_URL") or os.getenv("NEON_DATABASE_URL")
PEPPER = (st.secrets.get("PASSWORD_PEPPER") or os.getenv("PASSWORD_PEPPER") or "").encode()

# Admin (elige uno de los dos esquemas)
ADMIN_USER = os.getenv("CARMEN_USER") or st.secrets.get("CARMEN_USER", "carmen")
ADMIN_PASSWORD = os.getenv("CARMEN_PASSWORD") or st.secrets.get("CARMEN_PASSWORD")  # texto plano
# Alternativa hash simple (si no usas CARMEN_PASSWORD):
def sha256(x: str) -> str: return hashlib.sha256(x.encode()).hexdigest()
ADMIN_PASSWORD_HASH = st.secrets.get("ADMIN_PASSWORD_HASH")  # opcional

# Google Drive
SCOPES = ["https://www.googleapis.com/auth/drive"]
ROOT_FOLDER_ID = st.secrets.get("DRIVE_ROOT_FOLDER_ID")  # opcional

# =========================
# Conexión a Neon / Postgres
# =========================
@st.cache_resource
def conn():
    if not NEON_URL:
        st.error("Falta configurar NEON_DATABASE_URL en Secrets.")
        st.stop()
    return psycopg.connect(NEON_URL, autocommit=True)

def exec_sql(q_ps: str, p: tuple = ()):
    with conn().cursor() as cur:
        cur.execute(q_ps, p)

def df_sql(q_ps: str, p: tuple = ()):
    return pd.read_sql_query(q_ps, conn(), params=p)

# =========================
# Migración mínima (unifica modelos)
# =========================
def setup_db():
    # Tablas base
    exec_sql("""
    CREATE TABLE IF NOT EXISTS pacientes (
      id BIGSERIAL PRIMARY KEY,
      nombre TEXT NOT NULL,
      fecha_nac TEXT,
      telefono TEXT,
      correo TEXT,
      notas TEXT,
      token TEXT UNIQUE,
      drive_folder_id TEXT,
      password_hash TEXT,
      creado_en TIMESTAMP DEFAULT now()
    );
    """)
    # índice/unique de teléfono
    try:
        exec_sql("ALTER TABLE pacientes ADD CONSTRAINT uq_pacientes_telefono UNIQUE (telefono);")
    except Exception:
        pass

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

setup_db()

# =========================
# Utils comunes
# =========================
def normalize_tel(t: str) -> str:
    return re.sub(r'[-\s]+', '', (t or '').strip().lower())

def _peppered(pw: str) -> bytes:
    return (pw.encode() + PEPPER) if PEPPER else pw.encode()

def hash_password(pw: str) -> str:
    return bcrypt.hashpw(_peppered(pw), bcrypt.gensalt()).decode()

def check_password(pw: str, pw_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_peppered(pw), (pw_hash or "").encode())
    except Exception:
        return False

def get_or_create_token(pid: int):
    d = df_sql("SELECT token FROM pacientes WHERE id = %s", (pid,))
    if d.empty:
        return None
    tok = d.loc[0, "token"]
    if not tok:
        tok = uuid.uuid4().hex[:8]
        exec_sql("UPDATE pacientes SET token=%s WHERE id=%s", (tok, pid))
    return tok

def registrar_paciente(nombre: str, telefono: str, password: str) -> int:
    tel = normalize_tel(telefono)
    pw_hash = hash_password(password)
    with conn().cursor() as cur:
        cur.execute(
            "INSERT INTO pacientes (nombre, telefono, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (nombre.strip(), tel, pw_hash),
        )
        pid = int(cur.fetchone()[0])
    try:
        st.cache_data.clear()
    except:
        pass
    return pid

def login_paciente(telefono: str, password: str) -> Optional[dict]:
    tel = normalize_tel(telefono)
    d = df_sql("SELECT id, nombre, telefono, password_hash FROM pacientes WHERE telefono=%s LIMIT 1", (tel,))
    if d.empty:
        return None
    r = d.iloc[0]
    if r.get("password_hash") and check_password(password, str(r["password_hash"])):
        return {"id": int(r["id"]), "nombre": r["nombre"], "telefono": r["telefono"]}
    return None

# ===== Admin simple con secrets =====
ADMIN_USER = os.getenv("CARMEN_USER") or st.secrets.get("CARMEN_USER", "carmen")
ADMIN_PASSWORD = os.getenv("CARMEN_PASSWORD") or st.secrets.get("CARMEN_PASSWORD")

def is_admin_ok(user: str, password: str) -> bool:
    return bool(ADMIN_USER) and bool(ADMIN_PASSWORD) and (user == ADMIN_USER) and (password == ADMIN_PASSWORD)


# =========================
# Google Drive helpers
# =========================
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
    q = "trashed=false and " + f"'{parent_id}' in parents and " + f"name contains '{safe_base}'"
    res = drive.files().list(
        q=q, fields="files(name)", pageSize=100,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    existing = {f["name"] for f in res.get("files", [])}
    if name not in existing: return name
    i = 2
    while True:
        cand = f"{base}-{i}{ext}"
        if cand not in existing: return cand
        i += 1

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
    d = df_sql("SELECT drive_folder_id FROM pacientes WHERE id=%s", (pid,))
    if d.empty or not (d.loc[0, "drive_folder_id"] or "").strip():
        raise RuntimeError("El paciente no tiene carpeta de Drive asignada.")
    patient_folder_id = d.loc[0, "drive_folder_id"].strip()

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
    make_anyone_reader(f["id"]); return f

def upload_image_to_folder(file_bytes: bytes, filename: str, folder_id: str, mime: str) -> dict:
    drive = get_drive()
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime, resumable=False)
    meta = {"name": filename, "parents": [folder_id]}
    f = drive.files().create(body=meta, media_body=media, fields="id,webViewLink,thumbnailLink", supportsAllDrives=True).execute()
    make_anyone_reader(f["id"]); return f

def to_drive_preview(url: str) -> str:
    if not url: return ""
    u = url.strip()
    if "drive.google.com" in u:
        if "/view" in u: u = u.replace("/view", "/preview")
        elif not u.endswith("/preview"): u = u.rstrip("/") + "/preview"
    return u

# =========================
# Dominio: Agenda / Reglas / Asociación
# =========================
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
    assert is_fecha_permitida(fecha), "La fecha seleccionada no está permitida (mínimo día 3)."
    if ya_tiene_cita_en_dia(paciente_id, fecha):
        raise ValueError("Ya tienes una cita ese día. Solo se permite una por día.")
    if ya_tiene_cita_en_ventana_7dias(paciente_id, fecha):
        raise ValueError("Solo se permite una cita cada 7 días (respecto a la fecha elegida).")
    try:
        exec_sql("INSERT INTO citas(fecha, hora, paciente_id, nota) VALUES (%s, %s, %s, %s)",
                 (fecha, hora, paciente_id, nota))
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

def upsert_medicion(pid: int, fecha_str: str, rutina_pdf: str | None = None, plan_pdf: str | None = None):
    exec_sql("""
        INSERT INTO mediciones (paciente_id, fecha, rutina_pdf, plan_pdf)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (paciente_id, fecha)
        DO UPDATE SET rutina_pdf = EXCLUDED.rutina_pdf, plan_pdf = EXCLUDED.plan_pdf
    """, (pid, fecha_str, rutina_pdf, plan_pdf))

def asociar_medicion_a_cita(pid: int, fecha_str: str):
    d = df_sql("SELECT id FROM citas WHERE paciente_id=%s AND fecha=%s ORDER BY hora ASC LIMIT 1", (pid, fecha_str))
    if not d.empty:
        cid = int(d.loc[0, "id"])
        exec_sql("UPDATE mediciones SET cita_id=%s WHERE paciente_id=%s AND fecha=%s", (cid, pid, fecha_str))

# =========================
# Sidebar: Accesos y Navegación
# =========================
with st.sidebar:
    st.markdown("## Acceso")
    tabs = st.tabs(["👩‍⚕️ Admin", "🧑 Paciente (Agenda)", "🧑 Paciente (Portal RO)"])

    # --- Admin ---
    with tabs[0]:
        a_user = st.text_input("Usuario", value=ADMIN_USER, disabled=True, key="admin_user_input")
        a_pass = st.text_input("Contraseña", type="password", key="admin_pass_input")
        if st.button("Entrar como Admin", use_container_width=True, key="admin_login_btn"):
            if is_admin_ok(a_user, a_pass):
                st.session_state.role = "admin"
                st.session_state.paciente = None
                st.success("Acceso admin concedido ✅")
                st.rerun()
            else:
                st.error("Credenciales inválidas")

    # --- Paciente (Agenda): Login / Registro ---
    with tabs[1]:
        modo = st.radio("¿Tienes cuenta?", ["Iniciar sesión", "Registrarme"], horizontal=True, key="agenda_modo")

        if modo == "Iniciar sesión":
            p_tel = st.text_input("Teléfono", key="agenda_tel_input_login")
            p_pw  = st.text_input("Contraseña", type="password", key="agenda_pass_input_login")
            if st.button("Entrar (Agenda)", use_container_width=True, key="agenda_login_btn"):
                user = login_paciente(p_tel, p_pw)
                if user:
                    st.session_state.role = "paciente_agenda"
                    st.session_state.paciente = user  # dict con id, nombre, telefono
                    st.success(f"Bienvenid@, {user['nombre']} ✅")
                    st.rerun()
                else:
                    st.error("Teléfono o contraseña incorrectos.")

        else:  # Registrarme
            nombre = st.text_input("Nombre completo", key="agenda_nombre_reg")
            p_tel_reg = st.text_input("Teléfono", key="agenda_tel_reg")
            pw1 = st.text_input("Contraseña", type="password", key="agenda_pw1")
            pw2 = st.text_input("Repite tu contraseña", type="password", key="agenda_pw2")

            if st.button("Registrarme", use_container_width=True, key="agenda_reg_btn"):
                if not (nombre.strip() and p_tel_reg.strip() and pw1 and pw2):
                    st.error("Todos los campos son obligatorios.")
                elif pw1 != pw2:
                    st.error("Las contraseñas no coinciden.")
                else:
                    try:
                        pid = registrar_paciente(nombre, p_tel_reg, pw1)
                        # Autologin
                        st.session_state.role = "paciente_agenda"
                        st.session_state.paciente = {
                            "id": int(pid),
                            "nombre": nombre.strip(),
                            "telefono": normalize_tel(p_tel_reg),
                        }
                        st.success("Cuenta creada ✅. ¡Bienvenid@!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo crear la cuenta: {e}")

    # --- Paciente (Portal RO por token) ---
    with tabs[2]:
        token_from_url = st.query_params.get("token", [None])[0] if hasattr(st, "query_params") else None
        p_token = st.text_input("Token (o ?token=...)", value=token_from_url or "", key="portal_token_input")
        if st.button("Entrar (Solo lectura)", use_container_width=True, key="portal_login_btn"):
            d = df_sql("SELECT * FROM pacientes WHERE token=%s", (p_token.strip(),)) if p_token.strip() else pd.DataFrame()
            if d.empty:
                st.error("Token inválido o vacío")
            else:
                st.session_state.role = "paciente_ro"
                st.session_state.paciente = dict(d.iloc[0])
                st.success(f"Bienvenido, {d.iloc[0]['nombre']} ✅")
                st.rerun()


if "role" not in st.session_state: st.session_state.role = None
if "paciente" not in st.session_state: st.session_state.paciente = None

# =========================
# Vista: 📅 Agenda (Paciente)
# =========================
def view_agenda_paciente():
    st.header("📅 Agenda tu cita")
    p = st.session_state.paciente
    pid, nombre, tel = int(p["id"]), str(p["nombre"]), str(p["telefono"])
    st.success(f"Agendando como: {nombre} — {tel} (ID {pid})")
    if st.button("Cerrar sesión paciente (agenda)"):
        st.session_state.role = None; st.session_state.paciente = None; st.rerun()

    min_day = date.today() + timedelta(days=BLOQUEO_DIAS_MIN)
    fecha = st.date_input("Elige el día (desde el tercer día)", value=min_day, min_value=min_day)

    if not is_fecha_permitida(fecha):
        st.error("Solo puedes agendar a partir del tercer día."); st.stop()

    ocupados = slots_ocupados(fecha)
    libres = [t for t in generar_slots(fecha) if t not in ocupados]
    slot_sel = st.selectbox("Horario disponible", [t.strftime("%H:%M") for t in libres]) if libres else None
    if not libres:
        if fecha.weekday() == 6: st.warning("Domingo no se agenda. Elige L–S.")
        else: st.warning("No hay horarios libres en este día.")
    nota = st.text_area("Motivo o nota (opcional)")
    if st.button("📝 Confirmar cita", disabled=(slot_sel is None)):
        try:
            if slot_sel is None:
                st.error("Selecciona un horario.")
            else:
                h = datetime.strptime(slot_sel, "%H:%M").time()
                agendar_cita_autenticado(fecha, h, paciente_id=pid, nota=nota or None)
                st.success("¡Cita agendada! ✨"); st.balloons()
                try: st.cache_data.clear()
                except: pass
                st.rerun()
        except ValueError as ve:
            st.error(str(ve))
        except pg_errors.UniqueViolation:
            st.error("Ese horario ya fue tomado. Intenta con otro.")
        except Exception as e:
            st.error(f"No se pudo agendar: {e}")

# =========================
# Vista: 🧑‍⚕️ Admin
# =========================
def view_admin():
    st.header("🧑‍⚕️ Panel de Carmen (Admin)")

    # Login persistente básico: si llegaste aquí, ya estás autenticada
    colf, colr = st.columns([1, 2], gap="large")

    with colf:
        fecha_sel = st.date_input("Día", value=date.today(), key="fecha_admin")
        opt_slots = [t.strftime("%H:%M") for t in generar_slots(fecha_sel)]
        slot = st.selectbox("Hora", opt_slots) if opt_slots else None
        nombre = st.text_input("Nombre paciente", key="nombre_admin")
        tel = st.text_input("Teléfono", key="tel_admin")
        nota = st.text_area("Nota (opcional)", key="nota_admin")

        if st.button("➕ Crear cita", key="crear_admin"):
            if not slot: st.error("Selecciona un día con horarios disponibles.")
            elif not (nombre.strip() and tel.strip()): st.error("Nombre y teléfono son obligatorios.")
            else:
                try:
                    pid = crear_o_encontrar_paciente(nombre, tel)
                    exec_sql("INSERT INTO citas(fecha, hora, paciente_id, nota) VALUES (%s,%s,%s,%s)",
                             (fecha_sel, datetime.strptime(slot, "%H:%M").time(), pid, nota or None))
                    # Provisionar carpeta (opcional):
                    try:
                        pfid = df_sql("SELECT drive_folder_id FROM pacientes WHERE id=%s", (pid,))
                        if pfid.empty or not (pfid.loc[0,"drive_folder_id"] or "").strip():
                            folder_id = ensure_patient_folder(nombre.strip(), pid)
                            exec_sql("UPDATE pacientes SET drive_folder_id=%s WHERE id=%s", (folder_id, pid))
                    except Exception as _e:
                        st.info(f"[Drive] No se pudo provisionar carpeta: {_e}")
                    st.success("Cita creada."); st.rerun()
                except Exception as e:
                    st.error(f"No se pudo crear la cita: {e}")

    with colr:
        st.subheader(f"Citas para {fecha_sel.strftime('%d-%m-%Y')}")
        if st.button("🔄 Actualizar lista", key="refresh_admin"):
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
            cid = st.selectbox("ID cita", ids)
            r = df[df.id_cita == cid].iloc[0]
            nombre_e = st.text_input("Nombre", r["nombre"] or "", key="nombre_edit")
            tel_e = st.text_input("Teléfono", r["telefono"] or "", key="tel_edit")
            nota_e = st.text_area("Nota", r["nota"] or "", key="nota_edit")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("💾 Guardar cambios"):
                    if nombre_e.strip() and tel_e.strip():
                        try:
                            actualizar_cita(int(cid), nombre_e, tel_e, nota_e or None)
                            st.success("Actualizado."); st.rerun()
                        except Exception as e:
                            st.error(f"No se pudo actualizar: {e}")
                    else:
                        st.error("Nombre y teléfono son obligatorios.")
            with c2:
                ok_del = st.checkbox("Confirmar eliminación", key=f"confirm_del_{cid}")
                if st.button("🗑️ Eliminar", disabled=not ok_del):
                    try:
                        n = eliminar_cita(int(cid))
                        st.success("Cita eliminada." if n else "La cita ya no existía."); st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo eliminar: {e}")

    # -------------------------
    # Gestión completa (pega aquí tus tabs de la app de gestión)
    # -------------------------
    st.divider()
    st.subheader("📚 Gestión de Pacientes (Perfil, Mediciones, PDFs, Fotos)")

    # === Crear / Buscar / Seleccionar paciente ===
    # Reutiliza exactamente tus bloques: "Nuevo paciente", "Buscar paciente",
    # y los tabs: Perfil, Mediciones, PDFs, Fotos.
    # Puedes copiar/pegar desde tu app de gestión dentro de esta función,
    # adaptando `pid` según el paciente seleccionado.

# =========================
# Vista: 🧑 Paciente (RO)
# =========================
def view_paciente_ro():
    pac = st.session_state.paciente
    st.subheader(f"🧑 Portal del paciente — {pac['nombre']}")
    st.caption("Vista de solo lectura.")

    with st.expander("🧾 Datos del perfil"):
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Nombre:**", pac["nombre"])
            st.write("**Fecha de nacimiento:**", pac.get("fecha_nac") or "—")
            st.write("**Teléfono:**", pac.get("telefono") or "—")
        with c2:
            st.write("**Correo:**", pac.get("correo") or "—")
            st.write("**Notas:**"); st.write(pac.get("notas") or "—")

    st.markdown("### 📂 Tus PDFs de citas")
    citas = df_sql("SELECT fecha, rutina_pdf, plan_pdf FROM mediciones WHERE paciente_id=%s ORDER BY fecha DESC", (int(pac["id"]),))
    if citas.empty:
        st.info("Aún no tienes PDFs registrados.")
    else:
        fecha_sel = st.selectbox("Fecha de la cita", citas["fecha"].tolist())
        actual = citas.loc[citas["fecha"] == fecha_sel].iloc[0]
        r, p = (actual["rutina_pdf"] or "").strip(), (actual["plan_pdf"] or "").strip()
        c1, c2 = st.columns(2)
        with c1: st.link_button("🔗 Abrir Rutina (PDF)", r, disabled=(not bool(r)))
        with c2: st.link_button("🔗 Abrir Plan (PDF)", p, disabled=(not bool(p)))
        with st.expander("👁️ Vista previa (Drive)"):
            if r: st.components.v1.iframe(to_drive_preview(r), height=360)
            if p: st.components.v1.iframe(to_drive_preview(p), height=360)

    st.markdown("### 📏 Tus mediciones")
    hist = df_sql("""
        SELECT fecha,
               peso_kg AS peso_KG, grasa_pct AS grasa, musculo_pct AS musculo,
               brazo_rest AS brazo_rest_CM, brazo_flex AS brazo_flex_CM,
               pecho_rest AS pecho_rest_CM, pecho_flex AS pecho_flex_CM,
               cintura_cm AS cintura_CM, cadera_cm AS cadera_CM,
               pierna_cm AS pierna_CM, pantorrilla_cm AS pantorrilla_CM, notas
        FROM mediciones WHERE paciente_id=%s ORDER BY fecha DESC
    """, (int(pac["id"]),))
    if hist.empty: st.info("Aún no hay mediciones registradas.")
    else: st.dataframe(hist, use_container_width=True, hide_index=True)

    st.markdown("### 🖼️ Tus fotos")
    gal = df_sql("SELECT fecha, drive_file_id, filename FROM fotos WHERE paciente_id=%s ORDER BY fecha DESC", (int(pac["id"]),))
    if gal.empty:
        st.info("Sin fotos aún.")
    else:
        if "_photos_css_loaded_patient" not in st.session_state:
            st.markdown("""
                <style>
                  .photo-card { background:#111;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.2);display:flex;flex-direction:column;align-items:center;margin-bottom:6px; }
                  .photo-card img { height:220px;width:auto;object-fit:contain;display:block;margin:auto; }
                </style>
            """, unsafe_allow_html=True)
            st.session_state._photos_css_loaded_patient = True

        def _chunk(lst, n):
            for i in range(0, len(lst), n): yield lst[i : i + n]

        for fch in sorted(gal["fecha"].unique(), reverse=True):
            st.markdown(f"### 🗓️ {fch}")
            fila = gal[gal["fecha"] == fch].reset_index(drop=True).to_dict("records")
            for fila4 in _chunk(fila, 4):
                cols = st.columns(4, gap="medium")
                for i, r in enumerate(fila4):
                    with cols[i]:
                        img_url = drive_image_view_url(r["drive_file_id"]) if r.get("drive_file_id") else ""
                        dl_url = drive_image_download_url(r["drive_file_id"]) if r.get("drive_file_id") else None
                        st.markdown(f"""<div class="photo-card"><img src="{img_url}" alt="foto"></div>""",
                                    unsafe_allow_html=True)
                        if dl_url: st.link_button("⬇️ Descargar", dl_url)
                        else: st.caption("—")

# =========================
# Router principal
# =========================
st.title("🩺 Carmen Coach — Agenda & Pacientes")

role = st.session_state.role
if role == "admin":
    view_admin()
elif role == "paciente_agenda":
    view_agenda_paciente()
elif role == "paciente_ro":
    view_paciente_ro()
else:
    st.info("Elige un modo de acceso en la barra lateral (Admin / Paciente Agenda / Paciente RO).")


