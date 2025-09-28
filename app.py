# app.py
import streamlit as st

st.set_page_config(page_title="Carmen Coach", page_icon="🩺", layout="wide")

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
div[data-testid="stExpander"] > details {
  background: #f0f0f0;  /* gris claro */
  border-radius: 12px;
  border: 1px solid #d6d6d6;
  color: #111 !important; /* asegura que el texto sea oscuro y legible */
}

/* Inputs */
.stTextInput > div > div > input,
.stNumberInput input,
.stTextArea textarea,
.stSelectbox > div > div {
  background: #FFFFFF !important;
  color: #111827 !important;
  border: 1px solid #E5E7EB !important;
  border-radius: 10px !important;
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

/* Encabezados */
h1, h2, h3, h4 { color: #111827; }
"""

st.markdown(f"<style>{CUSTOM_CSS}</style>", unsafe_allow_html=True)

# Estado base
st.session_state.setdefault("role", None)
st.session_state.setdefault("paciente", None)

# ======== Define páginas ========
# Puedes apuntar a tus scripts existentes en /pages
home      = st.Page("pages/0_Login.py",               title="Inicio",            icon="🩺")
pac_dash  = st.Page("pages/1_Paciente_Dashboard.py",  title="Paciente Dashboard",icon="🧑")
car_hoy   = st.Page("pages/2_Carmen_Hoy.py",          title="Carmen Hoy",        icon="📅")
car_pac   = st.Page("pages/3_Carmen_Pacientes.py",    title="Carmen Pacientes",  icon="📚")
car_citas = st.Page("pages/4_Carmen_Citas.py",        title="Carmen Citas",      icon="🗓️")

role = st.session_state["role"]

if role == "paciente":
    nav = st.navigation([pac_dash])           # ← solo ve su dashboard
elif role == "admin":
    nav = st.navigation({"Carmen": [car_hoy, car_pac, car_citas]})  # ← solo páginas de Carmen
else:
    nav = st.navigation([home])               # ← solo login

nav.run()


