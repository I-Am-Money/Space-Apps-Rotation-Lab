# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Find my land from an address (US). Plain Streamlit only; labels use badge() from ui/components.py.

The farmer types a street address. We find the spot (US Census Geocoder) and read what was grown there in the last
years (USDA NASS Cropland Data Layer). The farmer then confirms or clears it. Only after "Yes" do the pin, the crop
plan and the data load happen. Nothing is saved: the address and results live in this browser session only.

Not connected yet, and said so on screen: who owns the land and the exact field boundary. Those are county records.
"""
from __future__ import annotations

import streamlit as st

from engine import address, fetch_cdl
from ui.recommendations import crop_label, show_badge

NOT_CONNECTED = ("Land ownership and the exact field boundary come from county records, which are not connected yet. "
                 "Please check that the pin is on your field and that the crops below are right.")


def _is_cropland(history) -> bool:
    return bool(history) and any(r["supported"] for r in history[-2:])


def _lookup(addr: str) -> None:
    st.session_state.pop("v4_found", None)
    try:
        with st.spinner("Finding your address…"):
            geo = address.geocode(addr)
        with st.spinner("Reading the satellite crop record for the last five years…"):
            hist = fetch_cdl.crop_history(geo["lat"], geo["lon"])
        found = {"geo": geo, "history": hist, "moved": None}
        if not _is_cropland(hist):
            # A street address lands on the farmhouse or the road. Look around for the nearest cropland.
            with st.spinner("Your address is not on cropland, so we are looking around it for the nearest field…"):
                near = fetch_cdl.nearest_cropland(geo["lat"], geo["lon"])
            if near:
                with st.spinner("Reading the crop record at that field…"):
                    found["history"] = fetch_cdl.crop_history(near["lat"], near["lon"])
                found["moved"] = {**near, "address_category": next((r["category"] for r in reversed(hist) if r["category"]), "a non-crop area")}
        found["suggest"] = fetch_cdl.suggest_plan(found["history"])
        st.session_state["v4_found"] = found
    except (address.AddressNotFound, address.AddressLookupError) as e:
        st.warning(str(e))
    except ValueError as e:                       # outside the lower 48: we have the spot but no crop record
        st.session_state["v4_found"] = {"geo": geo, "history": None, "suggest": None, "moved": None, "note": str(e)}


def _apply() -> None:
    f = st.session_state.get("v4_found") or {}
    geo = f.get("geo")
    if not geo:
        return
    spot = f.get("moved") or geo                  # the cropland we found near the address, else the address itself
    st.session_state["_v4_pending_pin"] = (round(spot["lat"], 5), round(spot["lon"], 5))
    st.session_state.update(v4_lat=round(spot["lat"], 5), v4_lon=round(spot["lon"], 5))
    st.session_state["v4_cdl_plan"] = (f.get("suggest") or {}).get("plan") or []
    st.session_state["_v4_autoload"] = True
    st.session_state["v4_found_applied"] = True


def _clear() -> None:
    for k in ("v4_found", "v4_found_applied", "v4_cdl_plan"):
        st.session_state.pop(k, None)


def _confirm(f: dict) -> None:
    geo = f["geo"]
    st.write(f"**We found:** {geo['matched_address'].title()}" + (f" · {geo['county']} County, {geo['state']}" if geo.get("county") else ""))
    show_badge("observed")
    st.caption("Source: US Census Bureau Geocoder.")
    hist = f.get("history")
    moved = f.get("moved")
    if moved:
        st.info(f"Your address is on {moved['address_category'].lower()}, such as a house or road, not a field. The nearest cropland we found "
                f"is about {moved['distance_m']} m {moved['direction']} of it, so the crop record and the map pin below use that spot. "
                "If your field is somewhere else, click it on the map after applying.")
    elif hist is not None and not any(r["supported"] for r in hist):
        st.warning("We found no cropland within about 450 m of this address. You can still apply the location, then click your field on the map.")
    if hist is None:
        st.info(f.get("note", "No crop record for this spot."))
    else:
        rows = [{"Year": r["year"], "What the satellite record shows": r["category"] or "no data",
                 "Used as your crop": crop_label(r["crop"]) if r["crop"] else "not a crop we plan"} for r in hist]
        st.table(rows)
        show_badge("observed")
        st.caption("Source: USDA NASS Cropland Data Layer, a satellite-based map at 30 m. It can misclassify a pixel, so please confirm.")
        for m in (f.get("suggest") or {}).get("messages", []):
            st.caption(m)
    st.info(NOT_CONNECTED)
    st.write("Is this your land?")
    a, b = st.columns(2)
    a.button("Yes, use this location and these crops", type="primary", on_click=_apply, key="v4_addr_yes")
    b.button("No, clear it", on_click=_clear, key="v4_addr_no")


def render() -> None:
    with st.expander("Find my land from a US address", expanded=bool(st.session_state.get("v4_found")) or "v4_site" not in st.session_state):
        st.caption("Your address is sent to the US Census geocoder to find the spot. It is not saved. "
                   "Outside the US, or if the lookup misses, click your field on the map instead.")
        addr = st.text_input("Street address, town and state", placeholder="123 County Road 5, Ames, IA", key="v4_addr")
        if st.button("Look up this address", key="v4_addr_go") and addr.strip():
            _lookup(addr)
        f = st.session_state.get("v4_found")
        if f and st.session_state.get("v4_found_applied"):
            st.success("Location and crop history applied below. Check the farm size and water, then continue.")
        elif f:
            _confirm(f)
