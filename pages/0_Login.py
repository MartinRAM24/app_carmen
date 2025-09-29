# pages/0_Login.py
import streamlit as st
from modules.core import is_admin_ok, login_paciente, registrar_paciente, normalize_tel
import base64
from urllib.parse import quote_plus

@st.cache_data
def load_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

logo_base64 = load_b64("assets/Logo.png")

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

ENABLE_SOCIAL = True   # cambia a True si lo quieres activar

tab_coach, tab_pac, tab_social = st.tabs(["👩‍⚕️ Coach", "🧑 Paciente", "📣 Redes"])

# ===== Coach =====
with tab_coach:
    st.subheader("Carmen (Coach)")
    with st.form("form_admin_login", clear_on_submit=False):
        a_user = st.text_input("Usuario", value="carmen", disabled=True, key="admin_user")
        a_pass = st.text_input("Contraseña", type="password", key="admin_pass")
        enviar_admin = st.form_submit_button("Entrar como Coach")
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
            enviar_login = st.form_submit_button("Entrar")
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
            enviar_reg = st.form_submit_button("Registrarme")

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

# Base64 de iconos (si ya tienes load_b64 arriba, esto va perfecto)
        ig_b64 = load_b64("assets/ig.png")
        ttk_b64 = load_b64("assets/tiktok.png")
        wa_b64 = load_b64("assets/wa.png")

        # Links
        IG_URL = "https://www.instagram.com/carmen._ochoa?igsh=dnd2aGt5a25xYTg0"
        TTK_PROFILE_URL = "https://www.tiktok.com/@carmen_ochoa123?_t=ZS-907SiUuhJDw&_r=1"
        TTK_VIDEO_ID = "7521784372152831240"
        TTK_EMBED_URL = f"https://www.tiktok.com/embed/v2/{TTK_VIDEO_ID}"

        WA_NUMBER = "523511974405"  # 52 + número sin signos
        WA_TEXT = "Hola Carmen, quiero una consulta."
        wa_link = f"https://wa.me/{WA_NUMBER}?text={quote_plus(WA_TEXT)}"
# ---- 📣 Redes (a la derecha)
with tab_social:
    if ENABLE_SOCIAL:
        st.subheader("Conecta con Carmen")

        # Fila de iconos clicables
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(
                f"""
                    <a href="{IG_URL}" target="_blank" rel="noopener">
                      <img src="data:image/png;base64,{ig_b64}"
                           alt="Instagram"
                           style="width:120px; border-radius:12px; display:block; margin:0 auto; cursor:pointer;">
                    </a>
                    """,
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
                    <a href="{TTK_PROFILE_URL}" target="_blank" rel="noopener">
                      <img src="data:image/png;base64,{ttk_b64}"
                           alt="TikTok"
                           style="width:120px; border-radius:12px; display:block; margin:0 auto; cursor:pointer;">
                    </a>
                    """,
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f"""
                    <a href="{wa_link}" target="_blank" rel="noopener">
                      <img src="data:image/png;base64,{wa_b64}"
                           alt="WhatsApp"
                           style="width:120px; border-radius:12px; display:block; margin:0 auto; cursor:pointer;">
                    </a>
                    """,
                unsafe_allow_html=True,
            )

        st.markdown("---")
        st.caption("🎥 Video destacado de TikTok")

        # ⚡ Render perezoso: solo carga el iFrame si el usuario lo pide
        show_video = st.toggle("Mostrar video", value=False, key="show_tiktok_embed")
        if show_video:
            st.components.v1.html(
                f"""
                    <div style="display:flex; justify-content:center;">
                        <iframe src="{TTK_EMBED_URL}"
                                width="350" height="600" frameborder="0"
                                allow="autoplay; encrypted-media"
                                allowfullscreen></iframe>
                    </div>
                    """,
                height=650,
            )
        else:
            # Alternativa ligera cuando el iFrame no está cargado
            st.link_button("Abrir video en TikTok", f"https://www.tiktok.com/@carmen_ochoa123/video/{TTK_VIDEO_ID}")

    else:
        st.info("⚡ Sección de redes desactivada temporalmente")


