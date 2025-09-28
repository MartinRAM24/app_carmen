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
    a_user = st.text_input("Usuario", value="carmen", disabled=True, key="admin_user_input")
    a_pass = st.text_input("Contraseña", type="password", key="admin_pass_input")
    if st.button("Entrar como Admin", use_container_width=True, key="admin_login_btn"):
        if is_admin_ok(a_user, a_pass):
            st.session_state.role = "admin"
            try:
                st.switch_page("pages/2_Carmen_Hoy.py")
            except Exception:
                st.success("Acceso admin concedido ✅ (no se pudo hacer switch_page)")
        else:
            st.error("Credenciales inválidas")

# -------- PACIENTE --------
with col2:
    st.subheader("🧑 Paciente")
    modo = st.radio("Cuenta", ["Iniciar sesión", "Registrarme"], horizontal=True, key="pac_modo_radio")

    if modo == "Iniciar sesión":
        tel_login = st.text_input("Teléfono", key="pac_tel_login")
        pw_login  = st.text_input("Contraseña", type="password", key="pac_pw_login")
        if st.button("Entrar", use_container_width=True, key="pac_login_btn"):
            user = login_paciente(tel_login, pw_login)
            if user:
                st.session_state.role = "paciente"
                st.session_state.paciente = user
                try:
                    st.switch_page("pages/1_Paciente_Dashboard.py")
                except Exception:
                    st.success("Login ok ✅ (no se pudo hacer switch_page)")
            else:
                st.error("Teléfono o contraseña incorrectos.")
    else:
        nombre = st.text_input("Nombre completo", key="pac_reg_name")
        tel_reg = st.text_input("Teléfono", key="pac_reg_tel")
        pw1     = st.text_input("Contraseña", type="password", key="pac_reg_pw1")
        pw2     = st.text_input("Repite tu contraseña", type="password", key="pac_reg_pw2")
        if st.button("Registrarme", use_container_width=True, key="pac_reg_btn"):
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
                        st.success("Registro ok ✅ (no se pudo hacer switch_page)")
                except Exception as e:
                    st.error(f"No se pudo registrar: {e}")

