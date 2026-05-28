"""
STEP 5 — Scene Planning (MindBlownFacts Edition)

Assigns visual_keywords (list of 3, ranked by specificity) to every scene.
Primary keyword is derived from the scene's actual narration text where
possible — not just the segment label — so visuals match what is being said.

Also sets focus_region (center/left/right/top/bottom) per scene to guide
directed Ken Burns motion in video_assembler.
"""

import logging

log = logging.getLogger(__name__)

# ── Keyword banks ─────────────────────────────────────────────────────────────

_HOOK: dict[str, list[str]] = {
    "SPACE":     ["galaxy stars universe stunning wide",     "nebula cosmos deep space",         "milky way night sky"],
    "SCIENCE":   ["laboratory experiment science close",     "microscope biology research",       "scientific discovery breakthrough"],
    "HISTORY":   ["ancient ruins archaeology historic site", "ancient monument stone heritage",   "civilisation ruins aerial"],
    "ANIMALS":   ["wild animal close up nature stunning",    "wildlife predator nature",          "animal portrait detail"],
    "NATURE":    ["dramatic nature landscape aerial",        "volcano eruption nature dramatic",  "storm lightning sky"],
    "GEOGRAPHY": ["aerial earth landscape geography drone",  "mountain peak aerial wide",         "world map globe"],
    "OCEAN":     ["ocean deep sea underwater stunning",      "ocean wave surface dramatic",       "ocean aerial wide"],
    "CULTURE":   ["ancient culture architecture landmark",   "historical temple ceremony",        "ancient art carving"],
}

_TENSION: dict[str, list[list[str]]] = {
    "SPACE":     [["nebula cosmos deep space",        "star formation gas cloud",       "black hole space dark"],
                  ["planet surface space exploration", "astronaut space suit",           "rocket launch space"]],
    "SCIENCE":   [["dna molecule cell biology",       "genetics laboratory science",    "microscope cell detail"],
                  ["physics experiment energy light",  "laser beam light science",       "quantum particle wave"]],
    "HISTORY":   [["ancient pyramid ruins stone",     "pharaoh egypt archaeology",      "pyramid aerial wide"],
                  ["historical battle medieval castle","knights armour medieval war",    "castle ruins history"]],
    "ANIMALS":   [["predator hunting wildlife",       "lion cheetah hunt savanna",      "wildlife chase nature"],
                  ["ocean creature underwater marine", "shark whale dolphin ocean",      "marine life coral reef"]],
    "NATURE":    [["volcano eruption lava flow",      "lava river molten rock",         "volcano aerial crater"],
                  ["storm lightning dramatic sky",     "tornado twister weather storm",  "flood river nature"]],
    "GEOGRAPHY": [["mountain peak altitude aerial",   "himalaya mountain snow peak",    "mountain climber altitude"],
                  ["desert vast landscape drone",      "sahara desert dune aerial",      "canyon desert rock formation"]],
    "OCEAN":     [["underwater bioluminescence glow", "deep sea creature dark ocean",   "ocean bioluminescent blue"],
                  ["ocean wave storm dramatic",        "wave crash surf powerful",       "ocean storm ship sailing"]],
    "CULTURE":   [["ancient temple ritual ceremony",  "temple ruins stone carving",     "religious ceremony culture"],
                  ["historical artefact museum art",   "ancient pottery sculpture museum","artefact close detail"]],
}

