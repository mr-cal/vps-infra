#!/usr/bin/env python3
"""validate_caddyfile.py

Validates Caddyfile syntax using caddy binary if available locally,
or via caddy docker container as fallback.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    caddyfile = repo_root / "caddy" / "Caddyfile"
    redirects = repo_root / "caddy" / "pcbisolation-image-redirects.caddy"

    if not caddyfile.exists():
        print(f"Error: {caddyfile} not found", file=sys.stderr)
        return 1

    # Check if local caddy executable is installed
    caddy_bin = shutil.which("caddy")
    if caddy_bin:
        cmd = [caddy_bin, "validate", "--config", str(caddyfile)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Caddy validation failed:\n{res.stderr or res.stdout}", file=sys.stderr)
            return res.returncode
        print("Caddyfile is valid.")
        return 0

    # Fallback to docker if docker is installed
    docker_bin = shutil.which("docker")
    if docker_bin:
        cmd = [
            docker_bin,
            "run",
            "--rm",
            "-v",
            f"{caddyfile}:/etc/caddy/Caddyfile:ro",
            "-v",
            f"{redirects}:/etc/caddy/pcbisolation-image-redirects.caddy:ro",
            "docker.io/library/caddy:2-alpine",
            "caddy",
            "validate",
            "--config",
            "/etc/caddy/Caddyfile",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Caddy validation failed via docker:\n{res.stderr or res.stdout}", file=sys.stderr)
            return res.returncode
        print("Caddyfile is valid (validated via docker).")
        return 0

    print("Warning: Neither 'caddy' nor 'docker' found; skipping Caddyfile validation.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
