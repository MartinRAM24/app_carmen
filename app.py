# app.py (Neon / PostgreSQL)
import streamlit as st
import os, uuid, hashlib, traceback
import pandas as pd
from datetime import date
import psycopg
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io, re


st.set_page_config(page_title="Pacientes", page_icon="🩺", layout="wide")

# =========================
# Config media local (nota: en cloud puede ser efímero)
# =========================
MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)

# =========================
# DB helpers (Neon / Postgres con psycopg)
# =========================
# --- DB helpers (Postgres con psycopg) ---

NEON_URL = st.secrets.get("NEON_DATABASE_URL") or os.getenv("NEON_DATABASE_URL")

@st.cache_resource
def conn():
    if not NEON_URL:
        st.stop()  # fuerza a configurar la URL
    # autocommit True para no olvidar commit
    return psycopg.connect(NEON_URL, autocommit=True)

def exec_sql(q_ps: str, p: tuple = ()):
    with conn().cursor() as cur:
        cur.execute(q_ps, p)

def df_sql(q_ps: str, p: tuple = ()):
    return pd.read_sql_query(q_ps, conn(), params=p)



# =========================
# Esquema de tablas (Postgres)
# =========================
def setup_db():
    # pacientes
    exec_sql("""
    CREATE TABLE IF NOT EXISTS pacientes(
      id         BIGSERIAL PRIMARY KEY,
      nombre     TEXT NOT NULL,
      fecha_nac  TEXT,
      telefono   TEXT,
      correo     TEXT,
      notas      TEXT,
      token      TEXT UNIQUE
    )
    """)
    # mediciones (citas) incl. PDFs + métricas
    exec_sql("""
    CREATE TABLE IF NOT EXISTS mediciones(
      id              BIGSERIAL PRIMARY KEY,
      paciente_id     BIGINT NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
      fecha           TEXT NOT NULL,       -- 'YYYY-MM-DD'
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
      CONSTRAINT mediciones_unq UNIQUE (paciente_id, fecha)
    )
    """)
    # fotos
    exec_sql("""
    CREATE TABLE IF NOT EXISTS fotos(
      id           BIGSERIAL PRIMARY KEY,
      paciente_id  BIGINT NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
      fecha        TEXT NOT NULL,   -- 'YYYY-MM-DD'
      filepath     TEXT NOT NULL
    )
    """)

