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
    "SPACE":     [["nebula cosmos deep space",           "star formation gas cloud",          "black hole space dark"],
                  ["planet surface space exploration",    "astronaut space suit helmet",       "rocket launch space flame"],
                  ["milky way galaxy night sky stars",    "star cluster glowing dramatic",     "galaxy spiral arms wide"],
                  ["solar flare sun corona dramatic",     "aurora borealis lights colours",    "space telescope deep field"],
                  ["comet tail space streaking",          "meteor shower night sky trail",     "asteroid belt rocky orbit"]],
    "SCIENCE":   [["dna molecule helix biology",         "genetics laboratory science",       "microscope cell detail"],
                  ["physics experiment energy light",     "laser beam prism light spectrum",   "quantum particle wave"],
                  ["chemistry reaction beaker bubbling",  "chemical explosion colour dramatic","laboratory glassware close"],
                  ["brain neuron synapse close",          "mri scan medical brain glow",       "neuroscience research lab"],
                  ["ai robot technology futuristic",      "computer chip circuit board close", "data server technology glow"]],
    "HISTORY":   [["ancient pyramid ruins stone aerial", "pharaoh egypt archaeology gold",    "pyramid interior chamber dark"],
                  ["historical battle medieval castle",   "knights armour medieval war",       "castle siege dramatic"],
                  ["roman colosseum arena ancient",       "roman soldier armour dramatic",     "roman ruins pillars wide"],
                  ["viking ship ocean dramatic",          "ancient warriors battle dramatic",  "bronze age weapons tools"],
                  ["aztec maya temple jungle ruins",      "inca machu picchu mountain mist",   "mesoamerican pyramid wide"]],
    "ANIMALS":   [["predator hunting wildlife savanna",  "lion cheetah hunt chase nature",    "wildlife ambush dramatic"],
                  ["ocean creature underwater marine",    "shark whale dolphin ocean deep",    "marine life coral reef fish"],
                  ["wolf pack hunting forest snow",       "eagle hawk hunting dramatic sky",   "bear hunting river salmon"],
                  ["snake venom fangs close dramatic",    "spider web prey caught close",      "scorpion desert night"],
                  ["elephant herd migration aerial",      "gorilla primate forest dramatic",   "crocodile attack water"]],
    "NATURE":    [["volcano eruption lava flow",         "lava river molten rock glowing",    "volcano aerial crater smoke"],
                  ["storm lightning dramatic sky dark",   "tornado twister weather powerful",  "hurricane aerial satellite"],
                  ["wildfire forest burning dramatic",    "fire wall trees burning wide",      "smoke ash dramatic landscape"],
                  ["earthquake destruction rubble",       "tsunami wave ocean coastline",      "avalanche mountain snow dramatic"],
                  ["ice glacier calving ocean",           "permafrost arctic dramatic wide",   "blizzard whiteout extreme weather"]],
    "GEOGRAPHY": [["mountain peak altitude aerial",      "himalaya mountain snow peak",       "mountain climber altitude dramatic"],
                  ["desert vast landscape drone",         "sahara desert dune aerial red",     "canyon desert rock formation"],
                  ["arctic tundra wilderness wide",       "siberia frozen landscape aerial",   "permafrost ice dramatic wide"],
                  ["amazon rainforest canopy aerial",     "jungle river aerial green dense",   "tropical forest mist dramatic"],
                  ["volcano island ocean aerial",         "remote island isolation aerial",    "archipelago ocean aerial wide"]],
    "OCEAN":     [["underwater bioluminescence glow",    "deep sea creature dark ocean",      "ocean bioluminescent blue dark"],
                  ["ocean wave storm dramatic crash",     "wave barrel surf powerful close",   "ocean storm ship dramatic"],
                  ["submarine deep ocean dark pressure",  "underwater cave dark dramatic",     "hydrothermal vent ocean floor"],
                  ["jellyfish bloom ocean dramatic",      "manta ray ocean surface aerial",    "whale shark underwater dramatic"],
                  ["ocean whirlpool vortex aerial",       "rip current ocean wave power",      "tsunami wave deep ocean"]],
    "CULTURE":   [["ancient temple ritual ceremony",     "temple ruins stone carving detail", "religious ceremony dramatic"],
                  ["historical artefact museum close",    "ancient pottery gold artefact",     "museum exhibit dramatic light"],
                  ["carnival festival crowd colour",      "traditional dance ceremony wide",   "cultural celebration dramatic"],
                  ["ancient silk road caravan desert",    "trade route map historical",        "merchant ancient city wide"],
                  ["indigenous tribal ritual fire",       "ancient cave painting close",       "shamanic ceremony dramatic"]],
}

