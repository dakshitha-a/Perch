"""Process hardening for a server that holds users' decrypted text and keys in memory."""

from __future__ import annotations

import resource


def harden_process() -> None:
    """No core dumps from this process or its children: a dump would hold decrypted CVs and
    data keys."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
