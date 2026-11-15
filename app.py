import html
import inspect
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
if not data.is_mock() and any(v == "placeholder" for v in rec.get("badges", {}).get("econ_detail", {}).values()):
    st.warning("Profit rankings use unverified cost inputs. Review the assumptions in How Good Is This? before using a recommendation.")
elif not data.is_mock():
    st.caption("Cost basis: national A2+FL unit costs converted using district potential yields, unless replaced by local inputs. This is a planning assumption, not a farm cost observation.")
base_plan = ["rice"] * 4
same = top["plan"] == base_plan
md(f"""<div class="rl-mast"><div>
<div class="rl-brand">RotationLab</div>
<h1>A rice farm in Nalgonda, Telangana</h1>
<p class="lede">The farm grows rice every year today. Should some plots move to millets or pigeon pea when irrigation water is limited? Compare four-year plans against decades of real weather and find the water level where the answer changes.</p>
</div><div class="rl-plan"><p class="cap">Our farm today (Rotation A, the baseline)</p>{ribbon(base_plan, True)}
<p class="cap" style="margin-top:.8rem">{"Best plan for your inputs is the same as today" if same else "Best plan for your inputs"} {badge("placeholder" if data.is_mock() else "modeled")}</p>{"" if same else ribbon(top["plan"], True)}</div></div>""")
banner = st.empty()
md(f'<div class="rl-strip"><span><strong>{html.escape(JUDGMENT)}</strong></span><span>{html.escape(REGIONAL)}</span></div>')

TABS = ["My Field", "Compare Futures", "My Priorities", "Tipping Points", "How Good Is This?"]
VIEWS = (field, compare, priorities, tipping, hindcast)
if "on_change" in inspect.signature(st.tabs).parameters:
    tabs = st.tabs(TABS, key="nav", on_change="rerun")
    for tab, mod in zip(tabs, VIEWS):
        with tab:
            if tab.open:
                mod.render()
else:
    # Older Streamlit releases lack lazy tabs. Keep only the selected view running.
    active = st.segmented_control("View", TABS, default=TABS[0], key="nav") or TABS[0]
    VIEWS[TABS.index(active)].render()

if data.is_mock():
    banner.markdown('<div class="rl-mock">Mock data is on screen. Part of the decision engine is not connected yet, so some numbers below are placeholders and carry the yellow Placeholder badge.</div>', unsafe_allow_html=True)
