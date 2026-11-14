import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

st.set_page_config(page_title="RotationLab", page_icon="assets/favicon.svg", layout="wide", initial_sidebar_state="collapsed")

from ui import data, theme
from ui.components import JUDGMENT, REGIONAL, DISCLAIMER, badge, md, ribbon
from ui.tabs import compare, field, hindcast, priorities, tipping

theme.inject()
data.init_state()

p = data.params()
rec = data.recommend(p)
top = rec["top"]
md(f"""<div class="rl-mast"><div>
<div class="rl-brand">RotationLab</div>
<h1>What should follow what, when water is short?</h1>
<p class="lede">Compare four-year crop plans for rice, jowar, bajra and pigeon pea against decades of real weather, and see the water level where the best plan changes.</p>
</div><div class="rl-plan"><p class="cap">Best plan for your current inputs {badge("placeholder" if data.is_mock() else "modeled")}</p>{ribbon(top["plan"])}
</div></div>""")
banner = st.empty()
md(f'<div class="rl-strip"><span><strong>{html.escape(JUDGMENT)}</strong></span><span>{html.escape(REGIONAL)}</span></div>')

TABS = ["My Field", "Compare Futures", "My Priorities", "Tipping Points", "How Good Is This?"]
tabs = st.tabs(TABS, key="nav", on_change="rerun")
for tab, mod in zip(tabs, (field, compare, priorities, tipping, hindcast)):
    with tab:
        if tab.open:
            mod.render()

if data.is_mock():
    banner.markdown('<div class="rl-mock">Mock data is on screen. Part of the decision engine is not connected yet, so some numbers below are placeholders and carry the yellow Placeholder badge.</div>', unsafe_allow_html=True)
