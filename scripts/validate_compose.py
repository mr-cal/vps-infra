#!/usr/bin/env python3
"""validate_compose.py

Validates docker-compose.*.yml files using 'docker compose config'
or 'podman-compose config', supplying temporary example environment
files where required so compose configuration syntax and structure
can be verified deterministically in CI and local pre-commit.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    compose_files = sorted(repo_root.glob("docker-compose.*.yml"))

    if not compose_files:
        print("No docker-compose.*.yml files found to validate.", file=sys.stderr)
        return 1

    docker_bin = shutil.which("docker")
    podman_compose_bin = shutil.which("podman-compose")

    if not docker_bin and not podman_compose_bin:
        print("Warning: Neither docker nor podman-compose available; skipping compose validation.", file=sys.stderr)
        return 0

    env_example = repo_root / ".env.example"
    env_bm_example = repo_root / ".env.bm-tracker.example"

    # We ensure .env and .env.bm-tracker exist temporarily in repo_root if not present
    created_env = False
    created_bm_env = False
    env_file = repo_root / ".env"
    env_bm_file = repo_root / ".env.bm-tracker"

    try:
        if not env_file.exists() and env_example.exists():
            env_file.write_text(env_example.read_text())
            created_env = True
        elif not env_file.exists():
            env_file.write_text("# dummy env\nDATABASE_URL=postgres://dummy\n")
            created_env = True

        if not env_bm_file.exists() and env_bm_example.exists():
            env_bm_file.write_text(env_bm_example.read_text())
            created_bm_env = True
        elif not env_bm_file.exists():
            env_bm_file.write_text("# dummy env\nSESSION_SECRET=dummysecretdummysecretdummysecret32\n")
            created_bm_env = True

        for compose_file in compose_files:
            cmd: list[str]
            if docker_bin:
                cmd = [docker_bin, "compose", "-f", str(compose_file), "config", "--quiet"]
            else:
                cmd = [podman_compose_bin, "-f", str(compose_file), "config"]

            res = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"Validation failed for {compose_file.name}:\n{res.stderr or res.stdout}", file=sys.stderr)
                return res.returncode
            print(f"✓ {compose_file.name} is valid.")

    finally:
        if created_env and env_file.exists():
            env_file.unlink()
        if created_bm_env and env_bm_file.exists():
            env_bm_file.unlink()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
