# app.py
import streamlit as st
from modules.core import is_admin_ok, login_paciente, registrar_paciente, normalize_tel

st.set_page_config(page_title="Carmen Coach — Inicio", page_icon="🩺", layout="wide")

st.title("🩺 Carmen Coach")
st.caption("Bienvenida/o. Elige cómo quieres entrar.")

# Estado base
if "role" not in st.session_state:
    st.session_state.role = None
if "paciente" not in st.session_state:
    st.session_state.paciente = None

col1, col2 = st.columns(2)

# -------- ADMIN --------
with col1:
    st.subheader("👩‍⚕️ Carmen (Admin)")
    a_user = st.text_input("Usuario", value="carmen", disabled=True)
    a_pass = st.text_input("Contraseña", type="password")
    if st.button("Entrar como Admin", use_container_width=True):
        if is_admin_ok(a_user, a_pass):
            st.session_state.role = "admin"
            st.switch_page("pages/2_Carmen_Hoy.py")
        else:
            st.error("Credenciales inválidas")

# -------- PACIENTE --------
with col2:
    st.subheader("🧑 Paciente")
    modo = st.radio("Cuenta", ["Iniciar sesión", "Registrarme"], horizontal=True)
    if modo == "Iniciar sesión":
        tel = st.text_input("Teléfono")
        pw  = st.text_input("Contraseña", type="password")
        if st.button("Entrar", use_container_width=True):
            user = login_paciente(tel, pw)
            if user:
                st.session_state.role = "paciente"
                st.session_state.paciente = user
                st.switch_page("pages/1_Paciente_Dashboard.py")
            else:
                st.error("Teléfono o contraseña incorrectos.")
    else:
        nombre = st.text_input("Nombre completo")
        tel = st.text_input("Teléfono")
        pw1 = st.text_input("Contraseña", type="password")
        pw2 = st.text_input("Repite tu contraseña", type="password")
        if st.button("Registrarme", use_container_width=True):
            if not (nombre.strip() and tel.strip() and pw1 and pw2):
                st.error("Completa todos los campos.")
            elif pw1 != pw2:
                st.error("Las contraseñas no coinciden.")
            else:
                try:
                    pid = registrar_paciente(nombre, tel, pw1)
                    st.session_state.role = "paciente"
                    st.session_state.paciente = {"id": pid, "nombre": nombre.strip(), "telefono": normalize_tel(tel)}
                    st.switch_page("pages/1_Paciente_Dashboard.py")
                except Exception as e:
                    st.error(f"No se pudo registrar: {e}")
