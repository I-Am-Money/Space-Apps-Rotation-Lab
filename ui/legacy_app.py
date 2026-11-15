# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
import html
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st



from ui import data, theme
from ui.components import JUDGMENT, REGIONAL, badge, md, ribbon
from ui.tabs import compare, field, hindcast, priorities, tipping

def render():
    theme.inject()
    data.init_state()
    
    p = data.params()
    with st.spinner(data.MSG["recommend"]):
        rec = data.recommend(p)
    top = rec["top"]
    if not data.is_mock() and any(v == "placeholder" for v in rec.get("badges", {}).get("econ_detail", {}).values()):
        st.warning("Profit rankings use unverified cost inputs. Review the assumptions in How Good Is This? before using a recommendation.")
    elif not data.is_mock():
        st.caption("Costs use scaled Telangana A2+FL surveys for rice and pigeon pea and national unit-cost proxies for millets, unless replaced by local inputs. These are planning assumptions, not farm cost observations.")
    base_plan = ["rice"] * 4
    same = top["plan"] == base_plan
    _ph = data.placeholder_inputs()
    draft_note = (f'<p class="cap" style="margin-top:.6rem">{badge("placeholder")} {len(_ph)} model inputs in use have no verified source yet '
                  f'(listed under How Good Is This?). Treat this plan as a demonstration until they are replaced.</p>') if _ph else ""
    md(f"""<div class="rl-mast"><div>
    <div class="rl-brand">RotationLab</div>
    <h1>A rice farm in Nalgonda, Telangana</h1>
    <p class="lede">The farm grows rice every year today. Should some years move to millet or pigeon pea when irrigation water is limited? Compare four-year plans against decades of real weather and find the water level where the answer changes.</p>
    </div><div class="rl-plan"><p class="cap">Our farm today (Rotation A, the baseline)</p>{ribbon(base_plan, True)}
    <p class="cap" style="margin-top:.8rem">{"Best plan for your inputs is the same as today" if same else "Best plan for your inputs"} {badge("placeholder" if data.is_mock() else "modeled")}</p>{"" if same else ribbon(top["plan"], True)}{draft_note}</div></div>""")
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
