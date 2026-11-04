"""The consent text (ARCHITECTURE_V1 section 7.5). Every statement below comes from the
contract. The consents row stores the version, the provider name and the hash of this exact
text, so a changed text is a new hash."""

from __future__ import annotations

import hashlib

from perch.auth import settings


def consent_text() -> str:
    p = settings.consent_provider_name()
    return (
        f"Perch may send the text of your CV and entries to {p} so that it can write your "
        "briefs, hand-off drafts and cover points. Contact details such as emails, phone "
        "numbers and links are blanked before any text is sent. "
        "Your CV and entries are stored encrypted under a key that belongs to you. "
        "You can delete all of your data at any time with Delete my data. "
        "If you do nothing for 12 months, your data is deleted. "
        "After you delete your data, backups clear within 35 days. "
        "You can withdraw this consent at any time. Withdrawing stops these model jobs "
        "but does not delete your data."
    )


def consent_sha256() -> bytes:
    return hashlib.sha256(consent_text().encode()).digest()
