# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Presentation for the global planner; independent of the legacy farm theme.

Use public Streamlit container keys and semantic test IDs, never generated CSS
class names. Native widgets retain their labels, keyboard behavior and tooltips.
"""
import streamlit as st


def inject() -> None:
    st.html("""<style>
    :root {
      --rl-ink: #20342e; --rl-muted: #586b63; --rl-line: #dce5df;
      --rl-accent: #236653; --rl-soft: #edf4ef; --rl-surface: #ffffff;
    }
    .stApp { color: var(--rl-ink); }
    [data-testid="stMainBlockContainer"] {
      max-width: 1200px; padding: 3.5rem 2.5rem 5rem;
    }
    h1, h2, h3 { color: var(--rl-ink); letter-spacing: -.035em; }
    h1 { font-size: clamp(2rem, 3.5vw, 3rem); line-height: 1.12; font-weight: 700; }
    h2 { font-size: 2rem; line-height: 1.2; font-weight: 650; }
    h3 { font-size: 1.2rem; line-height: 1.35; font-weight: 650; }
    [data-testid="stCaptionContainer"] { color: var(--rl-muted); line-height: 1.55; }
    [data-testid="stMarkdownContainer"] p { line-height: 1.6; }
    [data-testid="stVerticalBlock"] { gap: 1rem; }
    [data-testid="stSidebar"] { background: #f0f3ef; border-right: 1px solid var(--rl-line); }
    [data-testid="stSidebarUserContent"] { padding-top: 2rem; }
    [data-testid="stSidebar"] h3 { font-size: 1.05rem; }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: .85rem; }
    .rl-brand { display: flex; gap: .65rem; align-items: center; margin-bottom: .4rem; }
    .rl-brand svg { width: 34px; height: 34px; flex-shrink: 0; }
    .rl-brand strong { font-size: 1.35rem; letter-spacing: -.045em; color: var(--rl-ink); }
    .st-key-rl_navigation [role="radiogroup"] { gap: .3rem; }
    .st-key-rl_navigation [role="radiogroup"] label {
      border-radius: 9px; padding: .55rem .65rem; margin: 0;
      min-height: 44px; transition: background-color 140ms ease;
    }
    .st-key-rl_navigation [role="radiogroup"] label:hover { background: #e4ece5; }
    .st-key-rl_navigation [role="radiogroup"] label:has(input:checked) {
      background: #dceadf; box-shadow: inset 3px 0 var(--rl-accent);
    }
    .st-key-rl_navigation [role="radiogroup"] label:has(input:checked) p { font-weight: 650; }
    [class*="st-key-rl_card_"], [class*="st-key-rl_pick_"],
    [class*="st-key-rl_question_"], .st-key-rl_headline, .st-key-rl_current {
      border-color: var(--rl-line) !important; border-radius: 14px !important;
      background: var(--rl-surface); padding: 1.35rem;
    }
    /* Keyed containers style only their own surface, never nested cards. */
    .st-key-rl_welcome {
      padding: 2.5rem !important; border-radius: 18px !important;
      border: 1px solid #d5e3d8 !important;
      background: linear-gradient(120deg, #eef5ec 0%, #f9fbf6 75%);
    }
    .st-key-rl_welcome h1 { max-width: 17ch; }
    .st-key-rl_welcome [data-testid="stMarkdownContainer"] p { max-width: 65ch; }
    .st-key-rl_welcome [data-testid="stCaptionContainer"] p { text-transform: uppercase; letter-spacing: .12em; font-size: .75rem; font-weight: 700; }
    .st-key-rl_headline { border: 1px solid #abc8b4 !important; border-top: 3px solid var(--rl-accent) !important; }
    .st-key-rl_current { background: var(--rl-soft) !important; }
    .st-key-rl_page_intro { margin-bottom: .4rem; }
    .st-key-rl_page_intro [data-testid="stCaptionContainer"]:first-child p {
      letter-spacing: .1em; font-size: .75rem; font-weight: 700; text-transform: uppercase;
    }
    .st-key-rl_secondary_plans [data-testid="stMetricValue"] { font-size: 1.55rem; }
    [data-testid="stMetric"] { min-width: 0; padding: .8rem 1rem; border-radius: 10px; border-color: var(--rl-line); }
    [data-testid="stMetricLabel"] p { font-size: .82rem; font-weight: 500; white-space: normal; color: var(--rl-muted); }
    [data-testid="stMetricValue"] { font-size: clamp(1.35rem, 2.4vw, 2rem); font-weight: 650; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
    [data-testid="stMetricDelta"] { font-size: .8rem; }
    [data-testid="stButton"] button, [data-testid="stDownloadButton"] button {
      min-height: 44px; border-radius: 9px; font-weight: 600;
      transition: border-color 140ms ease, background-color 140ms ease;
    }
    [data-testid="stButton"] button[kind="secondary"] { background: #fff; border-color: #cdd9d1; }
    [data-testid="stButton"] button[kind="secondary"]:hover { background: var(--rl-soft); border-color: var(--rl-accent); }
    [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input { font-variant-numeric: tabular-nums; }
    [data-testid="stTextInputRootElement"], [data-testid="stNumberInputContainer"], [data-baseweb="select"] > div {
      background: #fff; border-color: #cdd9d1; border-radius: 9px;
    }
    [data-testid="stTabs"] [role="tablist"] { gap: 1.5rem; border-bottom: 1px solid var(--rl-line); }
    [data-testid="stTabs"] button[role="tab"] { padding: .6rem 0; height: auto; min-height: 44px; white-space: nowrap; }
    [data-testid="stTabs"] button[aria-selected="true"] { font-weight: 650; }
    [data-testid="stExpander"] { background: #fff; border-color: var(--rl-line); border-radius: 10px; }
    [data-testid="stExpander"] summary { min-height: 44px; }
    [data-testid="stAlert"] { border-radius: 10px; }
    [data-testid="stMarkdownContainer"] table { width: 100%; font-size: .9rem; font-variant-numeric: tabular-nums; }
    [data-testid="stMarkdownContainer"] th { background: var(--rl-soft); color: var(--rl-muted); font-weight: 600; }
    [data-testid="stMarkdownContainer"] td, [data-testid="stMarkdownContainer"] th { padding: .65rem .75rem; border-color: var(--rl-line); }
    [data-testid="stMarkdownContainer"] a { text-underline-offset: 3px; }
    button:focus-visible, a:focus-visible, input:focus-visible, summary:focus-visible {
      outline: 3px solid #428a75 !important; outline-offset: 3px;
    }
    @media (max-width: 760px) {
      [data-testid="stMainBlockContainer"] { padding: 2rem 1rem 3rem; }
      .st-key-rl_welcome { padding: 1.5rem !important; }
      h2 { font-size: 1.7rem; }
      [data-testid="stTabs"] [role="tablist"] { gap: 1rem; }
      [data-testid="stMetricValue"] { font-size: 1.6rem; }
      [data-testid="stMarkdownContainer"] table { font-size: .8rem; }
      [data-testid="stMarkdownContainer"] td, [data-testid="stMarkdownContainer"] th { padding: .5rem; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { transition: none !important; scroll-behavior: auto !important; }
    }
    </style>""")


def brand() -> None:
    st.html('''<div class="rl-brand"><svg viewBox="0 0 40 40" aria-hidden="true" fill="none">
      <rect width="40" height="40" rx="11" fill="#236653"/>
      <path d="M12 27c0-12 7-16 17-16 0 11-4 18-14 17M13 28l12-13" stroke="#f1f7ef" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg><strong>RotationLab</strong></div>''')


def page_intro(step: str, title: str, description: str) -> None:
    with st.container(key="rl_page_intro"):
        st.caption(step)
        st.header(title)
        st.write(description)
