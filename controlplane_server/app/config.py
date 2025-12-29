from __future__ import annotations

import os

APP_NAME = "ControlPlane"
APP_VERSION = "0.3.0"
TOKEN_ENV_VAR = "CONTROLPLANE_TOKEN"


def get_api_token() -> str:
    """Return the bearer token expected by the API or raise if missing."""
    token = os.environ.get(TOKEN_ENV_VAR, "")
    if not token:
        raise RuntimeError(f"Server missing {TOKEN_ENV_VAR}")
    return token
