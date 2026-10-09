"""Rules shared by every logged entry: readings, doses, carbs.

Each logging service raises ``EntryError`` with a message that can be shown on the page.
``PossibleDuplicate`` is the one error the user may override, by confirming the entry.
"""

from datetime import datetime, timedelta

# Allowance for a phone clock that runs a little ahead of the server.
FUTURE_ALLOWANCE = timedelta(minutes=5)
MAX_AGE = timedelta(days=30)


class EntryError(ValueError):
    """The entry is not acceptable. The message is safe to show to the user."""


class PossibleDuplicate(EntryError):
    """The same entry was logged moments ago. Saved anyway only when the user confirms."""


def check_entry_time(at: datetime, now: datetime) -> None:
    """Reject times in the future (beyond clock drift) or older than 30 days."""
    if at.tzinfo is None:
        raise ValueError("naive datetime: attach the user's timezone before checking an entry")
    if at > now + FUTURE_ALLOWANCE:
        raise EntryError("The time is in the future. Check the date and time.")
    if at < now - MAX_AGE:
        raise EntryError("Entries older than 30 days cannot be added.")
