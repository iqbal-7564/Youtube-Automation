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

import json
import logging
import os
import re
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_LOGS_DIR = Path(__file__).parent.parent / "logs"
_USED_KEYWORDS_PATH = _LOGS_DIR / "used_visual_keywords.json"
_KEYWORD_WINDOW = 10  # penalize keywords used in last 10 videos


def _load_used_keywords() -> set[str]:
    """Load the rolling 10-video keyword history."""
    try:
        if _USED_KEYWORDS_PATH.exists():
            data = json.loads(_USED_KEYWORDS_PATH.read_text())
            return set(data.get("keywords", []))
    except Exception:
        pass
    return set()


def _save_used_keywords(keywords: list[str]) -> None:
    """Append new keywords to the rolling window (cap at 10 videos * 15 keywords = 150)."""
    try:
        existing: list[str] = []
        if _USED_KEYWORDS_PATH.exists():
            existing = json.loads(_USED_KEYWORDS_PATH.read_text()).get("keywords", [])
        combined = (existing + keywords)[-150:]  # rolling 150 entries
        tmp = _USED_KEYWORDS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"keywords": combined}, indent=2))
        tmp.replace(_USED_KEYWORDS_PATH)
    except Exception:
        pass

# ── Layer 1: Semantic narrative → emotional visual keywords ───────────────────
# Pattern strings are pipe-separated regex alternatives.
# First matching pattern wins; its visuals are prepended to keyword list.

_NARRATIVE_TRIGGERS: list[tuple[str, list[str], str]] = [
    # (regex_pattern, visual_keywords, motion_emotion)

    # Destruction / extinction / catastrophe (expanded synonyms)
    (r"died|extinct|destroyed|collapse|impact|crash|doom|apocalypse|devastat"
     r"|vanish|wiped.?out|obliterat|annihilat|eradicat|perish|ruin",
     ["cinematic explosion destruction aftermath dark",
      "apocalyptic dramatic ruins devastation wide",
      "impact shock debris dramatic cinematic"],
     "dramatic"),

    # Discovery / secret / hidden (expanded)
    (r"discover|found|reveal|uncover|secret|hidden|unknown|first time|never seen"
     r"|uncov|exposed|unearthed|breakthrough|identified|confirmed|detected",
     ["discovery light emergence dramatic reveal",
      "scientist breakthrough discovery laboratory",
      "hidden reveal light dark contrast dramatic"],
     "mysterious"),

    # Scale / size comparison (expanded)
    (r"bigger|larger|massive|enormous|vast|huge|scale|trillion|billion|million times"
     r"|colossal|immense|gigantic|incomprehensible|dwarfs|overshadow",
     ["aerial vast scale comparison dramatic wide",
      "cosmic scale size comparison universe",
      "size contrast comparison dramatic aerial"],
     "dramatic"),

    # Speed / instant (expanded)
    (r"faster|speed|instant|second|millisecond|rapidly|lightning|immediate"
     r"|velocity|acceleration|simultaneous|nanosecond|blinding",
     ["speed blur motion fast dynamic",
      "lightning fast impact velocity dramatic",
      "fast motion dynamic energy speed"],
     "excited"),

    # Fear / danger / threat (expanded)
    (r"terrif|deadly|danger|threat|killer|fatal|lethal|predator|attack|horror"
     r"|catastroph|hazard|peril|venom|toxic|radiation|lethal",
     ["dark ominous threat dramatic cinematic",
      "danger predator dark atmospheric",
      "ominous cinematic thriller dark shadow"],
     "dramatic"),

    # Ancient / history / time (expanded)
    (r"ancient|prehistoric|million year|thousand year|oldest|century|civilisation|empire"
     r"|millennia|archaic|primordial|antiquity|paleolithic|neolithic|medieval",
     ["ancient ruins archaeological stone dramatic",
      "prehistoric landscape dramatic wide historical",
      "ancient civilisation monument stone aerial"],
     "mysterious"),

    # Underground / deep / hidden beneath (expanded)
    (r"underground|beneath|buried|ocean floor|deep sea|cave|trench|abyss"
     r"|subterranean|subsurface|below ground|hidden beneath|depths",
     ["cave underground dark depth mysterious",
      "deep ocean dark bioluminescence dramatic",
      "underground tunnel depth atmospheric dark"],
     "mysterious"),

    # Wonder / beauty / breathtaking (expanded)
    (r"beautiful|stunning|breathtaking|extraordinary|incredible|magnificent|wonder"
     r"|spectacular|awe.?inspiring|mesmerising|sublime|remarkable",
     ["stunning aerial beautiful cinematic wide",
      "breathtaking landscape golden dramatic light",
      "cinematic beautiful nature vast wide"],
     "excited"),

    # Impossible / mind-blowing / paradox (expanded)
    (r"impossible|paradox|bizarre|unbelievable|mind.?blow|defy|strange"
     r"|counterintuitive|defies|violates|contradicts|inexplicable|absurd",
     ["impossible surreal dramatic mind-blowing",
      "paradox strange dramatic contrast cinematic",
      "bizarre impossible dramatic wide surreal"],
     "mysterious"),

    # Life / survival / evolution (expanded)
    (r"evolv|survival|adapt|life form|organism|creature|species|born|alive"
     r"|mutate|reproduce|extinct|thrive|predator|prey|ecosystem",
     ["wildlife survival dramatic nature wide",
      "creature close detail dramatic nature",
      "life evolution dramatic nature wide"],
     "excited"),

    # Universe / cosmos / space (expanded)
    (r"universe|cosmos|galaxy|nebula|star|planet|black hole|solar|light year"
     r"|quasar|pulsar|supernova|dark matter|event horizon|interstellar",
     ["cosmos galaxy nebula dramatic wide",
      "deep space universe dramatic cinematic",
      "planet surface space dramatic atmospheric"],
     "mysterious"),

    # Water / ocean / flood (expanded)
    (r"ocean|sea|water|flood|wave|tsunami|underwater|marine|current"
     r"|aquatic|submerged|tidal|hydrothermal|bioluminescent|abyss",
     ["ocean dramatic wave cinematic wide",
      "underwater dramatic cinematic bioluminescent",
      "ocean surface dramatic aerial wide"],
     "dramatic"),
]

