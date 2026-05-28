"""
STEP 5 — Scene Planning (MindBlownFacts Edition)

Assigns visual_keyword to every scene based on segment label + category.
Categories: SPACE, SCIENCE, HISTORY, ANIMALS, NATURE, GEOGRAPHY, OCEAN, CULTURE
"""

import logging

log = logging.getLogger(__name__)

_HOOK: dict[str, str] = {
    "SPACE":     "galaxy stars universe space stunning",
    "SCIENCE":   "laboratory experiment science microscope",
    "HISTORY":   "ancient ruins archaeology historic site",
    "ANIMALS":   "wild animal close up nature stunning",
    "NATURE":    "dramatic nature landscape aerial stunning",
    "GEOGRAPHY": "aerial earth landscape geography drone",
    "OCEAN":     "ocean deep sea underwater stunning",
    "CULTURE":   "ancient culture architecture landmark",
}

_TENSION: dict[str, list[str]] = {
    "SPACE":     ["nebula cosmos deep space",        "planet surface space exploration"],
    "SCIENCE":   ["dna molecule cell biology",       "physics experiment energy light"],
    "HISTORY":   ["ancient pyramid ruins stone",     "historical battle medieval castle"],
    "ANIMALS":   ["predator hunting wildlife nature","ocean creature underwater marine"],
    "NATURE":    ["volcano eruption lava flow",      "storm lightning dramatic sky"],
    "GEOGRAPHY": ["mountain peak altitude aerial",   "desert vast landscape drone"],
    "OCEAN":     ["underwater bioluminescence glow", "ocean wave storm dramatic"],
    "CULTURE":   ["ancient temple ritual ceremony",  "historical artefact museum art"],
}

_CORE: dict[str, list[str]] = {
    "SPACE":     ["space planet surface texture",    "asteroid comet space rock",
                  "solar system scale size"],
    "SCIENCE":   ["microscope biology science lab",  "chemical reaction experiment",
                  "technology innovation research"],
    "HISTORY":   ["ancient civilisation ruins wide", "historical map trade route",
                  "archaeological dig site discovery"],
    "ANIMALS":   ["animal behaviour close shot",     "herd migration aerial drone",
                  "marine life coral reef ocean"],
    "NATURE":    ["forest aerial canopy wide",       "river waterfall nature flow",
                  "cave crystal geological wonder"],
    "GEOGRAPHY": ["map border country aerial",       "extreme landscape drone wide",
                  "city skyline aerial geography"],
    "OCEAN":     ["deep sea creature bioluminescent","ocean floor geology trench",
                  "whale dolphin marine mammal"],
    "CULTURE":   ["ancient writing carving stone",   "traditional ceremony people",
                  "historical artefact close detail"],
}

_PAYOFF: dict[str, str] = {
    "SPACE":     "cosmos stars milky way beautiful wide",
    "SCIENCE":   "scientific discovery breakthrough research",
    "HISTORY":   "ancient wonder heritage monument golden",
    "ANIMALS":   "animal peaceful nature beautiful wide",
    "NATURE":    "nature landscape sunrise golden beauty",
    "GEOGRAPHY": "world earth from above beautiful aerial",
    "OCEAN":     "ocean surface calm sunrise beautiful",
    "CULTURE":   "cultural celebration heritage beautiful",
}

_DEFAULT = "SCIENCE"


def plan_scenes(timeline: dict, intent: str) -> dict:
    intent = intent.upper()
    if intent not in _HOOK:
        intent = _DEFAULT

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

    log.info("Scene keywords assigned (%d scenes, category=%s)",
             len(timeline["scenes"]), intent)
    return timeline