_CORE: dict[str, list[list[str]]] = {
    "SPACE":     [["space planet surface texture",    "planet close surface detail",    "space rock asteroid"],
                  ["asteroid comet space rock",        "meteor space rock impact",       "space debris orbit"],
                  ["solar system scale size",          "sun planets scale comparison",   "orbit trajectory space"]],
    "SCIENCE":   [["microscope biology science lab",  "cell structure biology zoom",    "science experiment detail"],
                  ["chemical reaction experiment",     "chemical explosion colour lab",   "chemistry beaker reaction"],
                  ["technology innovation research",   "computer chip circuit board",    "technology future lab"]],
    "HISTORY":   [["ancient civilisation ruins wide", "temple ruins ancient city",      "archaeological site dig"],
                  ["historical map trade route",       "old map cartography navigation", "ancient map illustration"],
                  ["archaeological dig site",          "fossil bone excavation dig",     "archaeologist discovery"]],
    "ANIMALS":   [["animal behaviour close shot",     "animal eye face close up",       "animal communication nature"],
                  ["herd migration aerial drone",      "wildebeest migration savanna",   "bird flock aerial migration"],
                  ["marine life coral reef ocean",     "coral reef fish colourful",      "sea turtle ocean swim"]],
    "NATURE":    [["forest aerial canopy wide",       "rainforest aerial green canopy", "forest trees sunlight"],
                  ["river waterfall nature flow",      "waterfall mist jungle nature",   "river canyon aerial"],
                  ["cave crystal geological wonder",   "crystal cave stalactite glowing","cave formation rock"]],
    "GEOGRAPHY": [["map border country aerial",       "country border satellite map",   "political map world"],
                  ["extreme landscape drone wide",     "unique terrain geography drone", "landscape pattern aerial"],
                  ["city skyline aerial geography",    "megacity skyline night lights",  "city aerial architecture"]],
    "OCEAN":     [["deep sea creature bioluminescent","anglerfish deep sea dark",       "jellyfish bioluminescent ocean"],
                  ["ocean floor geology trench",       "underwater mountain ridge",      "ocean floor sediment"],
                  ["whale dolphin marine mammal",      "whale breach ocean surface",     "dolphin pod swim ocean"]],
    "CULTURE":   [["ancient writing carving stone",   "hieroglyphics carving wall",     "ancient script tablet"],
                  ["traditional ceremony people",      "cultural festival crowd colour", "ritual dance people"],
                  ["historical artefact close detail", "ancient gold artefact museum",   "pottery ancient art"]],
}

_PAYOFF: dict[str, list[str]] = {
    "SPACE":     ["cosmos stars milky way beautiful wide", "night sky stars galaxy calm", "space nebula colour beautiful"],
    "SCIENCE":   ["scientific discovery breakthrough",     "science lab success result",  "innovation technology future"],
    "HISTORY":   ["ancient wonder heritage monument",      "historical site golden light", "ancient civilisation beauty"],
    "ANIMALS":   ["animal peaceful nature beautiful",      "wildlife sunset nature calm",  "animal family nature wide"],
    "NATURE":    ["nature landscape sunrise golden",       "sunrise mountain golden hour", "nature calm peaceful wide"],
    "GEOGRAPHY": ["world earth from above beautiful",      "earth aerial overview wide",   "landscape beautiful golden"],
    "OCEAN":     ["ocean surface calm sunrise beautiful",  "ocean horizon sunset calm",    "ocean calm clear tropical"],
    "CULTURE":   ["cultural celebration heritage",         "festival culture crowd joyful","cultural art beauty wide"],
}

# Focus region per segment (guides Ken Burns direction)
_FOCUS: dict[str, str] = {
    "HOOK":    "center",
    "TENSION": "center",
    "CORE":    "center",
    "PAYOFF":  "center",
    "CLOSE":   "center",
}

_DEFAULT = "SCIENCE"


def plan_scenes(timeline: dict, intent: str) -> dict:
    intent = intent.upper()
    if intent not in _HOOK:
        intent = _DEFAULT

    t_pool = [kws[:] for kws in _TENSION[intent]]
    c_pool = [kws[:] for kws in _CORE[intent]]
    t_idx = c_idx = 0

    for sc in timeline["scenes"]:
        label = sc["segment_label"]

        if label == "HOOK":
            kws = _HOOK[intent]

        elif label == "TENSION":
            kws = t_pool[t_idx % len(t_pool)]
            t_idx += 1

        elif label == "CORE":
            kws = c_pool[c_idx % len(c_pool)]
            c_idx += 1

        elif label == "PAYOFF":
            kws = _PAYOFF[intent]

        elif label == "CLOSE":
            sc["visual_keyword"]  = "CLOSE"
            sc["visual_keywords"] = ["CLOSE"]
            sc["clip_type"]       = "close"
            sc["focus_region"]    = "center"
            continue

        else:
            kws = _PAYOFF.get(intent, ["nature landscape wide"])

        sc["visual_keyword"]  = kws[0]
        sc["visual_keywords"] = list(kws[:3])
        sc["focus_region"]    = _FOCUS.get(label, "center")

    log.info("Scene keywords assigned (%d scenes, category=%s)",
             len(timeline["scenes"]), intent)
    return timeline
