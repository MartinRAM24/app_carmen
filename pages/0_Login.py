# pages/0_Login.py
import streamlit as st
from modules.core import is_admin_ok, login_paciente, registrar_paciente, normalize_tel
import base64

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

def get_base64_of_bin_file(bin_file):
    with open(bin_file, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()

logo_base64 = get_base64_of_bin_file("assets/Logo.png")

st.markdown(
    f"""
    <div style="text-align: center;">
        <img src="data:image/png;base64,{logo_base64}" width="300">
        <p>Bienvenida/o. Elige cómo quieres entrar.</p>
    </div>
    """,
    unsafe_allow_html=True
)

# Estado base
st.session_state.setdefault("role", None)
st.session_state.setdefault("paciente", None)

tab_coach, tab_pac = st.tabs(["👩‍⚕️ Coach", "🧑 Paciente"])

# ===== Coach =====
with tab_coach:
    st.subheader("Carmen (Coach)")
    with st.form("form_admin_login", clear_on_submit=False):
        a_user = st.text_input("Usuario", value="carmen", disabled=True, key="admin_user")
        a_pass = st.text_input("Contraseña", type="password", key="admin_pass")
        enviar_admin = st.form_submit_button("Entrar como Coach", use_container_width=True)
    if enviar_admin:
        if is_admin_ok(a_user, a_pass):
            st.session_state.role = "admin"
            try:
                st.switch_page("pages/2_Carmen_Hoy.py")
            except Exception:
                st.success("Acceso Coach concedido ✅")
                st.rerun()
        else:
            st.error("Credenciales inválidas")

# ===== Paciente =====
with tab_pac:
    st.subheader("Paciente")
    modo = st.radio("¿Qué quieres hacer?", ["Iniciar sesión", "Registrarme"],
                    horizontal=True, key="pac_radio")

    if modo == "Iniciar sesión":
        with st.form("form_pac_login", clear_on_submit=False):
            tel_login = st.text_input("Teléfono", key="pac_tel_login")
            pw_login  = st.text_input("Contraseña", type="password", key="pac_pw_login")
            enviar_login = st.form_submit_button("Entrar", use_container_width=True)
        if enviar_login:
            user = login_paciente(tel_login, pw_login)
            if user:
                st.session_state.role = "paciente"
                st.session_state.paciente = user
                try:
                    st.switch_page("pages/1_Paciente_Dashboard.py")
                except Exception:
                    st.success("Login ok ✅"); st.rerun()
            else:
                st.error("Teléfono o contraseña incorrectos.")

    else:
        with st.form("form_pac_reg", clear_on_submit=False):
            nombre = st.text_input("Nombre completo", key="pac_reg_name")
            tel_reg = st.text_input("Teléfono", key="pac_reg_tel")
            pw1     = st.text_input("Contraseña", type="password", key="pac_reg_pw1")
            pw2     = st.text_input("Repite tu contraseña", type="password", key="pac_reg_pw2")
            enviar_reg = st.form_submit_button("Registrarme", use_container_width=True)

        if enviar_reg:
            if not (nombre.strip() and tel_reg.strip() and pw1 and pw2):
                st.error("Completa todos los campos.")
            elif pw1 != pw2:
                st.error("Las contraseñas no coinciden.")
            else:
                try:
                    pid = registrar_paciente(nombre, tel_reg, pw1)
                    st.session_state.role = "paciente"
                    st.session_state.paciente = {
                        "id": pid,
                        "nombre": nombre.strip(),
                        "telefono": normalize_tel(tel_reg),
                    }
                    try:
                        st.switch_page("pages/1_Paciente_Dashboard.py")
                    except Exception:
                        st.success("Registro ok ✅"); st.rerun()
                except Exception as e:
                    st.error(f"No se pudo registrar: {e}")

