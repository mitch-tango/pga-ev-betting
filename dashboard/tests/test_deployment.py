"""Deployment validation tests.

Verify that all required deployment artifacts exist and are correctly configured.
These tests read files from disk relative to the dashboard directory — no Streamlit
or Supabase dependencies needed.
"""
import pathlib

DASHBOARD_DIR = pathlib.Path(__file__).resolve().parent.parent


def test_requirements_txt_exists_and_contains_core_deps():
    """requirements.txt must exist and list streamlit, supabase, plotly, pandas."""
    req_path = DASHBOARD_DIR / "requirements.txt"
    assert req_path.exists(), "dashboard/requirements.txt not found"
    content = req_path.read_text().lower()
    for dep in ("streamlit", "supabase", "plotly", "pandas"):
        assert dep in content, f"{dep} missing from requirements.txt"


def test_config_toml_exists_and_sets_dark_theme():
    """.streamlit/config.toml must exist and configure the dark theme."""
    config_path = DASHBOARD_DIR / ".streamlit" / "config.toml"
    assert config_path.exists(), "dashboard/.streamlit/config.toml not found"
    content = config_path.read_text()
    assert "dark" in content.lower(), "config.toml does not set dark theme"


def test_secrets_toml_in_gitignore():
    """dashboard/.streamlit/secrets.toml must be listed in the repo .gitignore."""
    repo_root = DASHBOARD_DIR.parent
    gitignore_paths = [
        repo_root / ".gitignore",
        DASHBOARD_DIR / ".gitignore",
    ]
    found = False
    for gi in gitignore_paths:
        if gi.exists():
            content = gi.read_text()
            if "secrets.toml" in content:
                found = True
                break
    assert found, "secrets.toml not found in any .gitignore"


def test_pycache_in_gitignore():
    """__pycache__/ must be covered by .gitignore."""
    repo_root = DASHBOARD_DIR.parent
    gitignore_paths = [
        repo_root / ".gitignore",
        DASHBOARD_DIR / ".gitignore",
    ]
    found = False
    for gi in gitignore_paths:
        if gi.exists():
            content = gi.read_text()
            if "__pycache__" in content:
                found = True
                break
    assert found, "__pycache__/ not found in any .gitignore"
