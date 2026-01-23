"""Text normalization utilities for fuzzy matching."""

import re
import unicodedata
from functools import lru_cache

# Montreal-specific abbreviations (lowercase -> expanded)
ABBREVIATIONS: dict[str, str] = {
    "st-": "saint-",
    "st ": "saint ",
    "ste-": "sainte-",
    "ste ": "sainte ",
    "boul.": "boulevard",
    "boul ": "boulevard ",
    "av.": "avenue",
    "av ": "avenue ",
    "ch.": "chemin",
    "ch ": "chemin ",
    "pl.": "place",
    "pl ": "place ",
    "rue ": "rue ",
    "mtl": "montreal",
    "mtée": "montee",
    "mtee": "montee",
}

# Cross-street separators
CROSS_STREET_SEPARATORS = re.compile(r"\s+(?:at|et|/|&|@|and|corner\s+of)\s+", re.IGNORECASE)

# Direction prefixes to strip
DIRECTION_PREFIXES = re.compile(r"^(?:to|vers|direction)\s+", re.IGNORECASE)


@lru_cache(maxsize=4096)
def remove_accents(text: str) -> str:
    """Remove accents from text.

    Example: "Préfontaine" -> "Prefontaine"
    """
    # Normalize to NFD (decomposes accented characters)
    normalized = unicodedata.normalize("NFD", text)
    # Remove combining diacritical marks
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


@lru_cache(maxsize=4096)
def normalize_text(text: str) -> str:
    """Normalize text for fuzzy matching.

    - Converts to lowercase
    - Removes accents
    - Expands abbreviations
    - Normalizes whitespace

    Example: "St-Michel / Boul. Crémazie" -> "saint-michel / boulevard cremazie"
    """
    # Lowercase
    result = text.lower().strip()

    # Remove accents
    result = remove_accents(result)

    # Expand abbreviations
    for abbrev, expanded in ABBREVIATIONS.items():
        result = result.replace(abbrev, expanded)

    # Normalize whitespace
    result = " ".join(result.split())

    return result


@lru_cache(maxsize=1024)
def parse_cross_street(query: str) -> tuple[str, str] | None:
    """Parse a cross-street query into two street names.

    Returns (street1, street2) if cross-street pattern detected, None otherwise.

    Examples:
        "Sherbrooke at Berri" -> ("sherbrooke", "berri")
        "St-Denis / Beaubien" -> ("saint-denis", "beaubien")
        "McGill" -> None
    """
    parts = CROSS_STREET_SEPARATORS.split(query)
    if len(parts) == 2:
        street1 = normalize_text(parts[0].strip())
        street2 = normalize_text(parts[1].strip())
        if street1 and street2:
            return (street1, street2)
    return None


def strip_direction_prefix(text: str) -> str:
    """Remove direction prefixes from headsign text.

    Example: "to Angrignon" -> "Angrignon"
    """
    return DIRECTION_PREFIXES.sub("", text).strip()


def extract_route_number(query: str) -> str | None:
    """Extract a route number from query text.

    Returns the route number if the query looks like a route number, None otherwise.

    Examples:
        "24" -> "24"
        "route 24" -> "24"
        "bus 747" -> "747"
        "the 80" -> "80"
        "green line" -> None
    """
    # Direct number
    if query.isdigit():
        return query

    # Pattern: "route X", "bus X", "line X", "the X"
    match = re.search(r"(?:route|bus|line|the)\s+(\d+)", query, re.IGNORECASE)
    if match:
        return match.group(1)

    # Pattern: "#X" or "no. X"
    match = re.search(r"(?:#|no\.?\s*)(\d+)", query, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


# Metro line aliases (normalized query -> route_id)
METRO_ALIASES: dict[str, str] = {
    # Green line (route_id=1)
    "green": "1",
    "green line": "1",
    "ligne verte": "1",
    "verte": "1",
    "vert": "1",
    # Orange line (route_id=2)
    "orange": "2",
    "orange line": "2",
    "ligne orange": "2",
    # Yellow line (route_id=4)
    "yellow": "4",
    "yellow line": "4",
    "ligne jaune": "4",
    "jaune": "4",
    # Blue line (route_id=5)
    "blue": "5",
    "blue line": "5",
    "ligne bleue": "5",
    "bleue": "5",
    "bleu": "5",
}


def get_metro_route_id(query: str) -> str | None:
    """Get metro route_id from an alias.

    Returns route_id if query matches a metro alias, None otherwise.

    Examples:
        "green line" -> "1"
        "ligne verte" -> "1"
        "orange" -> "2"
        "bus 24" -> None
    """
    normalized = normalize_text(query)
    return METRO_ALIASES.get(normalized)
