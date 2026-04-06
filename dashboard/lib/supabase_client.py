"""Supabase client singleton using Streamlit-native patterns."""
import streamlit as st
from supabase import Client, create_client


@st.cache_resource
def get_client() -> Client:
    """Create and cache a Supabase client using Streamlit secrets.

    Raises RuntimeError with setup instructions if secrets are missing.
    """
    try:
        url = st.secrets["SUPABASE_URL"]
    except KeyError:
        raise RuntimeError(
            "SUPABASE_URL not found in Streamlit secrets. "
            "Add to .streamlit/secrets.toml:\n\n"
            'SUPABASE_URL = "https://your-project.supabase.co"\n'
            'SUPABASE_KEY = "your-anon-key"'
        )
    try:
        key = st.secrets["SUPABASE_KEY"]
    except KeyError:
        raise RuntimeError(
            "SUPABASE_KEY not found in Streamlit secrets. "
            "Add to .streamlit/secrets.toml:\n\n"
            'SUPABASE_URL = "https://your-project.supabase.co"\n'
            'SUPABASE_KEY = "your-anon-key"'
        )
    return create_client(url, key)
