"""The stored device-flow session (``auth.json``).

Sign-in is additive, never required: every verb in this package works with no
``AuthState`` on disk (:func:`load_auth` returning ``None`` is the normal,
fully-supported anonymous path). When present, the file carries the bearer
token the learn API issued, its expiry, and the linked GitHub identity — never
an email (the API itself never requests or stores one; see
``workers/learn-api/src/github.js``). The file is written ``0600`` (owner
read/write only) since it holds a bearer credential.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from typing import Any, Optional

from learn.profile._paths import auth_path, ensure_store_dir


@dataclass(frozen=True)
class AuthState:
    """The linked learner's session, as stored locally."""

    token: str
    token_type: str
    expires_at: Optional[int]
    github_user_id: str
    display_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "token_type": self.token_type,
            "expires_at": self.expires_at,
            "learner": {
                "github_user_id": self.github_user_id,
                "display_name": self.display_name,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthState":
        learner = data.get("learner") or {}
        return cls(
            token=str(data["token"]),
            token_type=str(data.get("token_type", "Bearer")),
            expires_at=data.get("expires_at"),
            github_user_id=str(learner.get("github_user_id", "")),
            display_name=str(learner.get("display_name", "")),
        )


def load_auth() -> Optional[AuthState]:
    """Return the stored session, or ``None`` when signed out / unreadable.

    A missing, corrupt, or malformed file is treated as "signed out" rather
    than an error — the anonymous path must never be blocked by a damaged
    auth file.
    """
    path = auth_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return AuthState.from_dict(data)
    except (KeyError, TypeError):
        return None


def save_auth(state: AuthState) -> None:
    """Persist ``state``, chmod'd ``0600`` (owner-only) since it holds a token."""
    ensure_store_dir()
    path = auth_path()
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # best-effort — some filesystems (e.g. some CI containers) reject chmod


def clear_auth() -> bool:
    """Delete the stored session. Returns whether one existed."""
    path = auth_path()
    if path.is_file():
        path.unlink()
        return True
    return False
