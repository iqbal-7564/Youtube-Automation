"""
STEP 5 — Scene Planning

Reads the updated master timeline and assigns visual_keyword to every scene
based on segment label and intent. Keyword assignment drives Step 6 (visual fetch).
"""

import logging

log = logging.getLogger(__name__)

_HOOK = {
    "DISASTER": "explosion destruction emergency",
    "WAR":      "military explosion impact strike",
    "POLITICS": "crowd protest demonstration streets",
    "ECONOMY":  "stock market crash red screen",
    "SPORTS":   "crowd celebration stadium victory",
}

_TENSION: dict[str, list[str]] = {
    "DISASTER": ["emergency rescue helicopter aerial", "flood disaster destruction"],
    "WAR":      ["military convoy soldiers march",     "city smoke destruction aerial"],
    "POLITICS": ["government building parliament",     "protest crowd street police"],
    "ECONOMY":  ["stock market trading floor",         "currency exchange finance"],
    "SPORTS":   ["athletes competing stadium",         "sports crowd cheering fans"],
}

_CORE: dict[str, list[str]] = {
    "DISASTER": ["emergency response rescue team", "disaster aftermath aerial view",
                 "rescue operation survivors"],
    "WAR":      ["military operation soldiers",    "combat zone aerial ruins",
                 "war damage city streets"],
    "POLITICS": ["political leader speech podium", "government building official",
                 "news conference press media"],
    "ECONOMY":  ["business office finance work",   "economic data analysis report",
                 "city commerce trade centre"],
    "SPORTS":   ["athletic competition game play", "sports training practice field",
                 "crowd fans stadium energy"],
}

_PAYOFF = {
    "DISASTER": "rescue aid relief survivors",
    "WAR":      "humanitarian aid rescue relief",
    "POLITICS": "official statement press conference podium",
    "ECONOMY":  "economic recovery growth chart upward",
    "SPORTS":   "trophy ceremony champion celebration",
}

_DEFAULT_INTENT = "POLITICS"


def plan_scenes(timeline: dict, intent: str) -> dict:
    intent = intent.upper()
    if intent not in _HOOK:
        intent = _DEFAULT_INTENT

    tension_pool = _TENSION[intent].copy()
    core_pool    = _CORE[intent].copy()
    t_idx = c_idx = 0

    for sc in timeline["scenes"]:
        label = sc["segment_label"]

        if label == "HOOK":
            sc["visual_keyword"] = _HOOK[intent]

        elif label == "TENSION":
            sc["visual_keyword"] = tension_pool[t_idx % len(tension_pool)]
            t_idx += 1

        elif label == "CORE":
            sc["visual_keyword"] = core_pool[c_idx % len(core_pool)]
            c_idx += 1

        elif label == "PAYOFF":
            sc["visual_keyword"] = _PAYOFF[intent]

        elif label == "CLOSE":
            sc["visual_keyword"] = "CLOSE"
            sc["clip_type"]      = "close"

    log.info("Scene keywords assigned (%d scenes, intent=%s)", len(timeline["scenes"]), intent)
    return timeline