_CORE: dict[str, list[list[str]]] = {
    "SPACE":     [["space planet surface texture close",  "planet close surface detail rocky",  "space rock asteroid crater"],
                  ["asteroid comet space streaking",       "meteor space rock impact explosion",  "space debris orbit dramatic"],
                  ["solar system scale comparison wide",   "sun corona flare close detail",       "orbit trajectory space map"],
                  ["black hole accretion disk glowing",    "neutron star pulsar beam space",      "supernova explosion nebula"],
                  ["mars red surface landscape barren",    "moon crater surface dramatic",        "jupiter great red storm"],
                  ["space station orbit earth view",       "astronaut spacewalk earth background","satellite earth view dramatic"]],
    "SCIENCE":   [["microscope cell biology close zoom",  "cell structure biology dramatic",     "science experiment detail lab"],
                  ["chemical reaction beaker colour",      "chemical explosion dramatic lab",     "chemistry formula board"],
                  ["technology innovation future lab",     "computer chip circuit board close",   "quantum computer technology"],
                  ["brain scan neuron activity glow",      "nerve cell synapse connection",       "brain surgery medical dramatic"],
                  ["physics particle accelerator",         "laser experiment optics light",       "nuclear fusion energy plasma"],
                  ["dna strand helix close detail",        "gene editing crispr laboratory",      "protein molecule structure 3d"]],
    "HISTORY":   [["ancient civilisation ruins wide",     "temple ruins ancient city dramatic",  "archaeological site excavation"],
                  ["historical map trade route ancient",   "old map cartography detail",          "ancient map manuscript scroll"],
                  ["archaeological dig fossil bone",       "archaeologist discovery close",       "ancient artefact revealed"],
                  ["medieval illuminated manuscript",      "ancient scroll papyrus close",        "library ancient books dramatic"],
                  ["ancient coin gold treasure hoard",     "buried treasure archaeological",      "shipwreck underwater artefact"],
                  ["ancient weapon sword shield",          "armour knight medieval close",        "ancient battle formation"]],
    "ANIMALS":   [["animal behaviour close detail",       "animal eye iris close dramatic",      "animal camouflage hide nature"],
                  ["herd migration aerial wide savanna",   "wildebeest migration river crossing", "bird flock murmuration sky"],
                  ["marine life coral reef colourful",     "coral reef ecosystem fish wide",      "sea turtle swimming ocean"],
                  ["insect macro close detail dramatic",   "butterfly wing pattern close",        "ant colony work underground"],
                  ["animal birth newborn dramatic",        "mother animal young nurture nature",  "pack family social behaviour"],
                  ["nocturnal animal night vision",        "owl hunt night dramatic",             "bat sonar hunting dark"]],
    "NATURE":    [["forest aerial canopy wide green",     "rainforest canopy sunlight break",    "forest floor undergrowth close"],
                  ["waterfall mist dramatic canyon",       "river rapids white water canyon",     "gorge river aerial dramatic"],
                  ["cave crystal formation glowing",       "stalactite cave dramatic light",      "underground lake cave reflection"],
                  ["desert cracked earth drought close",   "salt flat white desert aerial",       "dust devil desert swirl"],
                  ["arctic ice formation dramatic",        "glacier crevasse blue ice close",     "polar landscape wide dramatic"],
                  ["mushroom forest floor close detail",   "bioluminescent fungi forest night",   "microorganism nature close"]],
    "GEOGRAPHY": [["satellite map country border",        "political boundary aerial dramatic",  "border wall fence aerial"],
                  ["extreme terrain landscape drone",      "unique geology rock formation wide",  "landscape pattern aerial"],
                  ["megacity skyline night aerial",        "city infrastructure aerial wide",     "urban sprawl satellite view"],
                  ["remote isolated location aerial",      "uninhabited island ocean aerial",     "wilderness no man's land wide"],
                  ["tectonic plate boundary dramatic",     "fault line geology aerial",           "earthquake zone map dramatic"],
                  ["ancient trade road path aerial",       "silk road desert caravan route",      "migration path human aerial"]],
    "OCEAN":     [["anglerfish deep sea dark glow",       "deep sea creature bioluminescent",    "ocean abyss dark pressure"],
                  ["ocean trench floor geology",           "underwater mountain ridge wide",      "hydrothermal vent ocean floor"],
                  ["whale breach surface dramatic",        "dolphin pod aerial ocean",            "orca hunt strategy pod"],
                  ["ocean microplastic pollution close",   "coral bleaching dead reef dramatic",  "ocean pollution debris wide"],
                  ["submarine deep dive dramatic",         "underwater cave dark exploration",    "ocean pressure experiment"],
                  ["ocean current map global wide",        "thermohaline circulation map",        "gulf stream ocean aerial"]],
    "CULTURE":   [["ancient hieroglyphics carving wall",  "cuneiform tablet script close",       "ancient alphabet stone carving"],
                  ["traditional ceremony fire dramatic",   "cultural festival crowd colourful",   "ritual dance costume dramatic"],
                  ["ancient gold artefact museum close",   "pottery ancient art detail",          "museum exhibit dramatic light"],
                  ["spice market ancient trade colour",    "bazaar market ancient culture",       "trade goods ancient commerce"],
                  ["ancient city reconstruction wide",     "lost city ruins exploration",         "underground city cave dwelling"],
                  ["ancient astronomical observatory",     "calendar stone carving circle",       "astrology ancient stars map"]],
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
