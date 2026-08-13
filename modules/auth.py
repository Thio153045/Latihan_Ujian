"""Resolusi API key Gemini: utamakan `.streamlit/secrets.toml`
(`GEMINI_API_KEY`), fallback ke input manual di sidebar (session_state)
kalau secret belum diatur. Dipanggil dari setiap halaman karena Streamlit
multipage app hanya menjalankan skrip halaman yang sedang aktif."""

import streamlit as st


def get_gemini_api_key() -> str:
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        secret_key = ""
    if secret_key:
        st.session_state["gemini_api_key"] = secret_key
        return secret_key
    return st.session_state.get("gemini_api_key", "")