def add_col_if_missing(table: str, col: str, coldef: str):
    # Compatibilidad: en Postgres usamos information_schema
    exists = df_sql("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s AND column_name=%s
    """, (table, col))
    if exists.empty:
        exec_sql(f'ALTER TABLE {table} ADD COLUMN {col} {coldef}')
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/drive"]

def get_drive():
    """Devuelve cliente de Google Drive usando secrets en la nube"""
    info = dict(st.secrets["gcp_service_account"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)

# Carpeta raíz en Drive donde se crearán las subcarpetas de pacientes
ROOT_FOLDER_ID = st.secrets.get("DRIVE_ROOT_FOLDER_ID")  # ID de la carpeta en tus secrets


def debug_root_access():
    st.write("SA:", st.secrets["gcp_service_account"]["client_email"])
    st.write("ROOT_FOLDER_ID:", st.secrets.get("DRIVE_ROOT_FOLDER_ID"))
    drive = get_drive()
    rid = st.secrets.get("DRIVE_ROOT_FOLDER_ID")
    if not rid:
        st.error("Falta DRIVE_ROOT_FOLDER_ID en Secrets.")
        return
    try:
        info = drive.files().get(
            fileId=rid,
            fields="id,name,parents,driveId",
            supportsAllDrives=True
        ).execute()
        st.success(f"OK acceso a raíz: {info['name']} ({info['id']})")
    except HttpError as e:
        st.error(f"Sin acceso a la raíz. Comparte la carpeta con la SA como 'Content manager'. Error: {e}")
        st.stop()

debug_root_access()

def ensure_mediciones_columns():
    needed = [
        ("peso_kg", "DOUBLE PRECISION"),
        ("grasa_pct", "DOUBLE PRECISION"),
        ("musculo_pct", "DOUBLE PRECISION"),
        ("brazo_rest", "DOUBLE PRECISION"),
        ("brazo_flex", "DOUBLE PRECISION"),
        ("pecho_rest", "DOUBLE PRECISION"),
        ("pecho_flex", "DOUBLE PRECISION"),
        ("cintura_cm", "DOUBLE PRECISION"),
        ("cadera_cm", "DOUBLE PRECISION"),
        ("pierna_cm", "DOUBLE PRECISION"),
        ("pantorrilla_cm", "DOUBLE PRECISION"),
        ("notas", "TEXT"),
    ]
    for col, typ in needed:
        add_col_if_missing("mediciones", col, typ)

SCOPES = ["https://www.googleapis.com/auth/drive"]

 # puede ser None

@st.cache_resource
def ensure_patient_folder(nombre: str, pid: int) -> str:
    drive = get_drive()

    # 1) Validar root opcional
    parent = ROOT_FOLDER_ID

    # 2) Nombre y query
    folder_name = f"{pid:05d} - {nombre}"
    escaped = folder_name.replace("'", "\\'")
    q = (
        "mimeType='application/vnd.google-apps.folder' and trashed=false "
        f"and name='{escaped}' "
        + (f"and '{parent}' in parents" if parent else "")
    )

    res = drive.files().list(
        q=q, fields="files(id,name,parents)", pageSize=1,
        supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent:
        meta["parents"] = [parent]

    folder = drive.files().create(
        body=meta,
        fields="id,name,parents,webViewLink",
        supportsAllDrives=True
    ).execute()
    return folder["id"]



def extract_drive_folder_id(url_or_id: str) -> str | None:
    if not url_or_id:
        return None
    s = url_or_id.strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", s)
    if m: return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", s): return s
    return None

def make_anyone_reader(file_id: str):
    drive = get_drive()
    drive.permissions().create(fileId=file_id, body={"type": "anyone", "role": "reader"}).execute()

def upload_pdf_to_folder(file_bytes: bytes, filename: str, folder_id: str) -> dict:
    drive = get_drive()
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="application/pdf", resumable=False)
    meta = {"name": filename, "parents": [folder_id]}
    f = drive.files().create(
        body=meta,
        media_body=media,
        fields="id,webViewLink",
        supportsAllDrives=True,
    ).execute()
    make_anyone_reader(f["id"])
    return f

def upload_image_to_folder(file_bytes: bytes, filename: str, folder_id: str, mime: str) -> dict:
    drive = get_drive()
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime, resumable=False)
    meta = {"name": filename, "parents": [folder_id]}
    f = drive.files().create(
        body=meta,
        media_body=media,
        fields="id,webViewLink",
        supportsAllDrives=True,
    ).execute()
    make_anyone_reader(f["id"])
    return f


def drive_image_view_url(file_id: str) -> str:
    # URL directa para <img>
    return f"https://drive.google.com/uc?export=view&id={file_id}"

def drive_image_download_url(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=download&id={file_id}"

def delete_drive_file(file_id: str):
    try:
        get_drive().files().delete(fileId=file_id).execute()
    except Exception:
        pass  # si ya no existe, ignoramos


setup_db()
ensure_mediciones_columns()

# columnas nuevas para Drive
add_col_if_missing("pacientes", "drive_folder_id", "TEXT")
add_col_if_missing("fotos", "drive_file_id", "TEXT")
add_col_if_missing("fotos", "web_view_link", "TEXT")
add_col_if_missing("fotos", "filename", "TEXT")


def delete_paciente(pid: int):
    # 1) Borrar fotos físicas del disco (si existen)
    fotos = df_sql("SELECT filepath FROM fotos WHERE paciente_id = %s", (pid,))
    for _, row in fotos.iterrows():
        path = row["filepath"]
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            st.warning(f"No se pudo borrar {path}: {e}")

    # 2) Borrar registros dependientes
    exec_sql("DELETE FROM fotos WHERE paciente_id = %s", (pid,))
    exec_sql("DELETE FROM mediciones WHERE paciente_id = %s", (pid,))

    # 3) Borrar paciente
    exec_sql("DELETE FROM pacientes WHERE id = %s", (pid,))

    st.success("Paciente eliminado ✅")



# =========================
# Helpers de dominio
# =========================
def delete_foto(photo_id: int):
    fila = df_sql("SELECT drive_file_id, filepath FROM fotos WHERE id = %s", (photo_id,))
    if fila.empty:
        st.warning("No se encontró la foto en la base.")
        return

    file_id = fila["drive_file_id"].iloc[0]
    path = fila["filepath"].iloc[0]

    # borra del disco si fuera una foto vieja (compatibilidad)
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception as e:
        st.warning(f"No se pudo borrar el archivo físico: {e}")
        st.text(traceback.format_exc())

    # borra de Drive si existe
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
    if d.empty: return None
    tok = d["token"].iloc[0]
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
        (f"%{filtro}%",)
    )

def query_mediciones(pid):
    return df_sql("""
       SELECT fecha, rutina_pdf, plan_pdf
         FROM mediciones
        WHERE paciente_id = %s
        ORDER BY fecha DESC
    """, (pid,))

def upsert_medicion(pid, fecha, rutina_pdf, plan_pdf):
    exec_sql("""
      INSERT INTO mediciones (paciente_id, fecha, rutina_pdf, plan_pdf)
      VALUES (%s, %s, %s, %s)
      ON CONFLICT (paciente_id, fecha)
      DO UPDATE SET
        rutina_pdf = EXCLUDED.rutina_pdf,
        plan_pdf   = EXCLUDED.plan_pdf
    """, (pid, fecha, rutina_pdf, plan_pdf))


def save_image(file, pid: int, fecha_str: str):
    # sube a Drive en vez de disco
    pf = df_sql("SELECT drive_folder_id, nombre FROM pacientes WHERE id=%s", (pid,))
    if pf.empty or not (pf["drive_folder_id"].iloc[0] or "").strip():
        raise RuntimeError("Este paciente no tiene carpeta de Drive asignada.")

    folder_id = (pf["drive_folder_id"].iloc[0] or "").strip()
    filename = file.name
    mime = file.type or "image/jpeg"

    f = upload_image_to_folder(file.read(), filename, folder_id, mime)
    file_id = f["id"]
    web_link = f["webViewLink"]

    exec_sql("""
        INSERT INTO fotos (paciente_id, fecha, filepath, drive_file_id, web_view_link, filename)
        VALUES (%s,%s,%s,%s,%s,%s)
    """, (pid, fecha_str, None, file_id, web_link, filename))

    return file_id


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



# =========================
# UI (tu misma lógica)
# =========================
st.title("🩺 Gestión de Pacientes")
token_from_url = st.query_params.get("token", [None])[0] if hasattr(st, "query_params") else None

with st.sidebar:
    st.markdown("## Acceso")
    tabs = st.tabs(["👩‍⚕️ Admin", "🧑 Paciente"])
    with tabs[0]:
        a_user = st.text_input("Usuario", value=ADMIN_USER, disabled=True)
        a_pass = st.text_input("Contraseña", type="password")
        admin_login = st.button("Entrar como Admin")
    with tabs[1]:
        p_token = st.text_input("Token de acceso (o usa el link con %stoken=...)", value=token_from_url or "")
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

# ---------- ADMIN ----------
if role == "admin":
    st.subheader("👩‍⚕️ Vista de administración (Carmen)")
    if st.button("➕ Nuevo paciente"):
        @st.dialog("➕ Nuevo paciente")
        def nuevo_paciente():
            with st.form("form_nuevo_paciente", clear_on_submit=True):
                nombre = st.text_input("Nombre completo *")
                fnac = st.date_input("Fecha de nacimiento", value=date(2000,1,1))
                tel = st.text_input("Teléfono")
                mail = st.text_input("Correo")
                notas = st.text_area("Notas")
                enviar = st.form_submit_button("Guardar")
            if enviar:
                if not nombre.strip():
                    st.error("El nombre es obligatorio.");
                    return
                dup = df_sql("SELECT id FROM pacientes WHERE nombre = %s", (nombre.strip(),))
                if not dup.empty:
                    st.warning("Ya existe un paciente con ese nombre.");
                    return

                tok = uuid.uuid4().hex[:8]
                # 1) crea paciente para obtener ID
                new_row = df_sql("""
                                 INSERT INTO pacientes (nombre, fecha_nac, telefono, correo, notas, token)
                                 VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                                 """, (nombre.strip(), str(fnac), tel.strip(), mail.strip(), notas.strip(), tok))
                new_id = int(new_row.iloc[0]["id"])

                # 2) crea carpeta en Drive y guarda en DB
                folder_id = ensure_patient_folder(nombre.strip(), new_id)
                exec_sql("UPDATE pacientes SET drive_folder_id=%s WHERE id=%s", (folder_id, new_id))

                st.success("Paciente creado y carpeta en Drive lista ✅");
                st.rerun()


        nuevo_paciente()

    # --- Búsqueda controlada (no lista nada por defecto) ---
    with st.form("form_buscar_paciente"):
        filtro = st.text_input("Buscar paciente", placeholder="Ej. Ana, Juan…")
        do_search = st.form_submit_button("Buscar")

    # Ejecutar búsqueda sólo al hacer submit
    if do_search:
        if len(filtro.strip()) < 2:
            st.warning("Escribe al menos 2 letras para buscar.")
        else:
            st.session_state["buscados_df"] = buscar_pacientes(filtro.strip())

    # resultados almacenados tras buscar
    buscados = st.session_state.get("buscados_df", pd.DataFrame(columns=["id", "nombre"]))

    if not buscados.empty:
        st.markdown("#### Resultados")
        c1, c2 = st.columns([2, 1])
        with c1:
            pac_sel = st.selectbox("Paciente", buscados["nombre"].tolist(), key="adm_pac")
            pid = int(buscados.loc[buscados["nombre"] == pac_sel, "id"].iloc[0])

            # botón eliminar
            if st.button("🗑️ Eliminar", key=f"del_{pid}"):
                st.session_state["_del_pid"] = pid
                st.session_state["_del_name"] = pac_sel

            # confirmación en diálogo
            if st.session_state.get("_del_pid") is not None:
                @st.dialog("Confirmar eliminación")
                def _confirm_delete_dialog():
                    st.warning(
                        f"Se eliminará **{st.session_state['_del_name']}** y todos sus datos (mediciones y fotos).")
                    d1, d2 = st.columns(2)
                    with d1:
                        if st.button("❌ Cancelar"):
                            st.session_state.pop("_del_pid", None)
                            st.session_state.pop("_del_name", None)
                    with d2:
                        if st.button("✅ Sí, eliminar"):
                            delete_paciente(st.session_state["_del_pid"])
                            st.session_state.pop("_del_pid", None)
                            st.session_state.pop("_del_name", None)
                            st.cache_data.clear()
                            st.session_state["buscados_df"] = buscar_pacientes(filtro.strip())
                            st.rerun()


                _confirm_delete_dialog()

        with c2:
            if st.button("📋 Copiar token del paciente", use_container_width=True):
                tok = get_or_create_token(pid)
                # Muestra solo el token. El recuadro de `st.code` ya trae botón de copiar.
                st.code(tok, language="")
                st.caption("Toca el icono de copiar del recuadro para poner el token en el portapapeles.")

    else:
        st.caption("Escribe arriba y pulsa **Buscar** para ver resultados.")
        # si no hay resultados, evita usar pid más abajo
        # puedes hacer un return o un st.stop() si quieres bloquear los tabs
        st.stop()

    # === Subida directa a Google Drive (PDFs) ===
    pf = df_sql("SELECT drive_folder_id FROM pacientes WHERE id=%s", (pid,))
    folder_id = (pf["drive_folder_id"].iloc[0] or "").strip() if not pf.empty else ""

    st.markdown("### ⬆️ Subir PDFs a la carpeta de Drive del paciente")
    if not folder_id:
        st.warning("Primero asigna la carpeta de Drive del paciente en la pestaña **🧾 Perfil**.")
    else:
        fecha_sel = st.text_input("Fecha para asociar los PDFs (YYYY-MM-DD)", value=str(date.today()),
                                  key=f"fecha_pdf_{pid}")
        up_r = st.file_uploader("Subir **Rutina (PDF)**", type=["pdf"], key=f"up_r_{pid}")
        up_p = st.file_uploader("Subir **Plan alimenticio (PDF)**", type=["pdf"], key=f"up_p_{pid}")
        b1, b2 = st.columns(2)
        with b1:
            if up_r and st.button("⬆️ Subir Rutina a Drive"):
                with st.spinner("Subiendo Rutina a Drive..."):
                    f = upload_pdf_to_folder(up_r.read(), up_r.name, folder_id)
                    upsert_medicion(pid, fecha_sel.strip(), f["webViewLink"], None)
                    st.success("Rutina subida y enlazada ✅");
                    st.rerun()
        with b2:
            if up_p and st.button("⬆️ Subir Plan a Drive"):
                with st.spinner("Subiendo Plan a Drive..."):
                    f = upload_pdf_to_folder(up_p.read(), up_p.name, folder_id)
                    exec_sql("""INSERT INTO mediciones (paciente_id, fecha, rutina_pdf, plan_pdf)
                                VALUES (%s, %s, %s, %s) ON CONFLICT (paciente_id, fecha) DO
                    UPDATE SET plan_pdf = EXCLUDED.plan_pdf""",
                             (pid, fecha_sel.strip(), None, f["webViewLink"]))
                    st.success("Plan subido y enlazado ✅");
                    st.rerun()

    tab_info, tab_medidas, tab_pdfs, tab_fotos = st.tabs(["🧾 Perfil", "📏 Mediciones", "📂 PDFs", "🖼️ Fotos"])



    # --- Mediciones ---
    with tab_medidas:
        st.caption("Registra o actualiza medidas por fecha (cada fecha es una cita).")
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
            upsert_medicion(pid, f.strip(), None, None)
            def nz(x): return None if x in (0, 0.0) else x
            exec_sql("""
                     UPDATE mediciones
                     SET peso_kg=%s,
                         grasa_pct=%s,
                         musculo_pct=%s,
                         brazo_rest=%s,
                         brazo_flex=%s,
                         pecho_rest=%s,
                         pecho_flex=%s,
                         cintura_cm=%s,
                         cadera_cm=%s,
                         pierna_cm=%s,
                         pantorrilla_cm=%s,
                         notas=%s
                     WHERE paciente_id = %s
                       AND fecha = %s
                     """, (nz(peso_kg), nz(grasa), nz(musc),
                           nz(brazo_r), nz(brazo_f),
                           nz(pecho_r), nz(pecho_f),
                           nz(cintura), nz(cadera), nz(pierna), nz(pantorrilla),
                           (notas_med.strip() or None), pid, f.strip()))
            st.success("Medición guardada ✅"); st.rerun()

        citas_m = df_sql("SELECT fecha FROM mediciones WHERE paciente_id=%s ORDER BY fecha DESC", (pid,))
        if citas_m.empty:
            st.info("Sin mediciones registradas todavía.")
        else:
            fecha_sel_m = st.selectbox("Editar medición de fecha", citas_m["fecha"].tolist(), key=f"med_fecha_{pid}")
            actual_m = df_sql("SELECT * FROM mediciones WHERE paciente_id=%s AND fecha=%s", (pid, fecha_sel_m)).iloc[0]

            st.markdown("#### Editar valores")
            cols = st.columns(6)
            def val(x): return float(x) if x is not None else 0.0
            campos = [
                ("peso_kg", "Peso (kg)", 0),
                ("grasa_pct", "% Grasa", 1),
                ("musculo_pct", "% Músculo", 2),
                ("brazo_rest", "Brazo reposo", 3),
                ("brazo_flex", "Brazo flex", 4),
                ("pecho_rest", "Pecho reposo", 5),
                ("pecho_flex", "Pecho flex", 0),
                ("cintura_cm", "Cintura (cm)", 1),
                ("cadera_cm", "Cadera (cm)", 2),
                ("pierna_cm", "Pierna (cm)", 3),
                ("pantorrilla_cm", "Pantorrilla (cm)", 4),
            ]
            new_vals = {}
            for key, label, col_idx in campos:
                with cols[col_idx]:
                    new_vals[key] = st.number_input(label, value=val(actual_m[key]), step=0.1,
                                                    key=f"med_edit_{key}_{pid}_{fecha_sel_m}")
            notas_edit = st.text_area("Notas", actual_m["notas"] or "", key=f"med_edit_notas_{pid}_{fecha_sel_m}")

            cA, cB = st.columns(2)
            with cA:
                if st.button("💾 Guardar cambios de medidas"):
                    exec_sql("""
                             UPDATE mediciones
                             SET peso_kg=%s,
                                 grasa_pct=%s,
                                 musculo_pct=%s,
                                 brazo_rest=%s,
                                 brazo_flex=%s,
                                 pecho_rest=%s,
                                 pecho_flex=%s,
                                 cintura_cm=%s,
                                 cadera_cm=%s,
                                 pierna_cm=%s,
                                 pantorrilla_cm=%s,
                                 notas=%s
                             WHERE paciente_id = %s
                               AND fecha = %s
                             """, (new_vals["peso_kg"] or None, new_vals["grasa_pct"] or None,
                                   new_vals["musculo_pct"] or None,
                                   new_vals["brazo_rest"] or None, new_vals["brazo_flex"] or None,
                                   new_vals["pecho_rest"] or None, new_vals["pecho_flex"] or None,
                                   new_vals["cintura_cm"] or None, new_vals["cadera_cm"] or None,
                                   new_vals["pierna_cm"] or None, new_vals["pantorrilla_cm"] or None,
                                   (notas_edit.strip() or None), pid, fecha_sel_m))
                    st.success("Mediciones actualizadas ✅"); st.rerun()
            with cB:
                if st.button("🧹 Vaciar medidas (mantener PDFs)"):
                    exec_sql("""
                             UPDATE mediciones
                             SET peso_kg=NULL,
                                 grasa_pct=NULL,
                                 musculo_pct=NULL,
                                 brazo_rest=NULL,
                                 brazo_flex=NULL,
                                 pecho_rest=NULL,
                                 pecho_flex=NULL,
                                 cintura_cm=NULL,
                                 cadera_cm=NULL,
                                 pierna_cm=NULL,
                                 pantorrilla_cm=NULL,
                                 notas=NULL
                             WHERE paciente_id = %s
                               AND fecha = %s
                             """, (pid, fecha_sel_m))
                    st.success("Mediciones vaciadas ✅"); st.rerun()

        st.markdown("#### 📜 Historial")
        hist = df_sql("""
                      SELECT fecha,
                             peso_kg     AS peso_KG,
                             grasa_pct   AS grasa,
                             musculo_pct AS musculo,
                             brazo_rest AS brazo_rest_CM,
                             brazo_flex AS brazo_flex_CM,
                             pecho_rest AS pecho_rest_CM,
                             pecho_flex AS pecho_flex_CM,
                             cintura_cm  AS cintura_CM,
                             cadera_cm   AS cadera_CM,
                             pierna_cm   AS pierna_CM,
                             pantorrilla_cm AS pantorrilla_CM
                      FROM mediciones
                      WHERE paciente_id = %s
                      ORDER BY fecha DESC
                      """, (pid,))
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
            exec_sql("""UPDATE pacientes
                        SET nombre=%s, fecha_nac=%s, telefono=%s, correo=%s, notas=%s
                        WHERE id=%s""",
                     (nombre.strip(), fnac.strip(), tel.strip(), mail.strip(), notas.strip(), pid))
            st.success("Perfil actualizado ✅"); st.rerun()

    # --- PDFs ---
    with tab_pdfs:
        citas = query_mediciones(pid)
        with st.form("form_nueva_cita"):
            st.caption("Crear/actualizar cita por fecha (formato YYYY-MM-DD)")
            f = st.text_input("Fecha de la cita", value=str(date.today()))
            r = st.text_input("URL Rutina (PDF)")
            p = st.text_input("URL Plan alimenticio (PDF)")
            sub = st.form_submit_button("Guardar/Actualizar cita")
        if sub:
            upsert_medicion(pid, f.strip(), r.strip() or None, p.strip() or None)
            st.success("Cita guardada ✅"); st.rerun()

        if citas.empty:
            st.info("Este paciente aún no tiene citas registradas.")
        else:
            fecha_sel = st.selectbox("Fecha de la cita", citas["fecha"].tolist(), key=f"pdfs_fecha_{pid}")
            actual = citas.loc[citas["fecha"] == fecha_sel].iloc[0]
            rutina_actual = (actual["rutina_pdf"] or "").strip()
            plan_actual   = (actual["plan_pdf"] or "").strip()

            st.markdown("### 📎 Enlaces guardados")
            cL, cR = st.columns(2)
            with cL:
                if rutina_actual:
                    st.link_button("🔗 Rutina (PDF)", rutina_actual)
                else:
                    st.write("Rutina: _vacío_")
                st.text_input("URL Rutina", rutina_actual, key=f"show_r_{pid}_{fecha_sel}", disabled=True)
            with cR:
                if plan_actual:
                    st.link_button("🔗 Plan (PDF)", plan_actual)
                else:
                    st.write("Plan: _vacío_")
                st.text_input("URL Plan", plan_actual, key=f"show_p_{pid}_{fecha_sel}", disabled=True)

            with st.expander("👁️ Vista previa (Drive)"):
                if rutina_actual:
                    st.components.v1.iframe(to_drive_preview(rutina_actual), height=360)
                if plan_actual:
                    st.components.v1.iframe(to_drive_preview(plan_actual), height=360)

            c1, c2 = st.columns(2)
            with c1:
                n_r = st.text_input("Editar URL Rutina", rutina_actual, key=f"edit_r_{pid}_{fecha_sel}")
            with c2:
                n_p = st.text_input("Editar URL Plan", plan_actual, key=f"edit_p_{pid}_{fecha_sel}")
            a1, a2, a3 = st.columns([1,1,2])
            with a1:
                if st.button("💾 Guardar cambios"):
                    exec_sql("""UPDATE mediciones SET rutina_pdf=%s, plan_pdf=%s
                                WHERE paciente_id=%s AND fecha=%s""",
                             (n_r.strip() or None, n_p.strip() or None, pid, fecha_sel))
                    st.success("PDFs actualizados ✅"); st.rerun()
            with a2:
                if st.button("🧹 Vaciar ambos"):
                    exec_sql("""UPDATE mediciones SET rutina_pdf=NULL, plan_pdf=NULL
                                WHERE paciente_id=%s AND fecha=%s""", (pid, fecha_sel))
                    st.success("PDFs vaciados ✅"); st.rerun()

    # --- Fotos ---
    with tab_fotos:
        st.caption("Sube fotos asociadas a una fecha (YYYY-MM-DD).")
        colA, colB = st.columns([2,1])
        with colA:
            fecha_f = st.text_input("Fecha", value=str(date.today()))
            up = st.file_uploader("Agregar fotos", accept_multiple_files=True,
                                  type=["jpg","jpeg","png","webp"])
        with colB:
            if st.button("⬆️ Subir"):
                if not up:
                    st.warning("Selecciona al menos una imagen.")
                else:
                    for f in up:
                        save_image(f, pid, fecha_f.strip())
                    st.success("Fotos subidas ✅"); st.rerun()

        gal = df_sql("""
                     SELECT id, fecha, filepath, drive_file_id
                     FROM fotos
                     WHERE paciente_id = %s
                     ORDER BY fecha DESC
                     """, (pid,))

        if gal.empty:
            st.info("Sin fotos aún.")
        else:
            for fch in sorted(gal["fecha"].unique(), reverse=True):
                st.markdown(f"#### 📅 {fch}")
                fila = gal[gal["fecha"] == fch]
                cols = st.columns(4)
                for idx, r in fila.iterrows():
                    with cols[idx % 4]:
                        # si hay drive_file_id, usa URL directa de Drive; si no, usa filepath (compatibilidad)
                        if r.get("drive_file_id"):
                            img_url = drive_image_view_url(r["drive_file_id"])
                            st.image(img_url, use_container_width=True)
                            dl_url = drive_image_download_url(r["drive_file_id"])
                            c1, c2 = st.columns([1, 1])
                            with c1:
                                st.link_button("⬇️ Descargar", dl_url)
                        else:
                            st.image(r["filepath"], use_container_width=True)
                            c1, c2 = st.columns([1, 1])
                            with c1:
                                st.download_button("⬇️ Descargar", data=open(r["filepath"], "rb"),
                                                   file_name=os.path.basename(r["filepath"]))

                        with c2:
                            if st.button("🗑️ Eliminar", key=f"del_{r['id']}"):
                                st.session_state._delete_photo_id = int(r["id"])
                                st.session_state._delete_photo_path = r.get("filepath")
                                st.session_state._delete_photo_date = fch

                if "_delete_photo_id" in st.session_state:
                    @st.dialog("Confirmar eliminación")
                    def _confirm_delete_dialog():
                        st.warning("Esta acción eliminará la foto del disco y de la base de datos.")
                        pth = st.session_state.get("_delete_photo_path", "")
                        if pth and os.path.exists(pth):
                            st.image(pth, caption=os.path.basename(pth), use_container_width=True)
                        colA, colB = st.columns(2)
                        with colA:
                            if st.button("✅ Sí, borrar"):
                                delete_foto(st.session_state["_delete_photo_id"])
                                for k in ("_delete_photo_id", "_delete_photo_path", "_delete_photo_date"):
                                    st.session_state.pop(k, None)
                                st.success("Foto eliminada ✅"); st.rerun()
                        with colB:
                            if st.button("❌ Cancelar"):
                                for k in ("_delete_photo_id", "_delete_photo_path", "_delete_photo_date"):
                                    st.session_state.pop(k, None)
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
        r = (actual["rutina_pdf"] or "").strip()
        p = (actual["plan_pdf"] or "").strip()
        c1, c2 = st.columns(2)
        with c1: st.link_button("🔗 Abrir Rutina (PDF)", r, disabled=(not bool(r)))
        with c2: st.link_button("🔗 Abrir Plan (PDF)", p, disabled=(not bool(p)))
        with st.expander("👁️ Vista previa (Drive)"):
            if r: st.components.v1.iframe(to_drive_preview(r), height=360)
            if p: st.components.v1.iframe(to_drive_preview(p), height=360)

    st.markdown("### 📏 Tus mediciones")
    hist_ro = df_sql("""
                     SELECT fecha,
                            peso_kg     AS peso_KG,
                            grasa_pct   AS grasa,
                            musculo_pct AS musculo,
                            brazo_rest AS brazo_rest_CM,
                            brazo_flex AS brazo_flex_CM,
                            pecho_rest AS pecho_rest_CM,
                            pecho_flex AS pecho_flex_CM,
                            cintura_cm  AS cintura_CM,
                            cadera_cm   AS cadera_CM,
                            pierna_cm   AS pierna_CM,
                            pantorrilla_cm AS pantorrilla_CM,
                            notas
                     FROM mediciones
                     WHERE paciente_id = %s
                     ORDER BY fecha DESC
                     """, (int(pac["id"]),))
    if hist_ro.empty:
        st.info("Aún no hay mediciones registradas.")
    else:
        st.dataframe(hist_ro, use_container_width=True, hide_index=True)

    st.markdown("### 🖼️ Tus fotos")
    gal = df_sql("""
                 SELECT fecha, filepath, drive_file_id
                 FROM fotos
                 WHERE paciente_id = %s
                 ORDER BY fecha DESC
                 """, (int(pac["id"]),))

    # dentro del loop:
    if r["drive_file_id"]:
        img_url = drive_image_view_url(r["drive_file_id"])
        st.image(img_url, use_container_width=True)
    else:
        st.image(r["filepath"], use_container_width=True)


else:
    st.info("Elige un modo de acceso en la barra lateral (Admin o Paciente).")
