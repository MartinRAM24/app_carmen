# app.py (dentro del sidebar o donde tengas el login)
import streamlit as st
from modules.core import ensure_runtime, is_admin_session, is_patient_session
ensure_runtime()

st.markdown("## Acceso")
tabs = st.tabs(["👩‍⚕️ Admin", "🧑 Paciente"])

# --- ADMIN ---
with tabs[0]:
    a_user = st.text_input("Usuario", key="admin_user_input")
    a_pass = st.text_input("Contraseña", type="password", key="admin_pass_input")
    a_btn  = st.button("Entrar como Admin", use_container_width=True, key="admin_login_btn")

    if a_btn:
        # TODO: valida aquí tus credenciales reales
        if a_user == st.secrets.get("CARMEN_USER") and a_pass == st.secrets.get("CARMEN_PASSWORD"):
            st.session_state.role = "admin"
            st.session_state.paciente = None
            st.success("Acceso admin concedido ✅")
            st.rerun()
        else:
            st.error("Credenciales inválidas")

# --- PACIENTE ---
with tabs[1]:
    modo = st.radio("¿Tienes cuenta?", ["Iniciar sesión", "Registrarme"], horizontal=True, key="pac_modo_radio")

    if modo == "Iniciar sesión":
        p_tel = st.text_input("Teléfono", key="pac_tel_login")
        p_pw  = st.text_input("Contraseña", type="password", key="pac_pw_login")
        p_btn = st.button("Entrar", use_container_width=True, key="pac_login_btn")
        if p_btn:
            # TODO: valida contra tu DB
            user = {"id": 1, "nombre": "Demo"}  # reemplaza por login real
            if user:
                st.session_state.role = "paciente"
                st.session_state.paciente = user
                st.success("Bienvenid@ ✅"); st.rerun()
            else:
                st.error("Teléfono o contraseña incorrectos.")

    else:  # Registrarme
        p_name = st.text_input("Nombre completo", key="pac_reg_name")
        p_telr = st.text_input("Teléfono", key="pac_reg_tel")
        p_pw1  = st.text_input("Contraseña", type="password", key="pac_reg_pw1")
        p_pw2  = st.text_input("Repite tu contraseña", type="password", key="pac_reg_pw2")
        p_rbtn = st.button("Registrarme", use_container_width=True, key="pac_reg_btn")
        if p_rbtn:
            if not (p_name.strip() and p_telr.strip() and p_pw1 and p_pw2):
                st.error("Todos los campos son obligatorios.")
            elif p_pw1 != p_pw2:
                st.error("Las contraseñas no coinciden.")
            else:
                # TODO: registrar en DB
                st.session_state.role = "paciente"
                st.session_state.paciente = {"id": 1, "nombre": p_name.strip()}
                st.success("Cuenta creada ✅"); st.rerun()

