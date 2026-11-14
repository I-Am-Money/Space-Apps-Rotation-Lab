"""Small HTML components. All numbers passed in come from the engine; nothing is computed here
except display formatting."""
from __future__ import annotations

import html

import streamlit as st

from ui.theme import BADGES, CROP_COLOR, CROP_LABEL

DISCLAIMER = "Modeled estimates for planning. Not a guarantee of yield or profit."
JUDGMENT = "This tool supports, and does not replace, the judgment of the farmer and local experts."
REGIONAL = ("Weather and soil moisture come from regional NASA estimates for a grid cell around the farm location, "
            "not from measurements on your field.")

_DARK_TEXT = {"jowar", "pigeonpea"}


def badge(kind: str) -> str:
    label, cls, tip = BADGES.get(kind or "placeholder", BADGES["placeholder"])
    return f'<span class="rl-badge {cls}" title="{html.escape(tip)}">{label}</span>'


def md(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def fmt_rs(x, lakh: bool = False) -> str:
    if x is None:
        return "n/a"
    sign = "-" if x < 0 else ""
    x = abs(float(x))
    return f"{sign}Rs {x:,.0f}"


def stat(label, value, unit="", badge_kind="placeholder", note="") -> str:
    n = f'<div class="n">{note}</div>' if note else ""
    u = f'<span class="u">{unit}</span>' if unit else ""
    return (f'<div class="rl-stat"><div class="l">{label}</div><div class="v">{value}{u}</div>{n}'
            f'<div class="b">{badge(badge_kind)}</div></div>')


def stats(items: list[str]) -> None:
    md('<div class="rl-stats">' + "".join(items) + "</div>")


def ribbon(plan: list[str], small: bool = False) -> str:
    cells = []
    for i, c in enumerate(plan):
        cls = "rl-yr dark" if c in _DARK_TEXT else "rl-yr"
        cells.append(f'<div class="{cls}" style="background:{CROP_COLOR[c]}"><b>Year {i + 1}</b><span>{CROP_LABEL[c]}</span></div>')
    return f'<div class="rl-ribbon{" sm" if small else ""}">' + "".join(cells) + "</div>"


def tab_head(title: str, lede: str) -> None:
    md(f'<div class="rl-tabhead"><h2>{title}</h2><p>{lede}</p></div>'
       f'<p class="rl-disclaim">{DISCLAIMER} {JUDGMENT}</p>')


def section(title: str, badge_kind: str | None = None, lede: str = "") -> None:
    b = f" {badge(badge_kind)}" if badge_kind else ""
    l = f'<p style="color:var(--ink2);margin:0 0 .4rem">{lede}</p>' if lede else ""
    md(f'<h3 class="rl-h">{title}{b}</h3>{l}')


def legend(items: list[tuple[str, str]]) -> None:
    md('<div class="rl-legend">' + "".join(f'<span><i style="background:{c}"></i>{html.escape(n)}</span>' for n, c in items) + "</div>")


def bullets(title: str, items) -> str:
    if not items:
        return ""
    return f'<div class="sub">{title}</div><ul>' + "".join(f"<li>{html.escape(str(i))}</li>" for i in items) + "</ul>"


def srcline(text: str, label: str = "Source") -> None:
    md(f'<p class="rl-srcline"><b>{label}:</b> {html.escape(text)}</p>')


def delta_html(v, fmt="{:,.0f}", unit="", good_when_up=True) -> str:
    """Signed difference from baseline. Sign is shown in text so colour is never the only cue."""
    if v is None:
        return "n/a"
    if abs(v) < 0.5:
        return f'<span class="rl-delta">same</span>'
    up = v > 0
    good = up == good_when_up
    sign = "+" if up else "-"
    return f'<span class="rl-delta {"up" if good else "dn"}">{sign}{fmt.format(abs(v))}{unit}</span>'


def table(headers: list[str], rows: list[list[str]]) -> None:
    th = "".join(f"<th>{h}</th>" for h in headers)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    md(f'<div class="rl-tblwrap"><table class="rl-t"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>')
