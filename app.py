# app.py (Neon / PostgreSQL)
import streamlit as st
import os, uuid, hashlib, io, traceback
import pandas as pd
from datetime import date

st.set_page_config(page_title="Pacientes", page_icon="🩺", layout="wide")

# =========================
# Config media local (nota: en cloud puede ser efímero)
# =========================
MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)

# =========================
# DB helpers (Neon / Postgres con psycopg)
# =========================
import psycopg

# Lee URL de Neon de secrets o env
NEON_URL = st.secrets.get("NEON_DATABASE_URL") if hasattr(st, "secrets") else os.getenv("NEON_DATABASE_URL")
if not NEON_URL:
    st.warning("Configura NEON_DATABASE_URL en secrets o variables de entorno para conectar a PostgreSQL.")

def conn():
    return psycopg.connect(NEON_URL)

def _qmark_to_psql(q: str) -> str:
    # Convierte '?' (SQLite) -> '%s' (Postgres) para no tocar tus queries
    return q.replace("?", "%s")

def exec_sql(q, p=()):
    q_ps = _qmark_to_psql(q)
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(q_ps, p)

def df_sql(q, p=()):
    q_ps = _qmark_to_psql(q)
    with conn() as c:
        return pd.read_sql_query(q_ps, c, params=p)

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

setup_db()
ensure_mediciones_columns()

def delete_paciente(pid: int):
    # 1) Borrar fotos físicas del disco (si existen)
    fotos = query_df("SELECT filepath FROM fotos WHERE paciente_id = %s", (pid,))
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
    fila = df_sql("SELECT filepath FROM fotos WHERE id = %s", (photo_id,))
    if fila.empty:
        st.warning("No se encontró la foto en la base.")
        return
    path = fila["filepath"].iloc[0]
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception as e:
        st.warning(f"No se pudo borrar el archivo físico: {e}")
        st.text(traceback.format_exc())
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
        tok = uuid.uuid4().hex
        exec_sql("UPDATE pacientes SET token = %s WHERE id = %s", (tok, pid))
    return tok

def buscar_pacientes(filtro=""):
    return df_sql("SELECT id, nombre FROM pacientes WHERE nombre LIKE ? ORDER BY nombre",
                  (f"%{filtro}%",))

def query_mediciones(pid):
    return df_sql("""
       SELECT fecha, rutina_pdf, plan_pdf
         FROM mediciones
        WHERE paciente_id = ?
        ORDER BY fecha DESC
    """, (pid,))

def upsert_medicion(pid, fecha, rutina_pdf, plan_pdf):
    # UPSERT en Postgres (paciente_id, fecha)
    exec_sql("""
      INSERT INTO mediciones (paciente_id, fecha, rutina_pdf, plan_pdf)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(paciente_id, fecha)
      DO UPDATE SET rutina_pdf = EXCLUDED.rutina_pdf, plan_pdf = EXCLUDED.plan_pdf
    """, (pid, fecha, rutina_pdf, plan_pdf))

def save_image(file, pid: int, fecha_str: str):
    ext = os.path.splitext(file.name)[1].lower() or ".jpg"
    filename = f"p{pid}_{fecha_str}_{uuid.uuid4().hex}{ext}"
    path = os.path.join(MEDIA_DIR, filename)
    with open(path, "wb") as f:
        f.write(file.read())
    exec_sql("INSERT INTO fotos (paciente_id, fecha, filepath) VALUES (%s, %s, %s)",
             (pid, fecha_str, path))
    return path

