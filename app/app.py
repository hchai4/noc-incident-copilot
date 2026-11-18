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
st.set_page_config(page_title="NOC Incident Copilot", page_icon=":material/lan:", layout="wide")
bootstrap()

st.header("NOC Incident Copilot", divider="gray")
st.caption(
    "An AI copilot that turns a network alarm into a customer-ready incident email, grounded in runbooks and "
    "checked by safety guardrails before a human reviews it. Try the live console, then see how its "
    "quality is measured."
)

pages = [
    st.Page("app_pages/console.py", title="Dispatch console", icon=":material/support_agent:", default=True),
    st.Page("app_pages/evals.py", title="Eval dashboard", icon=":material/fact_check:"),
    st.Page("app_pages/guardrails.py", title="Guardrail lab", icon=":material/shield:"),
]
# Built-in top nav always renders above page content, so hide it and draw the tabs under the header.
page = st.navigation(pages, position="hidden")
with st.container(horizontal=True):
    for p in pages:
        st.page_link(p, width="content")
page.run()
