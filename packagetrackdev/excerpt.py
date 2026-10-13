"""Release note summarisation."""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass

NOTES_SHOWN = 3
NOTE_LINES = 6

_MARKUP = re.compile(r"\*\*|__|`|\\(?=[\[\]*_#])")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BARE_URL = re.compile(r"https?://\S+")

_TAG = re.compile(r"</?[A-Za-z][^<>]*>|<!--.*?-->")
_TAG_FRAGMENT = re.compile(r"</?[A-Za-z][^<>]*$")

_ROLE = re.compile(r":[A-Za-z]+(?::[A-Za-z]+)*:`(~?)([^`]+)`")
_ROLE_BARE = re.compile(r":[A-Za-z]+(?::[A-Za-z]+)*:(~?)([A-Za-z_][\w.]*)")
_ROLE_HTML = re.compile(
    r"(?<![\w:]):[A-Za-z]+(?::[A-Za-z]+)*:<code>(~?)([^<]+)</code>", re.IGNORECASE
)

_SPACES = re.compile(r"\s{2,}")
_SPACE_BEFORE_CLOSE = re.compile(r"\s+([)\]}.,;:!?])")
_SPACE_AFTER_OPEN = re.compile(r"([(\[{])\s+")

_SKIP = re.compile(
    r"^(full changelog|what's changed|new contributors|"
    r"see the changelog|release notes|changelog\b|"
    r"related issues and pull requests on github)",
    re.IGNORECASE,
)
_LINK_LABEL = re.compile(r"^[A-Z]\w*:?$")
_CREDIT = re.compile(r"\s+by\s+@[\w.-]+(\s+in)?\s*$", re.IGNORECASE)

_VERSION_ONLY = re.compile(
    r"^\[?v?\d+(\.\d+)+\]?"
    r"( - \d{4}-\d{2}-\d{2}| \((?=[^()]*\b(?:19|20)\d{2}\b)[\w ,./-]+\))?$"
)
_RST_ANCHOR = re.compile(r"^\.\. _\S+:?$")
_KAC_SECTION = re.compile(
    r"^(added|changed|deprecated|removed|fixed|security|unreleased"
    r"|breaking changes?"
    r"|security (?:fixes|fix|updates|update|advisories|advisory|issues|issue)"
    r"|deprecations?)$",
    re.IGNORECASE,
)
_RELEASED = re.compile(r"^released:\s", re.IGNORECASE)
_DATE_ONLY = re.compile(r"^(\d{4}-\d{2}-\d{2}|[A-Z][a-z]+ \d{1,2},? \d{4})$")
_NUMBER_ONLY = re.compile(r"^#?\d+[.,]?$")

_ONE_WORD = re.compile(r"^[A-Za-z][\w.-]*$")


_FENCE = re.compile(r"^(?:```|~~~)[A-Za-z0-9_+.#-]*$")
_HEADING = re.compile(r"^#{1,6}\s*\S")
_MD_HEADING = re.compile(r"^#{1,6}\s+\S")
_HTML_HEADING = re.compile(r"^<h[1-6][^>]*>.*</h[1-6]>$", re.IGNORECASE)
_TABLE_ROW = re.compile(r"^\|")
_LIST_ITEM = re.compile(r"^(?:[-*+•]|\d+[.)])\s+\S")
_RULE = re.compile(r"^(?:-{2,}|={2,}|_{2,}|\*{3,}|~{3,})$")
_INDENTED = re.compile(r"^(?:\t| {4,})\S")
_HTMLISH = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s|/?>)|&(?:lt|gt);")
_QUOTE_MARKER = re.compile(r"^>+\s*")
_HTML_ELEMENT = re.compile(r"<(/?)(?:li|p)(?:\s[^<>]*)?>", re.IGNORECASE)
_HTML_RECORD = re.compile(r"^(?:[-*+•]\s|\d+[.)]\s|[a-z]+(?:\([^)]*\))?!?:\s)")

WRAP_FLOOR = 60
WRAP_SLACK = 2


@dataclass(frozen=True, slots=True)
class _Block:
    """One block of a note."""


    text: str
    prose: bool
    heading: bool = False


