"""Which state RERA registry covers a project (Step 08 close-out; D57).

Projects can be anywhere in India, and each state runs its own RERA portal with its own layout. A project's state
comes from its `state` field when the input gives one, otherwise from its city (the table below lists the cities of
the main property markets; it grows as projects are added). A run uses the reader built for that state; a state
without a reader is reported as `access_pending` with its name, never skipped silently and never looked up in another
state's registry. Haryana has its list reader (HRERA); 16 other states have the generic certificate reader
(app.connectors.state_registry); the rest are reported access_pending by name.
"""

from __future__ import annotations

from typing import Any

from app.identity.text import normalise_text


def _readers() -> dict[str, str]:
    from app.connectors.state_registry import PORTALS

    return {"haryana": "harera_registry", **{state: "state_registry" for state in PORTALS}}


CITY_STATE = {
    "haryana": [
        "gurgaon",
        "gurugram",
        "manesar",
        "faridabad",
        "panchkula",
        "sonipat",
        "sonepat",
        "karnal",
        "panipat",
        "ambala",
        "rohtak",
        "hisar",
        "rewari",
        "bahadurgarh",
        "dharuhera",
        "sohna",
    ],
    "maharashtra": [
        "mumbai",
        "navi mumbai",
        "thane",
        "pune",
        "pimpri chinchwad",
        "nagpur",
        "nashik",
        "kalyan",
        "panvel",
        "aurangabad",
        "mira bhayandar",
        "vasai",
        "virar",
    ],
    "karnataka": ["bengaluru", "bangalore", "mysuru", "mysore", "mangaluru", "mangalore", "hubballi", "hubli"],
    "uttar pradesh": ["noida", "greater noida", "ghaziabad", "lucknow", "kanpur", "agra", "varanasi", "meerut"],
    "telangana": ["hyderabad", "secunderabad", "warangal"],
    "tamil nadu": ["chennai", "coimbatore", "madurai", "tiruchirappalli"],
    "gujarat": ["ahmedabad", "gandhinagar", "surat", "vadodara", "rajkot"],
    "delhi": ["delhi", "new delhi"],
    "west bengal": ["kolkata", "howrah", "new town"],
    "rajasthan": ["jaipur", "udaipur", "jodhpur", "kota"],
    "punjab": ["mohali", "ludhiana", "amritsar", "jalandhar", "zirakpur", "kharar"],
    "madhya pradesh": ["indore", "bhopal", "gwalior", "jabalpur"],
    "kerala": ["kochi", "thiruvananthapuram", "kozhikode"],
    "andhra pradesh": ["visakhapatnam", "vijayawada", "amaravati", "guntur"],
    "goa": ["panaji", "margao", "goa"],
    "odisha": ["bhubaneswar", "cuttack"],
    "bihar": ["patna"],
    "uttarakhand": ["dehradun", "haridwar"],
}
STATE_OF_CITY = {normalise_text(city): state for state, cities in CITY_STATE.items() for city in cities}


def state_of(project: dict[str, Any]) -> str | None:
    """The project's state, from its input or its city; None when neither says."""
    given = normalise_text(project.get("state") or "")
    if given:
        return given
    return STATE_OF_CITY.get(normalise_text(project.get("city") or ""))


def reader_for(project: dict[str, Any]) -> tuple[str | None, str | None]:
    """(connector ID of the state's registry reader, or None; the reason when there is none)."""
    state = state_of(project)
    if state is None:
        return None, f"the state of {project.get('city') or 'this city'} is not known: add the project's state"
    connector = _readers().get(state)
    if connector is None:
        return None, f"no registry reader for {state.title()} yet (D57); the {state.title()} RERA portal is not read"
    return connector, None
