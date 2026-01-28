import re
import unicodedata
from functools import lru_cache

# French article patterns to collapse (order matters - longer patterns first)
# "de la fontaine" -> "delafontaine", "l'acadie" -> "lacadie", etc.
FRENCH_ARTICLE_PATTERNS = [
    (re.compile(r"\bde l'(\w)", re.IGNORECASE), r"del\1"),  # de l'X -> delX
    (re.compile(r"\bde la[\s-]+", re.IGNORECASE), "dela"),  # de la X -> delaX
    (re.compile(r"\bl'(\w)", re.IGNORECASE), r"l\1"),  # l'X -> lX
    (re.compile(r"\b(la|le|du|de|des|les|aux)[\s-]+", re.IGNORECASE), r"\1"),  # la X -> laX
]

# Generic tokens to ignore in coverage calculations
GENERIC_TOKENS = frozenset({
    "station", "metro", "arret", "stop", "bus", "gare",
    "nord", "sud", "est", "ouest", "north", "south", "east", "west",
})

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

# Cross-street separators (includes " / " and " - " as STM uses both)
CROSS_STREET_SEPARATORS = re.compile(
    r"\s+(?:at|et|/|-|&|@|and|corner\s+of)\s+", re.IGNORECASE
)

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
    - Collapses French articles (la/le/du/de/des/les/aux + word)
    - Expands abbreviations
    - Normalizes whitespace

    Example: "St-Michel / Boul. Crémazie" -> "saint-michel / boulevard cremazie"
    Example: "Parc La Fontaine" -> "parc lafontaine"
    """
    # Lowercase
    result = text.lower().strip()

    # Remove accents
    result = remove_accents(result)

    # Collapse French articles with following word
    # "la fontaine" -> "lafontaine", "de l'acadie" -> "delacadie"
    for pattern, replacement in FRENCH_ARTICLE_PATTERNS:
        result = pattern.sub(replacement, result)

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


def get_meaningful_tokens(text: str) -> set[str]:
    """Extract tokens from normalized text, excluding generic/noise words.

    Used for token coverage scoring to avoid inflating matches on common words.
    Also expands article-prefixed tokens (duparc -> {duparc, parc}) to improve
    matching when users omit articles.

    Example: "station berri-uqam" -> {"berri", "uqam"}
    Example: "du Parc-La Fontaine / Rachel" -> {"duparc", "parc", "lafontaine", "fontaine", "rachel"}
    """
    normalized = normalize_text(text)
    # Split on whitespace and common separators
    raw_tokens = re.split(r"[\s/\-]+", normalized)
    # Filter out generic tokens and short tokens
    tokens = {t for t in raw_tokens if t and len(t) > 1 and t not in GENERIC_TOKENS}

    # Expand article-prefixed tokens: "duparc" -> also include "parc"
    # This helps match queries like "parc" to stop names like "du Parc"
    #
    # Only expand unambiguous prefixes to avoid false positives on proper names.
    # "la"/"le"/"l'" are skipped because they conflict with names like
    # Laurier, Lionel, Lesage, Lambert, etc. Fuzzy matching handles these.
    expanded = set()
    for token in tokens:
        stem = None

        # Longer compound prefixes (require stem >= 3 chars)
        for prefix in ("dela", "des", "aux"):
            if token.startswith(prefix) and len(token) >= len(prefix) + 3:
                stem = token[len(prefix):]
                break

        # "du"/"de" prefixes (require stem >= 3 chars)
        if stem is None:
            for prefix in ("du", "de"):
                if token.startswith(prefix) and len(token) >= len(prefix) + 3:
                    stem = token[len(prefix):]
                    break

        # "la"/"le" prefixes - very conservative (require stem >= 7 chars)
        # This catches "lafontaine" -> "fontaine" (8 chars) but avoids
        # "laurier" -> "urier" (5 chars), "lionel" -> "ionel" (5 chars)
        if stem is None:
            for prefix in ("la", "le"):
                if token.startswith(prefix) and len(token) >= len(prefix) + 7:
                    stem = token[len(prefix):]
                    break

        if stem and stem not in GENERIC_TOKENS:
            expanded.add(stem)

    return tokens | expanded


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
