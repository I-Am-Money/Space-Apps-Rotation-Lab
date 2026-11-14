"""Design tokens (OKLCH source of truth) and the CSS injected into Streamlit."""
from __future__ import annotations

import math

import streamlit as st


def oklch(L: float, C: float, H: float) -> str:
    a, b = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bl = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_

    def enc(x):
        x = min(1.0, max(0.0, x))
        x = 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
        return round(min(1, max(0, x)) * 255)

    return "#%02x%02x%02x" % (enc(r), enc(g), enc(bl))


T = dict(
    bg=oklch(0.972, 0.008, 135),       # paddy mist
    surface=oklch(0.993, 0.004, 135),
    sunken=oklch(0.94, 0.014, 140),
    line=oklch(0.87, 0.016, 140),
    ink=oklch(0.24, 0.035, 220),        # monsoon slate
    ink2=oklch(0.40, 0.03, 220),
    ash=oklch(0.49, 0.025, 220),
    accent=oklch(0.45, 0.085, 205),     # monsoon water
    accent_soft=oklch(0.93, 0.03, 205),
    # crops: rice water-blue, jowar ochre, bajra clay, pigeon pea leaf green
    rice=oklch(0.46, 0.10, 240),
    jowar=oklch(0.76, 0.15, 85),
    bajra=oklch(0.46, 0.13, 30),
    pigeonpea=oklch(0.70, 0.15, 150),
    mixed=oklch(0.55, 0.02, 220),
    warn=oklch(0.90, 0.13, 95),
    warn_ink=oklch(0.33, 0.07, 80),
)
CROP_COLOR = {"rice": T["rice"], "jowar": T["jowar"], "bajra": T["bajra"], "pigeonpea": T["pigeonpea"]}
CROP_LABEL = {"rice": "Rice", "jowar": "Jowar", "bajra": "Bajra", "pigeonpea": "Pigeon pea"}
# rotation ids on the tipping grid and Pareto colouring
ROT_COLOR = {"A": T["rice"], "B": T["jowar"], "C": T["pigeonpea"], "current": T["bajra"]}

BADGES = {
    "observed": ("Observed", "obs", "Measured or officially published data."),
    "modeled": ("Modeled", "mod", "Computed by this tool's model."),
    "local": ("Local input", "loc", "Entered by you or taken from your own records."),
    "assumption": ("Assumption", "asm", "A parameter chosen with a stated range, not measured."),
    "placeholder": ("Placeholder", "ph", "Not real data yet. Do not use for decisions."),
}

FONTS = ("@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700"
         "&family=Source+Sans+3:wght@400;500;600;700&display=swap');")

