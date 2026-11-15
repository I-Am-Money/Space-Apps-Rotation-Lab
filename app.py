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
with st.spinner(data.MSG["recommend"]):
    rec = data.recommend(p)
top = rec["top"]
base_plan = ["rice"] * 4
same = top["plan"] == base_plan
_ph = data.placeholder_inputs()
draft_note = (f'<p class="cap" style="margin-top:.6rem"><strong>Draft.</strong> {len(_ph)} model inputs have no verified source yet '
              f'(listed under How Good Is This?). Treat this plan as a demonstration until they are replaced.</p>') if _ph else ""
md(f"""<div class="rl-mast"><div>
<div class="rl-brand">RotationLab</div>
<h1>A rice farm in Nalgonda, Telangana</h1>
<p class="lede">The farm grows rice every year today. Should some plots move to millets or pigeon pea when irrigation water is limited? Compare four-year plans against decades of real weather and find the water level where the answer changes.</p>
</div><div class="rl-plan"><p class="cap">Our farm today (Rotation A, the baseline)</p>{ribbon(base_plan, True)}
<p class="cap" style="margin-top:.8rem">{"Best plan for your inputs is the same as today" if same else "Best plan for your inputs"} {badge("placeholder" if data.is_mock() else "modeled")}</p>{"" if same else ribbon(top["plan"], True)}{draft_note}</div></div>""")
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
