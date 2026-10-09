"""Versioned identity rules (Step 04.3, 04.4). Every link and query plan records this version.

Scores rank candidates for thresholds only. They are not probabilities and are never shown as one.
Change a weight or list here, bump RULES_VERSION and rerun the identity evaluation.
"""

from __future__ import annotations

RULES_VERSION = "identity-rules.1.1"  # 1.1: Devanagari locality, city and digit forms (I19)

# Deterministic signal weights (0-1000 after capping).
WEIGHTS = {
    "rera_id": 600,
    "project_name": 400,
    "approved_alias": 350,
    "approved_alias_context": 250,
    "phase_name": 100,
    "developer": 100,
    "locality": 150,
    "micromarket": 50,
    "city": 50,
}
MAX_SCORE = 1000
# An automatic match needs this score and a strong combination (a RERA ID, or a name with its place or developer).
AUTO_ACCEPT_SCORE = 550

CITY_SYNONYMS: dict[str, list[str]] = {
    "gurgaon": ["gurugram", "गुड़गांव", "गुड़गाँव", "गुडगांव", "गुरुग्राम"],
    "gurugram": ["gurgaon", "गुड़गांव", "गुड़गाँव", "गुडगांव", "गुरुग्राम"],
    "bangalore": ["bengaluru"],
    "bengaluru": ["bangalore"],
    "bombay": ["mumbai"],
    "mumbai": ["bombay"],
    "new delhi": ["delhi"],
    "delhi": ["new delhi"],
}

# Hindi (Devanagari) spellings of locality words, so "सेक्टर 102" reads as "sector 102" (I19). Only words in the
# catalogue's localities; extend with the catalogue.
LOCALITY_SCRIPT_FORMS: dict[str, list[str]] = {
    "sector": ["सेक्टर"],
    "manesar": ["मानेसर"],
}

# Cities that reveal a same-name project elsewhere. A match naming one of these but not the project's own
# city is rejected; naming both goes to review.
KNOWN_CITIES = [
    # Hindi (Devanagari) names first (I19); a city's own forms are excluded through CITY_SYNONYMS
    "गुड़गांव",
    "गुड़गाँव",
    "गुडगांव",
    "गुरुग्राम",
    "दिल्ली",
    "नई दिल्ली",
    "नोएडा",
    "ग्रेटर नोएडा",
    "गाज़ियाबाद",
    "गाजियाबाद",
    "फरीदाबाद",
    "सोनीपत",
    "मुंबई",
    "पुणे",
    "बेंगलुरु",
    "हैदराबाद",
    "चेन्नई",
    "कोलकाता",
    "अहमदाबाद",
    "चंडीगढ़",
    "जयपुर",
    "लखनऊ",
    "gurgaon",
    "gurugram",
    "delhi",
    "new delhi",
    "noida",
    "greater noida",
    "ghaziabad",
    "faridabad",
    "sonipat",
    "mumbai",
    "navi mumbai",
    "thane",
    "pune",
    "bangalore",
    "bengaluru",
    "hyderabad",
    "chennai",
    "kolkata",
    "ahmedabad",
    "chandigarh",
    "mohali",
    "panchkula",
    "zirakpur",
    "jaipur",
    "lucknow",
    "indore",
    "bhopal",
    "kochi",
    "goa",
    "nagpur",
    "surat",
    "vadodara",
    "dehradun",
    "bhubaneswar",
    "coimbatore",
    "mysore",
    "dubai",
]

# Words that follow a number in listings. A phase name ending in a number ("M3M Antalya Hills 3") does not
# match when the next word is one of these ("M3M Antalya Hills 3 BHK").
UNIT_WORDS = {
    "bhk",
    "bhks",
    "bed",
    "beds",
    "bedroom",
    "bedrooms",
    "br",
    "rk",
    "sq",
    "sqft",
    "sqyd",
    "lakh",
    "lakhs",
    "lac",
    "lacs",
    "crore",
    "crores",
    "cr",
    "floor",
    "floors",
    "acre",
    "acres",
    "star",
    "years",
    "yrs",
}

# Numbering forms treated as the same phase number.
NUMERAL_FORMS = [["1", "i", "one"], ["2", "ii", "two"], ["3", "iii", "three"], ["4", "iv", "four"], ["5", "v", "five"]]

# Generic terms for the alias collision check (docs/04): an alias made only of these, of a developer name or of
# a place name is generic and can be approved only as context-required. Stylised spellings count ("parq").
GENERIC_TERMS = {
    "phase",
    "tower",
    "towers",
    "block",
    "wing",
    "west",
    "east",
    "north",
    "south",
    "central",
    "sector",
    "sec",
    "park",
    "parq",
    "parc",
    "heights",
    "height",
    "residency",
    "residences",
    "residence",
    "homes",
    "home",
    "city",
    "greens",
    "green",
    "hills",
    "hill",
    "gardens",
    "garden",
    "floors",
    "apartments",
    "apartment",
    "villas",
    "villa",
    "plots",
    "plaza",
    "commercial",
    "retail",
    "mall",
    "estate",
    "estates",
    "enclave",
    "vista",
    "view",
    "square",
    "one",
    "the",
    "new",
    "old",
    "project",
    "society",
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "1",
    "2",
    "3",
    "4",
    "5",
    "01",
    "02",
    "03",
    "in",
    "by",
    "at",
    "of",
    "and",
}

# Query builder (04.3): bounded and deduplicated.
QUERY_RULES_VERSION = "query-rules.1.0"
MAX_QUERIES_PER_CONNECTOR = 12
# Within a priority, names approved from proposals come first: finding them is the point of discovery (D17).
ALIAS_ORIGIN_ORDER = {"approved_proposal": 0, "input_file": 1, "configuration": 2, "rera_registered_name": 3}
QUERY_PRIORITY = {"identifier": "high", "project_name": "high", "phase_name": "normal", "approved_alias": "normal"}

# A01 identity agent (04.4): bounded input per task.
A01_MAX_SEGMENTS = 10
A01_MAX_CHARS_PER_SEGMENT = 2000
EVIDENCE_MAX_CHARS = 4000