def to_drive_preview(url: str) -> str:
    if not url: return ""
    u = url.strip().split("%s")[0]
    if "drive.google.com" in u:
        if "/view" in u: u = u.replace("/view", "/preview")
        elif not u.endswith("/preview"):
            u = u[:-1] + "preview" if u.endswith("/") else u + "/preview"
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
                    st.error("El nombre es obligatorio."); return
                dup = df_sql("SELECT id FROM pacientes WHERE nombre = %s", (nombre.strip(),))
                if not dup.empty:
                    st.warning("Ya existe un paciente con ese nombre."); return
                tok = uuid.uuid4().hex[:8]
                exec_sql("""INSERT INTO pacientes(nombre, fecha_nac, telefono, correo, notas, token)
                            VALUES(%s,%s,%s,%s,%s,%s)""",
                         (nombre.strip(), str(fnac), tel.strip(), mail.strip(), notas.strip(), tok))
                st.success("Paciente creado ✅"); st.rerun()
        nuevo_paciente()

    c1, c2 = st.columns([2,1])
    with c1:
        filtro = st.text_input("Buscar paciente")
        lista = buscar_pacientes(filtro)
        if lista.empty:
            st.info("No hay pacientes. Crea uno con '➕ Nuevo paciente'.")
            st.stop()
        pac_sel = st.selectbox("Paciente", lista["nombre"].tolist(), key="adm_pac")
        pid = int(lista.loc[lista["nombre"] == pac_sel, "id"].iloc[0])

    for i, row in lista.iterrows():
        col1, col2 = st.columns([4, 1])
        with col1:
            st.write(f"👤 {row['nombre']} (id={row['id']})")
        with col2:
            if st.button("🗑️ Eliminar", key=f"del_{row['id']}"):
                st.session_state["_delete_pid"] = row["id"]

    # Confirmación
    if "_delete_pid" in st.session_state:
        pid = st.session_state["_delete_pid"]
        st.error("⚠️ ¿Seguro que quieres eliminar este paciente y todos sus datos?")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("❌ Cancelar", key="cancel_del"):
                del st.session_state["_delete_pid"]
        with c2:
            if st.button("✅ Sí, eliminar", key="confirm_del"):
                delete_paciente(pid)
                del st.session_state["_delete_pid"]
                st.rerun()

    with c2:
        if st.button("🔗 Copiar link del portal del paciente"):
            tok = get_or_create_token(pid)
            st.code(f"http://localhost:8501/?token={tok}", language="text")

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

        citas_m = df_sql("SELECT fecha FROM mediciones WHERE paciente_id=? ORDER BY fecha DESC", (pid,))
        if citas_m.empty:
            st.info("Sin mediciones registradas todavía.")
        else:
            fecha_sel_m = st.selectbox("Editar medición de fecha", citas_m["fecha"].tolist(), key=f"med_fecha_{pid}")
            actual_m = df_sql("SELECT * FROM mediciones WHERE paciente_id=? AND fecha=?", (pid, fecha_sel_m)).iloc[0]

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
                             peso_kg     AS peso,
                             grasa_pct   AS grasa,
                             musculo_pct AS musculo,
                             brazo_rest,
                             brazo_flex,
                             pecho_rest,
                             pecho_flex,
                             cintura_cm  AS cintura,
                             cadera_cm   AS cadera,
                             pierna_cm   AS pierna,
                             pantorrilla_cm AS pantorrilla
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

        gal = df_sql("SELECT id, fecha, filepath FROM fotos WHERE paciente_id=%s ORDER BY fecha DESC", (pid,))
        if gal.empty:
            st.info("Sin fotos aún.")
        else:
            for fch in sorted(gal["fecha"].unique(), reverse=True):
                st.markdown(f"#### 📅 {fch}")
                fila = gal[gal["fecha"] == fch]
                cols = st.columns(4)
                for idx, r in fila.iterrows():
                    with cols[idx % 4]:
                        st.image(r["filepath"], use_container_width=True)
                        c1, c2 = st.columns([1, 1])
                        with c1:
                            st.download_button("⬇️ Descargar", data=open(r["filepath"], "rb"),
                                               file_name=os.path.basename(r["filepath"]))
                        with c2:
                            if st.button("🗑️ Eliminar", key=f"del_{r['id']}"):
                                st.session_state._delete_photo_id = int(r["id"])
                                st.session_state._delete_photo_path = r["filepath"]
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
                            peso_kg     AS peso,
                            grasa_pct   AS grasa,
                            musculo_pct AS musculo,
                            brazo_rest,
                            brazo_flex,
                            pecho_rest,
                            pecho_flex,
                            cintura_cm  AS cintura,
                            cadera_cm   AS cadera,
                            pierna_cm   AS pierna,
                            pantorrilla_cm AS pantorrilla,
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
    gal = df_sql("SELECT fecha, filepath FROM fotos WHERE paciente_id=%s ORDER BY fecha DESC", (int(pac["id"]),))
    if gal.empty:
        st.info("Aún no hay fotos registradas.")
    else:
        for fch in sorted(gal["fecha"].unique(), reverse=True):
            st.markdown(f"#### 📅 {fch}")
            fila = gal[gal["fecha"] == fch]
            cols = st.columns(4)
            i = 0
            for _, r in fila.iterrows():
                with cols[i % 4]:
                    st.image(r["filepath"], use_container_width=True)
                i += 1

else:
    st.info("Elige un modo de acceso en la barra lateral (Admin o Paciente).")
