"""Make text from outside safe to show.

A hub's name, a player's name or an error code goes into a repair issue or a translated sentence, both of which
Home Assistant renders as Markdown.
"""

import re

#: What Markdown reads as a link, an image, code or a tag, and the ``://`` that makes a bare address a link.
_MARKDOWN = re.compile(r"[\[\]()`<>]|://")
_SPACES = re.compile(r"\s+")


def escape_markdown(value: object, limit: int = 120) -> str:
    """Return ``value`` as plain words.

    ``[ ] ( ) ` < >`` and ``://`` become spaces, control characters too, runs of blanks collapse, and the result is
    cut at ``limit``. ``x](http://evil)`` becomes ``x http evil`` (no link). Not text, or nothing left: ``""``.
    """
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    plain = "".join(ch if ch.isprintable() else " " for ch in value[: limit * 4])
    return _SPACES.sub(" ", _MARKDOWN.sub(" ", plain)).strip()[:limit]
