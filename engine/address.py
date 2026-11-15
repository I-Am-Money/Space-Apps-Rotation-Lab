# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Street address to location, anywhere in the United States, using the US Census Bureau Geocoder (free, no key).

    geocode("123 Main St, Ames, IA") -> {"lat", "lon", "matched_address", "state", "state_fips", "county", "county_fips"}

Source: https://geocoding.geo.census.gov/geocoder/ (geographies/onelineaddress, benchmark Public_AR_Current).
Privacy: the address is sent to the Census service and nowhere else. Results are kept only in this process's memory
(a small cache), never written to disk, never logged.
"""
from __future__ import annotations

from functools import lru_cache

import requests

URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
MAX_LEN = 200
ATTEMPTS = 3


class AddressNotFound(ValueError):
    """The service answered but found no US match for this address."""


class AddressLookupError(RuntimeError):
    """The service could not be reached or answered with an error."""


@lru_cache(maxsize=32)
def _lookup(address: str) -> dict:
    last = None
    for _ in range(ATTEMPTS):                       # one network blip should not send a farmer away
        try:
            r = requests.get(URL, params={"address": address, "benchmark": "Public_AR_Current", "vintage": "Current_Current",
                                          "format": "json"}, timeout=(5, 15), headers={"User-Agent": "RotationLab/1.0"})
            r.raise_for_status()
            matches = r.json()["result"]["addressMatches"]
            break
        except (requests.RequestException, ValueError, KeyError) as e:
            last = e
    else:
        raise AddressLookupError("The address service could not be reached. Try again, or click your field on the map.") from last
    if not matches:
        raise AddressNotFound("No United States match for that address. Include the street number, town and state, "
                              "or click your field on the map. This lookup covers US addresses only.")
    m = matches[0]
    geo = m.get("geographies", {})
    county = (geo.get("Counties") or [{}])[0]
    state = (geo.get("States") or [{}])[0]
    return {"lat": float(m["coordinates"]["y"]), "lon": float(m["coordinates"]["x"]), "matched_address": m.get("matchedAddress", ""),
            "state": state.get("STUSAB") or m.get("addressComponents", {}).get("state"), "state_fips": state.get("STATE") or county.get("STATE"),
            "county": county.get("BASENAME") or county.get("NAME"), "county_fips": (county.get("STATE", "") + county.get("COUNTY", "")) or None}


def geocode(address: str) -> dict:
    a = " ".join(str(address or "").split())
    if len(a) < 5:
        raise AddressNotFound("Enter a street address with the town and state.")
    if len(a) > MAX_LEN:
        raise AddressNotFound("That address is too long. Enter just the street, town and state.")
    return dict(_lookup(a))
