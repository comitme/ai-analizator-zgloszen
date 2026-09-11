"""Streamlit entry point.

Navigation is declared here rather than relying on the ``pages/`` directory
convention, which would label the first entry with this file's name ("app"). Three
surfaces: try a ticket, work the queue, read the numbers.

Runs as its own container and reaches the API over HTTP only - see ui/api_client.py.
"""

import sys
from pathlib import Path

# Streamlit puts the *entry script's* directory on sys.path - that is ui/, not the
# project root - so `from ui.common import ...` inside the pages would not resolve.
# Adding the root here, before any page runs, makes `streamlit run ui/app.py` work
# from anywhere without PYTHONPATH, and keeps the import path identical to the one
# the tests use.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402 - must follow the sys.path fix above

st.set_page_config(page_title="Analizator zgłoszeń", page_icon="📮", layout="wide")

nawigacja = st.navigation(
    [
        st.Page("views/nowe_zgloszenie.py", title="Nowe zgłoszenie", icon="📮", default=True),
        st.Page("views/kolejka.py", title="Kolejka", icon="📥"),
        st.Page("views/odpowiedzi.py", title="Odpowiedzi modelu", icon="✉️"),
        st.Page("views/metryki.py", title="Metryki", icon="📊"),
    ]
)
nawigacja.run()
