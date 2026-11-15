"""Plain words that would act on an exposed lock, alarm, siren, valve, garage door or gate.

The structured path (``actions.py``) refuses a sensitive action by its verb and its target. Plain words go to
Assist, which acts on any entity that is exposed to it, so the same thing could be asked in words ("toggle the front
door", "let me in", "silence the alarm", "open the water valve"). This module closes that gap on the Home Assistant
side, where the entities are known, with a deny-by-default rule that needs no verb:

1. **Names.** The sentence names an exposed sensitive entity: its name or one of its aliases (the household's own
   words, so this works in any language).
2. **Nouns.** The sentence holds the noun for a kind of sensitive entity that IS exposed (a "valve" when a valve is
   exposed, a "door" or a "garage" when a lock or a non-window cover is exposed). The nouns are written for
   English, French, German, Spanish, Italian, Portuguese and Dutch only; in any other language rule 1 is the cover.
3. **Phrases.** "Let me in" and its translations (same seven languages), when a lock is exposed.

A household that exposes nothing sensitive is never refused anything. A false refusal costs a repeat; a false pass
opens a door.
"""

from collections.abc import Iterable

from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from .actions import SAFE_COVER_CLASSES, fold

#: Domains whose every entity is sensitive when exposed.
SENSITIVE_DOMAINS = frozenset({"lock", "alarm_control_panel", "siren", "valve"})
#: Switch-like entities that are sensitive because of what they are called (a water shutoff is often a switch).
NAME_DOMAINS = frozenset(
    {
        "switch",
        "input_boolean",
        "script",
        "scene",
        "button",
        "input_button",
        "automation",
    }
)

_LOCK_NOUNS = (
    "lock deadbolt door doors serrure verrou porte portes schloss tur tuer haustur cerradura cerrojo puerta puertas "
    "serratura porta porte fechadura slot deur deuren voordeur achterdeur"
)
_COVER_NOUNS = (
    "garage gate door doors portail portillon porte tor tore tur tuer garagentor garaje cochera porton puerta cancello "
    "portone porta garagem portao portoes poort hek deur garagedeur"
)
_ALARM_NOUNS = (
    "alarm alarms alarme alarmes alarma alarmas allarme allarmi alarmanlage security securite sicherheit seguridad "
    "sicurezza seguranca beveiliging"
)
_SIREN_NOUNS = "siren sirens sirene sirenes sirena sirenas"
_VALVE_NOUNS = (
    "valve valves shutoff vanne vannes electrovanne ventil ventile absperrventil valvula valvulas valvola valvole "
    "afsluiter hoofdkraan"
)
#: Kinds of exposed sensitive entity -> the nouns (folded, whole words) that name them.
NOUNS: dict[str, frozenset[str]] = {
    "lock": frozenset(_LOCK_NOUNS.split()),
    "cover": frozenset(_COVER_NOUNS.split()),
    "alarm_control_panel": frozenset(_ALARM_NOUNS.split()),
    "siren": frozenset(_SIREN_NOUNS.split()),
    "valve": frozenset(_VALVE_NOUNS.split()),
}
#: Words that mark a switch-like entity as sensitive by name.
NAME_WORDS = (
    NOUNS["valve"]
    | NOUNS["siren"]
    | NOUNS["alarm_control_panel"]
    | {"water", "eau", "wasser", "agua", "acqua"}
)
#: Runs of words (folded) that ask to be let in; only asked when a lock is exposed.
LET_IN = (
    "let me in",
    "let us in",
    "let him in",
    "let her in",
    "let them in",
    "buzz me in",
    "buzz him in",
    "buzz her in",
    "laisse moi entrer",
    "laissez moi entrer",
    "fais moi entrer",
    "faites moi entrer",
    "lass mich rein",
    "lass mich herein",
    "lass uns rein",
    "lass ihn rein",
    "dejame entrar",
    "dejame pasar",
    "dejanos entrar",
    "fammi entrare",
    "lasciami entrare",
    "facci entrare",
    "deixa me entrar",
    "deixe me entrar",
    "laat me binnen",
    "laat ons binnen",
    "laat hem binnen",
)


def _contains(words: list[str], run: list[str]) -> bool:
    """Whether `run` stands in `words`, in order and next to each other."""
    size = len(run)
    return bool(run) and any(
        words[i : i + size] == run for i in range(len(words) - size + 1)
    )


def _is_sensitive(state: State) -> str | None:
    """The kind of sensitive entity this is (a key of `NOUNS`), or None."""
    domain = state.entity_id.split(".", 1)[0]
    if domain in SENSITIVE_DOMAINS:
        return domain
    if (
        domain == "cover"
        and state.attributes.get("device_class") not in SAFE_COVER_CLASSES
    ):
        return "cover"
    if domain in NAME_DOMAINS:
        words = set(fold(state.name).split())
        if words & NAME_WORDS:
            return (
                "valve"
                if words
                & (NOUNS["valve"] | {"water", "eau", "wasser", "agua", "acqua"})
                else "alarm_control_panel"
            )
    return None


def _names(hass: HomeAssistant, state: State) -> Iterable[str]:
    """The folded names an exposed entity answers to: its name and its aliases (Assist's own aliases)."""
    yield fold(state.name)
    entry = er.async_get(hass).async_get(state.entity_id)
    if entry is not None:
        for alias in entry.aliases:
            yield fold(alias)


def _noun_present(words: list[str], nouns: frozenset[str]) -> bool:
    """Whether a noun is a word of the sentence, or the end of a compound word.

    German and Dutch write 'Haustür' and 'garagedeur' as one word, so a noun of four letters or more also ends
    a longer word.
    """
    for word in words:
        if word in nouns:
            return True
        if len(word) > 6 and any(
            len(n) >= 4 and word.endswith(n) and n != "tore" for n in nouns
        ):
            return True
    return False


def refused_words(hass: HomeAssistant, utterance: str) -> str | None:
    """Why this sentence must not reach Assist while sensitive actions are off, or None.

    `name`, `noun` or `let_in`: only the reason class, never the entity, so nothing private is logged.
    """
    words = fold(utterance).split()
    if not words:
        return None
    kinds: set[str] = set()
    for state in hass.states.async_all():
        if (kind := _is_sensitive(state)) is None:
            continue
        if not async_should_expose(hass, "conversation", state.entity_id):
            continue
        kinds.add(kind)
        for name in _names(hass, state):
            # in order ("front door"), or every word of the name somewhere ("the horn in the hall" for "Hall horn")
            if name and (
                _contains(words, name.split()) or set(name.split()) <= set(words)
            ):
                return "name"
    for kind in kinds:
        if _noun_present(words, NOUNS[kind]):
            return "noun"
    if "lock" in kinds and any(_contains(words, phrase.split()) for phrase in LET_IN):
        return "let_in"
    return None
