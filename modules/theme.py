import streamlit as st
from pathlib import Path

def apply_theme():
    css_path = Path("assets/theme.css")
    if css_path.exists():
        css = css_path.read_text(encoding="utf-8")
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

