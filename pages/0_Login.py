# pages/0_Login.py
import streamlit as st
from modules.core import is_admin_ok, login_paciente, registrar_paciente, normalize_tel

st.image("assets/Logo.png", width=200)
st.caption("Bienvenida/o. Elige cómo quieres entrar.")

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

