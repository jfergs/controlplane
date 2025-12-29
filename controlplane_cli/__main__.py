from __future__ import annotations

import argparse
import getpass
import json
import sys

import httpx

from .keychain import get_token


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ControlPlane CLI")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the ControlPlane API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--account",
        default=getpass.getuser(),
        help="Keychain account name to load CONTROLPLANE_TOKEN (default: current user)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of a human-friendly summary",
    )
    parser.add_argument("--timeout", type=float, default=5.0, help="Request timeout in seconds")
    parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        help="Exit with status 2 if the response contains warnings",
    )
    return parser.parse_args(argv)


def _print_summary(data: dict) -> None:
    print(f"Host: {data.get('host')}")
    print(f"OS: {data.get('os')}")
    print(f"Python: {data.get('python')}")
    print(f"Uptime (s): {data.get('uptime_sec')}")
    disk = data.get("disk_root", {})
    print(
        "Disk /: total {total_gb} GB, used {used_gb} GB, free {free_gb} GB".format(
            total_gb=disk.get("total_gb"),
            used_gb=disk.get("used_gb"),
            free_gb=disk.get("free_gb"),
        )
    )
    mem = data.get("memory", {})
    print(
        "Memory: total {total} GB, available {avail} GB, used {percent}%".format(
            total=mem.get("total_gb"),
            avail=mem.get("available_gb"),
            percent=mem.get("percent"),
        )
    )
    load = data.get("load_avg", {})
    print(
        "Load average: 1m {one}, 5m {five}, 15m {fifteen}".format(
            one=load.get("1m"), five=load.get("5m"), fifteen=load.get("15m")
        )
    )
    net = data.get("net_io", {})
    print(
        "Net I/O: sent {sent} bytes, recv {recv} bytes".format(
            **{
                "sent": net.get("bytes_sent"),
                "recv": net.get("bytes_recv"),
            }
        )
    )
    print(f"CPU temp (C): {data.get('cpu_temp_c')}")
    warnings = data.get("warnings") or []
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"- {w}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        token = get_token(args.account)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    url = args.url.rstrip("/")

    try:
        resp = httpx.get(
            f"{url}/api/status",
            headers={"Authorization": f"Bearer {token}"},
            timeout=args.timeout,
        )
    except httpx.HTTPError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    if resp.status_code != 200:
        print(f"Error {resp.status_code}: {resp.text}", file=sys.stderr)
        return 1

    data = resp.json()
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        _print_summary(data)
    if args.fail_on_warnings and data.get("warnings"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