def _is_scaffolding(line: str) -> bool:
    """Return True for lines that carry no content (dates, headers, links)."""
    return bool(
        _SKIP.match(line)
        or _VERSION_ONLY.match(line)
        or _RELEASED.match(line)
        or _DATE_ONLY.match(line)
        or _KAC_SECTION.match(line)
        or _NUMBER_ONLY.match(line)
        or _RST_ANCHOR.match(line)
    )


def _reflow(run: list[str]) -> list[_Block]:
    """Reflow a run of adjacent lines."""
    blocks: list[_Block] = []
    piece: list[str] = []
    for line in run:
        piece.append(line)
        if _ends_the_line(line):
            blocks.extend(_reflow_piece(piece))
            piece = []
    if piece:
        blocks.extend(_reflow_piece(piece))
    return blocks


def _reflow_piece(piece: list[str]) -> list[_Block]:
    """Reflow one piece of a run."""
    column = max(len(line) for line in piece)
    wrapped = (
        len(piece) > 1
        and column >= WRAP_FLOOR
        and all(
            len(above) + 1 + len(below.split(" ", 1)[0]) > column - WRAP_SLACK
            for above, below in zip(piece, piece[1:], strict=False)
        )
    )
    if wrapped:
        return [_Block(" ".join(piece), prose=True)]
    return [_Block(line, prose=True) for line in piece]


def _element_open(line: str, was_open: bool) -> bool:
    """Return True if an `<li>` or `<p>` is still open after this line."""
    tags = _HTML_ELEMENT.findall(line)
    if not tags:
        return was_open
    return tags[-1] != "/"


def _continues_html(above: str, line: str) -> bool:
    """Return True if an HTML line carries on the sentence of the one above."""
    before, after = _clean(above), _clean(line)
    opening = _TAG.sub("", line).strip()
    return bool(
        before
        and after
        and (after[0].islower() or after[0].isdigit())
        and not _HTML_RECORD.match(opening)
        and not _HTML_RECORD.match(after)
        and not _ends_the_line(before)
    )


def _blocks(body: str) -> list[_Block]:
    """Split a note into blocks."""
    blocks: list[_Block] = []
    open_lines: list[str] = []
    open_kind: str | None = None
    in_code = False
    html_tail: int | None = None
    element_open = False

    def close() -> None:
        nonlocal open_kind
        if open_lines:
            blocks.extend(_reflow(open_lines))
            open_lines.clear()
        open_kind = None

    for raw in body.splitlines():
        stripped = raw.strip()
        tail, html_tail = html_tail, None

        if _FENCE.match(stripped):
            close()
            in_code = not in_code
            continue
        if in_code:
            blocks.append(_Block(stripped, prose=False))
            continue
        if not stripped or _RULE.match(stripped):
            close()
            continue
        if _HEADING.match(stripped) or _TABLE_ROW.match(stripped):
            close()
            blocks.append(
                _Block(stripped, prose=False, heading=bool(_MD_HEADING.match(stripped)))
            )
            continue
        if _HTMLISH.search(stripped):
            close()
            heading = bool(_HTML_HEADING.match(stripped))
            if (
                tail is not None
                and element_open
                and not heading
                and _continues_html(blocks[tail].text, stripped)
            ):
                blocks[tail] = _Block(f"{blocks[tail].text} {stripped}", prose=True)
            else:
                blocks.append(_Block(stripped, prose=False, heading=heading))
            element_open = _element_open(stripped, element_open)
            html_tail = len(blocks) - 1
            continue
        element_open = False

        probe = _clean(stripped)
        if not probe:
            close()
            continue
        if _is_scaffolding(probe):
            close()
            blocks.append(_Block(stripped, prose=False))
            continue

        if _LIST_ITEM.match(stripped):
            close()
            open_lines.append(stripped)
            open_kind = "item"
            continue
        if stripped.startswith(">"):
            if open_kind != "quote":
                close()
            open_lines.append(_QUOTE_MARKER.sub("", stripped))
            open_kind = "quote"
            continue
        if open_kind == "quote":
            close()
        if open_kind is None and _INDENTED.match(raw):
            blocks.append(_Block(stripped, prose=False))
            continue

        open_lines.append(stripped)
        if open_kind is None:
            open_kind = "paragraph"

    close()
    return blocks


_BOUNDARY = re.compile(r"""([.!?])(["')\]]*)\s+(?=["'(\[]*[A-Z])""")

