# app.py
import streamlit as st
from modules.core import is_admin_ok, login_paciente, registrar_paciente, normalize_tel

st.set_page_config(
    page_title="Carmen Coach",
    page_icon="assets/logo.png",  # usa tu logo como icono
    layout="wide"
)

# Estado base
st.session_state.setdefault("role", None)
st.session_state.setdefault("paciente", None)

# ======== Define páginas ========
# Puedes apuntar a tus scripts existentes en /pages
home      = st.Page("pages/0_Login.py",               title="Inicio",            page_icon="assets/logo.png")
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


