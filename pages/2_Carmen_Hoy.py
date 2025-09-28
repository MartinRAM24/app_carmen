# pages/2_Carmen_Hoy.py
import streamlit as st
from modules.core import df_sql


st.set_page_config(page_title="Carmen — Hoy", page_icon="📅", layout="wide")

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

