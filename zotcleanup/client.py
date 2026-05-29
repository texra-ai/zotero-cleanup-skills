"""Zotero client construction from environment / .env configuration."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from pyzotero import zotero


class ConfigError(RuntimeError):
    """Raised when required Zotero credentials are missing."""


def get_client() -> zotero.Zotero:
    """Build a :class:`pyzotero.zotero.Zotero` client from the environment.

    Reads ``ZOTERO_API_KEY``, ``ZOTERO_LIBRARY_ID`` and ``ZOTERO_LIBRARY_TYPE``
    (default ``"user"``). Real shell environment variables take precedence over
    values in a local ``.env`` file. Raises :class:`ConfigError` with an
    actionable message if anything required is missing.
    """
    load_dotenv()  # populate from .env without overriding real env vars

    api_key = os.environ.get("ZOTERO_API_KEY", "").strip()
    library_id = os.environ.get("ZOTERO_LIBRARY_ID", "").strip()
    library_type = os.environ.get("ZOTERO_LIBRARY_TYPE", "user").strip() or "user"

    missing = [
        name
        for name, value in (
            ("ZOTERO_API_KEY", api_key),
            ("ZOTERO_LIBRARY_ID", library_id),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "Missing required Zotero credentials: "
            + ", ".join(missing)
            + ".\nCopy .env.example to .env and fill in your values "
            "(get a key at https://www.zotero.org/settings/keys)."
        )

    if not library_id.isdigit():
        raise ConfigError(
            f"ZOTERO_LIBRARY_ID must be numeric, got {library_id!r}."
        )

    return zotero.Zotero(int(library_id), library_type, api_key)