# Emotion-matched CLOSE scene visuals (replaces placeholder "CLOSE" string)
_CLOSE_VISUALS: dict[str, list[str]] = {
    "excited":    ["sunset cinematic fade wide aerial",
                   "golden hour horizon beautiful calm",
                   "nature wide shot peaceful golden"],
    "mysterious": ["dark fog atmospheric cinematic wide",
                   "night sky stars calm mysterious",
                   "silhouette horizon mysterious wide"],
    "dramatic":   ["dramatic sky clouds wide aerial",
                   "epic landscape cinematic wide aerial",
                   "sunset dramatic wide horizon"],
    "neutral":    ["calm aerial zoom out landscape",
                   "peaceful nature wide sunset",
                   "logo reveal soft glow dark blue"],
}

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


_EMOTION_KEYWORDS: dict[str, list[str]] = {
    "dramatic":   ["dramatic", "cinematic", "dark", "impact", "destruction", "ruins"],
    "mysterious": ["mysterious", "dark", "hidden", "deep", "unknown", "atmospheric"],
    "excited":    ["stunning", "beautiful", "dynamic", "aerial", "wide", "golden"],
    "neutral":    ["wide", "landscape", "aerial", "calm", "nature"],
}


def _score_keywords(candidates: list[str], emotion: str,
                    semantic_hints: list[str],
                    used_keywords: set[str] | None = None) -> list[str]:
    """
    Score candidate keywords and return sorted list (highest score first).
    Scoring:
      +20 if keyword came from semantic text analysis (Layer 1)
      +15 if keyword contains an emotion-aligned word
      +20 if keyword NOT in recent 10-video history (novelty bonus)
      -10 if keyword IS in recent history (freshness penalty)
    """
    emotion_words   = _EMOTION_KEYWORDS.get(emotion, [])
    recently_used   = used_keywords or set()
    scores: list[tuple[int, str]] = []
    seen: set[str] = set()
    for kw in candidates:
        if kw in seen:
            continue
        seen.add(kw)
        score = 0
        if kw in semantic_hints:
            score += 20
        kw_lower = kw.lower()
        if any(ew in kw_lower for ew in emotion_words):
            score += 15
        if recently_used:
            if kw not in recently_used:
                score += 20  # novelty bonus
            else:
                score -= 10  # freshness penalty
        scores.append((score, kw))
    scores.sort(key=lambda x: x[0], reverse=True)
    return [kw for _, kw in scores]


# ── Groq: batch topic-specific visual keywords ───────────────────────────────

_GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.1-8b-instant"