CSS = FONTS + """
:root{
 --bg:%(bg)s;--surface:%(surface)s;--sunken:%(sunken)s;--line:%(line)s;--ink:%(ink)s;--ink2:%(ink2)s;--ash:%(ash)s;
 --accent:%(accent)s;--accent-soft:%(accent_soft)s;--rice:%(rice)s;--jowar:%(jowar)s;--bajra:%(bajra)s;--pigeonpea:%(pigeonpea)s;
 --warn:%(warn)s;--warn-ink:%(warn_ink)s;
 --serif:'Fraunces',Georgia,serif;--sans:'Source Sans 3',system-ui,sans-serif;
}
html,body,[data-testid="stAppViewContainer"],.stApp{background:var(--bg);color:var(--ink);font-family:var(--sans);}
[data-testid="stHeader"],[data-testid="stToolbar"],footer,#MainMenu,[data-testid="stDecoration"]{display:none!important;}
.block-container{max-width:1180px;padding:1.2rem 1.25rem 4rem;}
h1,h2,h3,h4{font-family:var(--serif);color:var(--ink);letter-spacing:-0.01em;font-weight:600;text-wrap:balance;}
p,li{font-size:1.02rem;line-height:1.55;max-width:70ch;color:var(--ink);}
a{color:var(--accent);text-underline-offset:3px;}
.stMarkdown p{margin-bottom:.6rem}

/* masthead */
.rl-mast{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:2rem;align-items:end;padding:1.2rem 0 1.4rem;border-bottom:1px solid var(--line);margin-bottom:.4rem}
.rl-brand{font-family:var(--serif);font-weight:700;font-size:1rem;color:var(--accent);letter-spacing:.01em;margin-bottom:.6rem}
.rl-mast h1{font-size:clamp(1.9rem,4.4vw,3.1rem);line-height:1.04;margin:0 0 .7rem;max-width:18ch}
.rl-mast .lede{font-size:1.12rem;color:var(--ink2);max-width:46ch;margin:0}
.rl-plan{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:1rem 1.1rem}
.rl-plan .cap{font-size:.86rem;color:var(--ash);margin:0 0 .5rem}
.rl-ribbon{display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin:.3rem 0 .5rem}
.rl-yr{border-radius:4px;padding:.55rem .5rem .5rem;color:#fff;min-height:3.3rem;display:flex;flex-direction:column;justify-content:space-between}
.rl-yr b{font-size:.74rem;font-weight:600;opacity:.92}
.rl-yr span{font-family:var(--serif);font-size:1rem;font-weight:600;line-height:1.1}
.rl-yr.dark{color:var(--ink)}
.rl-ribbon.sm .rl-yr{min-height:2.4rem;padding:.35rem .4rem}.rl-ribbon.sm .rl-yr span{font-size:.86rem}

.rl-note{font-size:.92rem;color:var(--ink2);margin:.5rem 0 0;max-width:none}
.rl-strip{display:flex;flex-wrap:wrap;gap:.35rem 1.4rem;font-size:.92rem;color:var(--ink2);padding:.65rem 0 .2rem}
.rl-strip strong{color:var(--ink)}
.rl-mock{background:var(--warn);color:var(--warn-ink);border-radius:8px;padding:.6rem .9rem;font-weight:600;margin:.8rem 0 0;font-size:.95rem}

/* tabs */
[data-baseweb="tab-list"]{gap:.2rem;border-bottom:1px solid var(--line);overflow-x:auto;scrollbar-width:none}
[data-baseweb="tab"]{height:auto!important;padding:.75rem .9rem!important;font-family:var(--sans)!important;font-weight:600;color:var(--ink2)!important;background:transparent!important;white-space:nowrap}
[data-baseweb="tab"] p{font-size:1.08rem!important;font-weight:600}
[aria-selected="true"][data-baseweb="tab"]{color:var(--ink)!important}
[data-baseweb="tab-highlight"]{background:var(--accent)!important;height:3px!important}
[data-baseweb="tab-border"]{display:none}
.rl-tabhead{padding:1.1rem 0 .3rem}
.rl-tabhead h2{font-size:clamp(1.5rem,3vw,2.1rem);margin:0 0 .35rem}
.rl-tabhead p{color:var(--ink2);margin:0}
.rl-disclaim{font-size:.88rem;font-weight:600;color:var(--ink2);margin:0 0 .7rem;padding-bottom:.55rem;border-bottom:1px dashed var(--line);max-width:none}
h3.rl-h{font-size:1.25rem;margin:1.8rem 0 .3rem}

/* badges */
.rl-badge{display:inline-flex;align-items:center;gap:.3rem;font-size:.72rem;font-weight:700;letter-spacing:.01em;padding:.12rem .5rem .12rem .4rem;border-radius:999px;vertical-align:middle;white-space:nowrap;line-height:1.35}
.rl-badge::before{content:"";width:.5rem;height:.5rem;background:currentColor;flex:none}
.rl-badge.obs{background:%(b_obs)s;color:%(t_obs)s}.rl-badge.obs::before{border-radius:50%%}
.rl-badge.mod{background:%(b_mod)s;color:%(t_mod)s}.rl-badge.mod::before{background:transparent;border:2px solid currentColor;border-radius:50%%;width:.55rem;height:.55rem;box-sizing:border-box}
.rl-badge.loc{background:%(b_loc)s;color:%(t_loc)s}.rl-badge.loc::before{border-radius:1px}
.rl-badge.asm{background:%(b_asm)s;color:%(t_asm)s;box-shadow:inset 0 0 0 1px %(l_asm)s}.rl-badge.asm::before{transform:rotate(45deg) scale(.85)}
.rl-badge.ph{background:var(--warn);color:var(--warn-ink);box-shadow:inset 0 0 0 1px %(l_ph)s}.rl-badge.ph::before{clip-path:polygon(50%% 0,100%% 100%%,0 100%%)}

/* stats */
.rl-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:.6rem 0}
.rl-stat{padding:.9rem 1rem .9rem 0;}
.rl-stat+.rl-stat{padding-left:1rem;border-left:1px solid var(--line)}
.rl-stat .l{font-size:.9rem;color:var(--ink2);margin-bottom:.15rem}
.rl-stat .v{font-family:var(--serif);font-size:clamp(1.7rem,3vw,2.3rem);font-weight:600;line-height:1.05;font-variant-numeric:tabular-nums;color:var(--ink)}
.rl-stat .u{font-size:.95rem;font-family:var(--sans);font-weight:500;color:var(--ink2);margin-left:.25rem}
.rl-stat .n{font-size:.84rem;color:var(--ash);margin-top:.25rem}
.rl-stat .b{margin-top:.4rem}

/* panels */
.rl-panel{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:1.1rem 1.25rem;margin:.6rem 0}
.rl-panel h4{margin:0 0 .4rem;font-size:1.15rem}
.rl-panel ul{margin:.2rem 0 .6rem 1.1rem;padding:0}
.rl-panel li{font-size:.97rem;margin-bottom:.2rem}
.rl-panel .sub{font-weight:700;font-size:.88rem;color:var(--ink2);margin:.7rem 0 .15rem}
.rl-hero{background:var(--ink);color:#f1f6f3;border-radius:10px;padding:1.3rem 1.5rem;margin:.8rem 0}
.rl-hero p,.rl-hero h4,.rl-hero li{color:#f1f6f3}
.rl-hero h4{font-size:1.5rem;margin:.1rem 0 .5rem}
.rl-hero .rl-badge{box-shadow:none}
.rl-callout{border:1px solid var(--line);background:var(--accent-soft);border-radius:10px;padding:.9rem 1.1rem;margin:.6rem 0;color:var(--ink)}
.rl-callout p{max-width:none;margin:0}
.rl-q{font-family:var(--serif);font-size:1.18rem;font-weight:600;margin:.1rem 0 .3rem;max-width:36ch;line-height:1.25}
.rl-evpi{font-family:var(--serif);font-size:2rem;font-weight:600;font-variant-numeric:tabular-nums}
.rl-legend{display:flex;flex-wrap:wrap;gap:.3rem 1.2rem;font-size:.92rem;color:var(--ink);margin:.3rem 0 .6rem}
.rl-legend i{display:inline-block;width:.8rem;height:.8rem;border-radius:2px;margin-right:.4rem;vertical-align:-1px}
.rl-src li{font-size:.97rem}
.rl-src .st{font-size:.8rem;color:var(--ash)}

/* widgets */
[data-testid="stWidgetLabel"] p,label p{font-size:.98rem!important;font-weight:600;color:var(--ink)}
.stSlider [data-baseweb="slider"] [role="slider"]{background:var(--accent)!important;box-shadow:none!important}
[data-testid="stSliderThumbValue"],[data-testid="stTickBarMin"],[data-testid="stTickBarMax"]{color:var(--ink2)!important}
div[data-baseweb="select"]>div,div[data-baseweb="input"]>div,input{background:var(--surface)!important;border-color:var(--line)!important;border-radius:6px!important}
[data-testid="stExpander"]{border:1px solid var(--line)!important;border-radius:8px!important;background:var(--surface)}
[data-testid="stExpander"] summary p{font-size:.97rem;font-weight:600}
[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:8px}
button:focus-visible,[role="tab"]:focus-visible,a:focus-visible{outline:3px solid var(--accent)!important;outline-offset:2px}
.stPlotlyChart{margin:.2rem 0}
iframe[title*="folium"],iframe{border-radius:8px}

@media (max-width:760px){
 .block-container{padding:.8rem .9rem 3rem}
 .rl-mast{grid-template-columns:1fr;gap:1rem}
 .rl-stat{padding:.75rem .5rem .75rem 0}
 .rl-stat+.rl-stat{padding-left:.7rem}
 [data-baseweb="tab"]{padding:.7rem .65rem!important}
 .rl-hero{padding:1rem}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


def inject() -> None:
    vals = dict(T)
    vals.update(
        b_obs=oklch(0.92, 0.05, 150), t_obs=oklch(0.32, 0.08, 150),
        b_mod=oklch(0.92, 0.04, 235), t_mod=oklch(0.32, 0.09, 235),
        b_loc=oklch(0.92, 0.05, 45), t_loc=oklch(0.38, 0.11, 40),
        b_asm=oklch(0.95, 0.008, 220), t_asm=oklch(0.38, 0.03, 220), l_asm=oklch(0.78, 0.02, 220),
        l_ph=oklch(0.70, 0.12, 90),
    )
    st.markdown("<style>" + (CSS % vals) + "</style>", unsafe_allow_html=True)
