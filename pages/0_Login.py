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
/* Expanders más oscuros */
div[data-testid="stExpander"] > details {
  background: #2C2C2C;   /* gris oscuro */
  border-radius: 12px;
  border: 1px solid #444444;  /* borde gris */
  color: #FFFFFF;             /* texto en blanco */
}


/* ===== Inputs (cubre text/number/password/date/time/select/textarea) ===== */
.stTextInput input,
.stNumberInput input,
.stDateInput input,
.stTimeInput input,
.stTextArea textarea,
.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div,
[data-baseweb="input"] input,
textarea,
input[type="text"],
input[type="password"],
input[type="email"],
input[type="tel"],
input[type="number"] {
  background: #F2F2F2 !important;    /* gris claro y descansado */
  color: #111827 !important;          /* texto oscuro */
  border: 1px solid #D1D5DB !important; /* gris medio */
  border-radius: 10px !important;
  box-shadow: none !important;
}

/* Placeholders más suaves */
::placeholder { color: #6B7280 !important; }

/* Al enfocar: borde guinda sutil + halo tenue */
.stTextInput input:focus,
.stNumberInput input:focus,
.stDateInput input:focus,
.stTimeInput input:focus,
.stTextArea textarea:focus,
.stSelectbox [data-baseweb="select"] > div:focus-within,
.stMultiSelect [data-baseweb="select"] > div:focus-within,
[data-baseweb="input"] input:focus,
textarea:focus {
  border-color: #A02C4A !important;           /* guinda */
  box-shadow: 0 0 0 3px rgba(160,44,74,0.15) !important;
  outline: none !important;
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