def _groq_batch_keywords(scenes: list[dict], intent: str,
                         wiki_summary: str = "") -> dict[int, list[str]]:
    """
    Single Groq call for all scenes. Returns {scene_id: [kw1, kw2, kw3]}.
    Keywords are topic-specific (derived from actual script text) rather than
    generic category banks. Falls back to empty dict on any error.
    """
    keys = [os.getenv("GROQ_API_KEY_1", "").strip(),
            os.getenv("GROQ_API_KEY_2", "").strip()]
    keys = [k for k in keys if k]
    if not keys:
        return {}

    scene_lines = [
        f"Scene {sc['scene_id']} ({sc['segment_label']}): {sc.get('script_text', '')[:150]}"
        for sc in scenes
        if sc.get("clip_type") != "close"
    ]
    if not scene_lines:
        return {}

    wiki_ctx = f"\nVerified facts: {wiki_summary[:300]}" if wiki_summary else ""

    system_prompt = (
        "You generate stock-photo search queries for educational YouTube video scenes.\n"
        "For each scene output 3 queries (4-6 words each) a photographer would actually shoot.\n"
        "Translate abstract/scientific concepts into visible physical subjects.\n"
        "BAD: 'neutron star radiation'  GOOD: 'bright cosmic explosion nebula glow'\n"
        "BAD: 'Vikings crossed Atlantic' GOOD: 'ancient wooden ship ocean storm'\n"
        'Return ONLY valid JSON: {"1": ["kw1","kw2","kw3"], "2": [...]}'
    )

    user_msg = f"Category: {intent}{wiki_ctx}\n\nScenes:\n" + "\n".join(scene_lines)

    for key in keys:
        try:
            r = requests.post(
                _GROQ_URL,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={
                    "model":    _GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_msg},
                    ],
                    "temperature": 0.4,
                    "max_tokens":  800,
                },
                timeout=30,
            )
            if not r.ok:
                continue
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"\s*```\s*$",        "", raw, flags=re.MULTILINE)
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if not m:
                continue
            data   = json.loads(m.group())
            result = {}
            for k, v in data.items():
                try:
                    sid = int(k)
                    if isinstance(v, list) and v:
                        result[sid] = [str(kw)[:60] for kw in v[:3]]
                except (ValueError, TypeError):
                    pass
            if result:
                log.info("Groq batch keywords: %d scenes", len(result))
                return result
        except Exception as exc:
            log.debug("Groq batch keywords: %s", exc)

    return {}


# ── Main ─────────────────────────────────────────────────────────────────────

def plan_scenes(timeline: dict, intent: str, wiki_summary: str = "") -> dict:
    intent = intent.upper()
    if intent not in _HOOK:
        intent = _DEFAULT

    t_pool = [kws[:] for kws in _TENSION[intent]]
    c_pool = [kws[:] for kws in _CORE[intent]]
    t_idx = c_idx = 0

    used_keywords = _load_used_keywords()
    new_keywords:  list[str] = []

    # Batch Groq call — topic-specific keywords from actual script text
    groq_keywords = _groq_batch_keywords(timeline["scenes"], intent, wiki_summary)

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
            # Use emotion-matched visual keywords instead of the placeholder "CLOSE"
            close_emotion = sc.get("emotion", "neutral")
            close_kws = _CLOSE_VISUALS.get(close_emotion, _CLOSE_VISUALS["neutral"])
            sc["visual_keyword"]  = close_kws[0]
            sc["visual_keywords"] = close_kws[:3]
            sc["clip_type"]       = "close"
            sc["focus_region"]    = "center"
            sc["motion_emotion"]  = "neutral"
            continue

        else:
            kws = _PAYOFF.get(intent, ["nature landscape wide"])

        # Layer 0: Groq topic-specific keywords (from actual script text) — highest priority
        groq_kws = groq_keywords.get(sc["scene_id"], [])

        # Layer 1: semantic text analysis — emotional visual hints
        text_hints, motion_override = _text_visual_hints(sc.get("script_text", ""))

        # Merge: Groq-specific first, then emotional hints, then static bank
        candidate_pool = groq_kws + text_hints + list(kws)

        # Score: semantic hint +20, emotion alignment +15, novelty +20, penalty -10
        scored   = _score_keywords(candidate_pool, emotion, text_hints, used_keywords)
        combined = scored[:3] if scored else candidate_pool[:3]

        sc["visual_keyword"]  = combined[0] if combined else "cinematic dramatic wide"
        sc["visual_keywords"] = combined
        sc["focus_region"]    = _FOCUS.get(label, "center")
        sc["motion_emotion"]  = motion_override or _EMOTION_MOTION.get(emotion, "neutral")
        new_keywords.extend(combined)

    # Persist used keywords for novelty rotation across next 10 videos
    if new_keywords:
        _save_used_keywords(new_keywords)

    log.info("Scene keywords assigned (%d scenes, category=%s)",
             len(timeline["scenes"]), intent)
    return timeline
