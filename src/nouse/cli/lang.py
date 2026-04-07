import os

def detect_language():
    # Priority: env var, then system locale, fallback to en
    lang = os.getenv("NOUSE_LANG")
    if lang:
        return lang[:2].lower()
    try:
        import locale
        loc = locale.getdefaultlocale()[0]
        if loc:
            return loc[:2].lower()
    except Exception:
        pass
    return "en"

LANG = detect_language()

# Simple translation dict (expand as needed)
STRINGS = {
    "en": {
        "front_title": "Nouse Front Door",
        "start": "Start",
        "conversation": "Conversation",
        "knowledge": "Knowledge & Learning",
        "exploration": "Exploration & Discovery",
        "diagnostics": "Brain State & Diagnostics",
        "autonomy": "Autonomy & Research",
        "identity": "Identity & Self",
        "integration": "Integration & Ingress",
        "config": "Configuration",
        "command": "Command",
        "description": "Description",
        "quickstart": "Quickstart: nouse start me · Details: nouse <command> --help · Version: nouse -V",
    },
    "sv": {
        "front_title": "Nouse Front Door",
        "start": "Start",
        "conversation": "Konversation",
        "knowledge": "Kunskap & Inlärning",
        "exploration": "Utforskning & Upptäckt",
        "diagnostics": "Hjärnstatus & Diagnostik",
        "autonomy": "Autonomi & Forskning",
        "identity": "Identitet & Self",
        "integration": "Integration & Ingress",
        "config": "Konfiguration",
        "command": "Command",
        "description": "Description",
        "quickstart": "Snabbstart: nouse start me · Detaljer: nouse <command> --help · Version: nouse -V",
    },
}

def tr(key):
    return STRINGS.get(LANG, STRINGS["en"]).get(key, key)