_ABBREVIATIONS = frozenset(
    """
    e.g i.e etc vs cf al resp approx fig no nos ca ver rev est
    mr mrs ms dr prof st inc ltd co corp vol ch sec ref pp min max
    """.split()
)
_NUMERIC_TOKEN = re.compile(r"^[vV]?\d+(?:\.\d+)*$")
_INITIAL = re.compile(r"^(?:[A-Za-z]|[A-Za-z](?:\.[A-Za-z])+)$")

MIN_SENTENCE = 20


_LINE_END = re.compile(r"""[.!?]["')\]*_`]*$""")


def _ends_the_line(line: str) -> bool:
    """Return True if the line ends a sentence."""
    match = _LINE_END.search(line)
    if match is None:
        return False
    if match.group(0)[0] != ".":
        return True
    return _ends_a_sentence(line, match.start() + 1)


def _ends_a_sentence(text: str, end: int) -> bool:
    """Return True if the period at `text[end - 1]` ends a sentence."""
    token = text[:end].rsplit(" ", 1)[-1].rstrip(".")
    if not token:
        return False
    return not (
        token.lower() in _ABBREVIATIONS
        or _NUMERIC_TOKEN.match(token)
        or _INITIAL.match(token)
    )


def _sentences(text: str) -> list[str]:
    """Split a paragraph into sentences."""
    out: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        cut = match.end(2)
        if cut - start < MIN_SENTENCE:
            continue
        if match.group(1) == "." and not _ends_a_sentence(text, match.end(1)):
            continue
        out.append(text[start:cut].strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    merged: list[str] = []
    for part in out:
        if merged and len(part) < MIN_SENTENCE:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def _echoed_heading(line: str, following: str | None) -> bool:
    return (
        following is not None
        and _ONE_WORD.fullmatch(line) is not None
        and f"[{line.lower()}]" in following.lower()
    )


def _role_text(match: re.Match) -> str:
    target = match.group(2)
    if match.group(1) == "~":
        target = target.split(".")[-1]
    return target


def _clean(raw: str) -> str:
    line = _ROLE_HTML.sub(_role_text, raw.strip())
    line = _TAG.sub(" ", line)
    line = _TAG_FRAGMENT.sub("", line)
    line = html_module.unescape(line)
    line = _TAG.sub(" ", line)
    line = _TAG_FRAGMENT.sub("", line)

    line = _MD_LINK.sub(r"\1", line)
    without_url = _BARE_URL.sub("", line)
    if without_url != line and _LINK_LABEL.match(_MARKUP.sub("", without_url).strip()):
        return ""
    line = without_url
    line = _ROLE.sub(_role_text, line)
    line = _ROLE_BARE.sub(_role_text, line)
    line = _MARKUP.sub("", line).strip().lstrip("#*->• ").strip(" :")
    line = _CREDIT.sub("", line).strip(" :,*")
    line = _SPACES.sub(" ", line)
    line = _SPACE_BEFORE_CLOSE.sub(r"\1", line)
    return _SPACE_AFTER_OPEN.sub(r"\1", line).strip()


def summarise(body: str, limit: int = NOTE_LINES) -> list[str]:
    """Summarise a release note to a few lines."""
    cleaned: list[_Block] = []
    for block in _blocks(body):
        line = _clean(block.text)
        if not line or line.startswith("<") or _SKIP.match(line):
            continue
        cleaned.append(_Block(line, block.prose, block.heading))

    lines: list[str] = []
    headings: list[bool] = []
    for position, block in enumerate(cleaned):
        if _is_scaffolding(block.text):
            continue
        following = cleaned[position + 1].text if position + 1 < len(cleaned) else None
        if _echoed_heading(block.text, following):
            continue
        if block.heading and len(lines) >= limit - 1:
            break
        parts = _sentences(block.text) if block.prose else [block.text]
        for part in parts:
            lines.append(clip(part))
            headings.append(block.heading)
            if len(lines) >= limit:
                return lines
    while headings and headings[-1]:
        lines.pop()
        headings.pop()
    return lines


def clip(line: str, width: int = 92) -> str:
    """Truncate at a word boundary and mark the cut."""
    if len(line) <= width:
        return line
    cut = line[:width].rsplit(" ", 1)[0]
    return f"{cut or line[:width]}…"
