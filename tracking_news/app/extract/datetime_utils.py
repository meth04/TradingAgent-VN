from datetime import timedelta, timezone

import dateparser
from dateutil import parser as dateutil_parser

VN_TIMEZONE = timezone(timedelta(hours=7))


class MissingPublishedAtError(ValueError):
    pass


def normalize_published_at(value: str | None) -> str:
    if value is None or not value.strip():
        raise MissingPublishedAtError("published_at is required")

    settings = {
        "TIMEZONE": "Asia/Ho_Chi_Minh",
        "TO_TIMEZONE": "Asia/Ho_Chi_Minh",
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "past",
    }
    parsed = dateparser.parse(value, languages=["vi", "en"], settings=settings)
    if parsed is None:
        try:
            parsed = dateutil_parser.parse(value)
        except (ValueError, TypeError) as exc:
            raise MissingPublishedAtError(f"invalid published_at: {value}") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=VN_TIMEZONE)
    else:
        parsed = parsed.astimezone(VN_TIMEZONE)

    return parsed.isoformat(timespec="seconds")


def published_date_from_iso(published_at: str) -> str:
    return published_at[:10]
