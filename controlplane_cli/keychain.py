from __future__ import annotations

import subprocess

SERVICE = "ControlPlane"


def get_token(account: str) -> str:
    p = subprocess.run(
        ["security", "find-generic-password", "-a", account, "-s", SERVICE, "-w"],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(
            "Token not found in Keychain. Run: python -m controlplane_cli.cli token-set <TOKEN>"
        )
    return p.stdout.strip()


def set_token(account: str, token: str) -> None:
    p = subprocess.run(
        ["security", "add-generic-password", "-a", account, "-s", SERVICE, "-w", token, "-U"],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"Failed to store token in Keychain: {p.stderr.strip()}")
