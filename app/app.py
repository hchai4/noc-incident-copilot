import sys
from pathlib import Path

# `streamlit run app/app.py` puts `app/` on sys.path, not the repo root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
from dotenv import load_dotenv

from common import bootstrap

load_dotenv()
st.set_page_config(page_title="NOC Agent | Evals & Guardrails", page_icon=":material/lan:", layout="wide")
bootstrap()

page = st.navigation(
    [
        st.Page("app_pages/evals.py", title="Eval dashboard", icon=":material/fact_check:", default=True),
        st.Page("app_pages/guardrails.py", title="Guardrail lab", icon=":material/shield:"),
        st.Page("app_pages/console.py", title="Dispatch console", icon=":material/support_agent:"),
    ],
    position="top",
)
page.run()
