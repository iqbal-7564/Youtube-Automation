"""
STEP 5 — Scene Planning (MindBlownFacts Edition)

Assigns visual_keywords (list of 3, ranked by specificity) to every scene.

TWO-LAYER keyword selection:
  Layer 1 — Semantic text analysis: scans the scene's actual script_text for
             emotional/narrative trigger words and prepends matching emotional
             visual keywords. This is what separates "stock search by topic"
             from "emotional visual storytelling."
  Layer 2 — Category+segment bank: static category-specific keywords as
             fallback and supplement.

Also sets focus_region and motion_emotion per scene to guide Ken Burns
motion presets in video_assembler.
"""

import logging
import re

log = logging.getLogger(__name__)

# ── Layer 1: Semantic narrative → emotional visual keywords ───────────────────
# Pattern strings are pipe-separated regex alternatives.
# First matching pattern wins; its visuals are prepended to keyword list.

_NARRATIVE_TRIGGERS: list[tuple[str, list[str], str]] = [
    # (regex_pattern, visual_keywords, motion_emotion)

    # Destruction / extinction / catastrophe
    (r"died|extinct|destroyed|collapse|impact|crash|doom|apocalypse|devastat",
     ["cinematic explosion destruction aftermath dark",
      "apocalyptic dramatic ruins devastation wide",
      "impact shock debris dramatic cinematic"],
     "dramatic"),

    # Discovery / secret / hidden
    (r"discover|found|reveal|uncover|secret|hidden|unknown|first time|never seen",
     ["discovery light emergence dramatic reveal",
      "scientist breakthrough discovery laboratory",
      "hidden reveal light dark contrast dramatic"],
     "mysterious"),

    # Scale / size comparison
    (r"bigger|larger|massive|enormous|vast|huge|scale|trillion|billion|million times",
     ["aerial vast scale comparison dramatic wide",
      "cosmic scale size comparison universe",
      "size contrast comparison dramatic aerial"],
     "dramatic"),

    # Speed / instant
    (r"faster|speed|instant|second|millisecond|rapidly|lightning|immediate",
     ["speed blur motion fast dynamic",
      "lightning fast impact velocity dramatic",
      "fast motion dynamic energy speed"],
     "excited"),

    # Fear / danger / threat
    (r"terrif|deadly|danger|threat|killer|fatal|lethal|predator|attack|horror",
     ["dark ominous threat dramatic cinematic",
      "danger predator dark atmospheric",
      "ominous cinematic thriller dark shadow"],
     "dramatic"),

    # Ancient / history / time
    (r"ancient|prehistoric|million year|thousand year|oldest|century|civilisation|empire",
     ["ancient ruins archaeological stone dramatic",
      "prehistoric landscape dramatic wide historical",
      "ancient civilisation monument stone aerial"],
     "mysterious"),

    # Underground / deep / hidden beneath
    (r"underground|beneath|buried|ocean floor|deep sea|cave|trench|abyss",
     ["cave underground dark depth mysterious",
      "deep ocean dark bioluminescence dramatic",
      "underground tunnel depth atmospheric dark"],
     "mysterious"),

    # Wonder / beauty / breathtaking
    (r"beautiful|stunning|breathtaking|extraordinary|incredible|magnificent|wonder",
     ["stunning aerial beautiful cinematic wide",
      "breathtaking landscape golden dramatic light",
      "cinematic beautiful nature vast wide"],
     "excited"),

    # Impossible / mind-blowing / paradox
    (r"impossible|paradox|bizarre|unbelievable|mind.?blow|defy|strange",
     ["impossible surreal dramatic mind-blowing",
      "paradox strange dramatic contrast cinematic",
      "bizarre impossible dramatic wide surreal"],
     "mysterious"),

    # Life / survival / evolution
    (r"evolv|survival|adapt|life form|organism|creature|species|born|alive",
     ["wildlife survival dramatic nature wide",
      "creature close detail dramatic nature",
      "life evolution dramatic nature wide"],
     "excited"),

    # Universe / cosmos / space
    (r"universe|cosmos|galaxy|nebula|star|planet|black hole|solar|light year",
     ["cosmos galaxy nebula dramatic wide",
      "deep space universe dramatic cinematic",
      "planet surface space dramatic atmospheric"],
     "mysterious"),

    # Water / ocean / flood
    (r"ocean|sea|water|flood|wave|tsunami|underwater|marine|current",
     ["ocean dramatic wave cinematic wide",
      "underwater dramatic cinematic bioluminescent",
      "ocean surface dramatic aerial wide"],
     "dramatic"),
]

# ── Layer 2: Category + segment static keyword banks ─────────────────────────

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

# Focus region per segment — guides Ken Burns direction
_FOCUS: dict[str, str] = {
    "HOOK":    "center",
    "TENSION": "center",
    "CORE":    "center",
    "PAYOFF":  "center",
    "CLOSE":   "center",
}

# Emotion → motion_emotion tag for video_assembler preset selection
_EMOTION_MOTION: dict[str, str] = {
    "excited":    "excited",
    "mysterious": "mysterious",
    "dramatic":   "dramatic",
    "neutral":    "neutral",
}

_DEFAULT = "SCIENCE"


# ── Semantic text analysis ────────────────────────────────────────────────────

def _text_visual_hints(text: str) -> tuple[list[str], str | None]:
    """
    Scan script_text for narrative/emotional trigger words.
    Returns (visual_keyword_overrides, motion_emotion_override).
    Overrides are prepended to the category keyword list.
    """
    text_lower = text.lower()
    for pattern, visuals, motion in _NARRATIVE_TRIGGERS:
        if re.search(pattern, text_lower):
            return visuals[:2], motion
    return [], None


# ── Main ─────────────────────────────────────────────────────────────────────

def plan_scenes(timeline: dict, intent: str) -> dict:
    intent = intent.upper()
    if intent not in _HOOK:
        intent = _DEFAULT

    t_pool = [kws[:] for kws in _TENSION[intent]]
    c_pool = [kws[:] for kws in _CORE[intent]]
    t_idx = c_idx = 0

    for sc in timeline["scenes"]:
        label   = sc["segment_label"]
        emotion = sc.get("emotion", "neutral")

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
            sc["motion_emotion"]  = "neutral"
            continue

        else:
            kws = _PAYOFF.get(intent, ["nature landscape wide"])

        # Layer 1: semantic text analysis — prepend emotional visual hints
        text_hints, motion_override = _text_visual_hints(sc.get("script_text", ""))
        combined = (text_hints + list(kws[:3]))[:3]

        sc["visual_keyword"]  = combined[0]
        sc["visual_keywords"] = combined
        sc["focus_region"]    = _FOCUS.get(label, "center")
        sc["motion_emotion"]  = motion_override or _EMOTION_MOTION.get(emotion, "neutral")

    log.info("Scene keywords assigned (%d scenes, category=%s)",
             len(timeline["scenes"]), intent)
    return timeline
