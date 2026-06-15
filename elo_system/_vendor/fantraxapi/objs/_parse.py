"""Small parsing helpers shared across the data-model classes.

These centralise the brittle string/number parsing that Fantrax responses
require (comma thousands separators, bracketed date ranges, trailing period
numbers) so the same idioms aren't repeated, and so malformed data raises a
clear :class:`~fantraxapi.exceptions.FantraxException` instead of an opaque
``AttributeError``/``IndexError``.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ..exceptions import FantraxException

# Characters that wrap a date range caption, e.g. "(Oct 12/24 - Oct 18/24)".
_RANGE_WRAPPERS = "()[] "
_PERIOD_SUFFIX = re.compile(r"(\d+)$")


def parse_float(value: object, default: float = 0.0) -> float:
    """Parse a float from a Fantrax cell value.

    Handles ``None``, blank/``"-"`` placeholders and comma thousands
    separators, falling back to ``default`` when the value can't be parsed.
    """
    if value is None:
        return default
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return default
    try:
        return float(text)
    except ValueError:
        return default


def parse_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    """Parse a :class:`~decimal.Decimal` from a Fantrax cell value.

    Like :func:`parse_float` but preserves exact decimal scores.
    """
    if value is None:
        return default
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return default
    try:
        return Decimal(text)
    except InvalidOperation:
        return default


def parse_date_range(caption: str, fmt: str) -> tuple[date, date]:
    """Parse a ``"(<start> - <end>)"`` caption into ``(start, end)`` dates.

    Args:
        caption: Bracketed caption such as ``"(Oct 12/24 - Oct 18/24)"``.
        fmt: ``datetime.strptime`` format for each side of the range.

    Raises:
        FantraxException: When the caption doesn't contain a parseable range.
    """
    parts = caption.strip(_RANGE_WRAPPERS).split(" - ")
    if len(parts) != 2:
        raise FantraxException(f"Could not parse date range from caption: {caption!r}")
    try:
        return (
            datetime.strptime(parts[0], fmt).date(),
            datetime.strptime(parts[1], fmt).date(),
        )
    except ValueError as e:
        raise FantraxException(f"Could not parse date range from caption: {caption!r}: {e}")


def period_number(caption: str) -> int:
    """Extract the trailing period number from a caption.

    Raises:
        FantraxException: When the caption has no trailing number.
    """
    match = _PERIOD_SUFFIX.search(caption)
    if match is None:
        raise FantraxException(f"Could not find a period number in caption: {caption!r}")
    return int(match.group(1))
