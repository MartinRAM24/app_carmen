# pages/2_Carmen_Hoy.py
import streamlit as st
from modules.core import df_sql


st.set_page_config(page_title="Carmen — Hoy", page_icon="📅", layout="wide")

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

if st.session_state.get("role") != "admin":
    st.switch_page("app.py")

st.title("📅 Próximas citas")

# Hoy
d1 = df_sql("""
    SELECT c.fecha, c.hora, p.nombre, p.telefono, c.nota
    FROM citas c LEFT JOIN pacientes p ON p.id=c.paciente_id
    WHERE c.fecha = CURRENT_DATE
    ORDER BY c.hora
""")
st.subheader("Hoy")
if not d1.empty:
    st.dataframe(d1, use_container_width=True)
else:
    st.info("Sin citas hoy.")

# Siguientes 7 días
d7 = df_sql("""
    SELECT c.fecha, c.hora, p.nombre, p.telefono, c.nota
    FROM citas c LEFT JOIN pacientes p ON p.id=c.paciente_id
    WHERE c.fecha BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
    ORDER BY c.fecha, c.hora
""")
st.subheader("Próxima semana")
if not d7.empty:
    st.dataframe(d7, use_container_width=True)
else:
    st.info("Sin citas en la semana.")

st.divider()

# Atajos opcionales a otras páginas (si quieres; o confía en el sidebar)
if st.button("Ir a Gestión de Pacientes →"):
     st.switch_page("pages/3_Carmen_Pacientes.py")
if st.button("Ir a Gestión de Citas →"):
     st.switch_page("pages/4_Carmen_Citas.py")

# Cerrar sesión (sustituye al antiguo st.page_link)
if st.button("🚪 Cerrar sesión"):
    st.session_state.role = None
    st.session_state.paciente = None
    st.rerun()

