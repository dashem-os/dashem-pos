"""When channel data stops being kept — política técnica inicial, not legal advice.

S10.1 proposal §3.7, D3 approved and D6 decided by the owner on 16/09/2026.
These numbers are an **initial technical policy** to build and test against.
They are not legal guidance, they declare no compliance, and they are not a
commercial promise: before any of that they need validation by whoever answers
for legal and privacy (G1).

What this module does today is assign deadlines. Nothing here removes data —
the purge is a later step, and until it exists and the provider's backup cycle
is documented, retention is not "implemented".
"""

from datetime import datetime, timedelta

RAW_PAYLOAD_DAYS = 30
CONTACT_DAYS = 90


def raw_payload_deadline_from_reception(received_at: datetime) -> datetime:
    """D6: every event is persisted with its payload already on the clock.

    An event applied to an order without ever being quarantined later trades this
    deadline, once, for the order's terminal state (D3). Every other event keeps
    it: quarantine does not stop it, and fixing the cause does not restart it.
    """
    return received_at + timedelta(days=RAW_PAYLOAD_DAYS)
