"""Streamlit entry point.

Navigation is declared here rather than relying on the ``pages/`` directory
convention, which would label the first entry with this file's name ("app"). Three
surfaces: try a ticket, work the queue, read the numbers.

Runs as its own container and reaches the API over HTTP only - see ui/api_client.py.
"""

import streamlit as st

st.set_page_config(page_title="Analizator zgłoszeń", page_icon="📮", layout="wide")

nawigacja = st.navigation(
    [
        st.Page("views/nowe_zgloszenie.py", title="Nowe zgłoszenie", icon="📮", default=True),
        st.Page("views/kolejka.py", title="Kolejka", icon="📥"),
        st.Page("views/metryki.py", title="Metryki", icon="📊"),
    ]
)
nawigacja.run()
