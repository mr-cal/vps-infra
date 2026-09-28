#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "click>=8.0",
#     "cryptography>=40.0",
#     "httpx>=0.24",
#     "pyjwt>=2.8",
# ]
# ///
"""Mint ephemeral GitHub App installation tokens for scoped bot automation.

This script signs an RS256 JWT using a GitHub App's private key and exchanges
it with the GitHub API for an ephemeral (1-hour) installation access token.
It supports on-demand repository downscoping and caches valid tokens locally
with an expiration buffer.

Usage:
    # Print authenticated git remote URL for the current repository
    uv run /path/to/vps-infra/scripts/mint_bot_token.py --print-remote-url

    # Target a specific repository explicitly
    uv run /path/to/vps-infra/scripts/mint_bot_token.py --print-remote-url --repo craft-dashboard

    # Verify credentials and token minting without printing token
    uv run /path/to/vps-infra/scripts/mint_bot_token.py --check

Environment Variables (can also be defined in .env.llm):
    GITHUB_APP_ID: Numeric GitHub App ID
    GITHUB_APP_INSTALLATION_ID: Numeric Installation ID
    GITHUB_APP_PRIVATE_KEY_PATH: Path to RSA .pem private key file
    GITHUB_APP_PRIVATE_KEY: Raw PEM string (alternative to path)
    GH_TOKEN / GITHUB_TOKEN: Fallback PAT if App credentials are not configured
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import Any

import click
import httpx
import jwt


def detect_repo_name() -> str | None:
    """Detect current repository name from git remote or directory."""
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        name = url.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return name or None
    except Exception:
        pass

    try:
        toplevel = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return pathlib.Path(toplevel).name or None
    except Exception:
        return None


def load_env_files() -> None:
    """Search and load .env.llm from cwd, git root, or script directory."""
    search_dirs = [pathlib.Path.cwd()]

    # Git toplevel of current directory if available
    try:
        toplevel = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if toplevel:
            search_dirs.append(pathlib.Path(toplevel))
    except Exception:
        pass

    # Script's own repository directory (vps-infra)
    script_repo = pathlib.Path(__file__).resolve().parent.parent
    search_dirs.append(script_repo)

    seen = set()
    for directory in search_dirs:
        for fname in (".env.llm", ".env"):
            fpath = directory / fname
            if fpath in seen or not fpath.is_file():
                continue
            seen.add(fpath)
            try:
                for raw_line in fpath.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("\"'")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except OSError:
                pass


def generate_jwt(app_id: str | int, private_key_pem: str) -> str:
    """Generate an RS256 JWT for authenticating as a GitHub App."""
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (9 * 60),
        "iss": str(app_id),
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def get_cache_path(installation_id: str | int, repo: str | None) -> pathlib.Path:
    """Return path to cache file for the installation and repository scope."""
    cache_dir = pathlib.Path(__file__).resolve().parent.parent / ".local" / "token_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = f"{installation_id}:{repo or 'all'}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"token_{digest}.json"


def read_cached_token(
    installation_id: str | int, repo: str | None, safety_margin_seconds: int = 300
) -> str | None:
    """Read a cached token if it has not expired and has safety margin remaining."""
    cache_path = get_cache_path(installation_id, repo)
    if not cache_path.is_file():
        return None

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        token = data.get("token")
        expires_at_str = data.get("expires_at")
        if not token or not expires_at_str:
            return None

        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        remaining = (expires_at - datetime.now(UTC)).total_seconds()
        if remaining > safety_margin_seconds:
            return str(token)
    except (OSError, ValueError, KeyError):
        return None

    return None


def save_cached_token(installation_id: str | int, repo: str | None, token_data: dict[str, Any]) -> None:
    """Save an installation token to the local cache with restricted permissions."""
    cache_path = get_cache_path(installation_id, repo)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(token_data), encoding="utf-8")
        cache_path.chmod(0o600)
    except OSError:
        pass


def mint_installation_token(
    app_id: str | int,
    installation_id: str | int,
    private_key_pem: str,
    repo: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Exchange GitHub App JWT for an ephemeral installation access token."""
    if use_cache:
        cached = read_cached_token(installation_id, repo)
        if cached:
            return {"token": cached, "cached": True}

    jwt_token = generate_jwt(app_id, private_key_pem)
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"

    payload: dict[str, Any] = {}
    if repo:
        payload["repositories"] = [repo]

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "vps-infra-token-minter",
    }

    try:
        resp = httpx.post(url, json=payload if payload else None, headers=headers, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"GitHub API error {exc.response.status_code} while minting token: {exc.response.text}"
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"Network error while contacting GitHub: {exc}") from exc

    if use_cache and "token" in data and "expires_at" in data:
        save_cached_token(installation_id, repo, data)

    return data


@click.command()
@click.option(
    "--app-id",
    envvar="GITHUB_APP_ID",
    help="Numeric GitHub App ID (or set GITHUB_APP_ID).",
)
@click.option(
    "--installation-id",
    envvar="GITHUB_APP_INSTALLATION_ID",
    help="Numeric GitHub App Installation ID (or set GITHUB_APP_INSTALLATION_ID).",
)
@click.option(
    "--key-path",
    envvar="GITHUB_APP_PRIVATE_KEY_PATH",
    type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
    help="Path to RSA .pem private key file.",
)
@click.option(
    "--repo",
    default=None,
    help="Repository to downscope the token to (e.g. craft-dashboard, vps-infra). Defaults to auto-detecting current git repo.",
)
@click.option(
    "--owner",
    default="mr-cal",
    help="GitHub owner / organization for remote URL (default: mr-cal).",
)
@click.option(
    "--print-token/--no-print-token",
    default=False,
    help="Print raw token to stdout.",
)
@click.option(
    "--print-remote-url/--no-print-remote-url",
    default=False,
    help="Print authenticated HTTPS git remote URL to stdout.",
)
@click.option(
    "--check/--no-check",
    default=False,
    help="Verify credentials and token generation without printing secrets.",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Bypass cache and force minting a fresh token.",
)
def main(
    app_id: str | None,
    installation_id: str | None,
    key_path: pathlib.Path | None,
    repo: str | None,
    owner: str,
    print_token: bool,
    print_remote_url: bool,
    check: bool,
    no_cache: bool,
) -> None:
    """Mint ephemeral GitHub App installation tokens for scoped bot automation."""
    load_env_files()

    # Auto-detect target repository if not specified
    target_repo = repo or detect_repo_name()

    app_id = app_id or os.getenv("GITHUB_APP_ID")
    installation_id = installation_id or os.getenv("GITHUB_APP_INSTALLATION_ID")
    key_path_str = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
    if not key_path and key_path_str:
        candidate = pathlib.Path(key_path_str).expanduser()
        if candidate.is_file():
            key_path = candidate

    private_key_pem = os.getenv("GITHUB_APP_PRIVATE_KEY")
    if not private_key_pem and key_path and key_path.is_file():
        private_key_pem = key_path.read_text(encoding="utf-8")

    # Fallback to GH_TOKEN / GITHUB_TOKEN if App credentials are not provided
    if not (app_id and installation_id and private_key_pem):
        fallback_token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
        if fallback_token:
            if check:
                click.echo("OK (fallback classic/PAT token found in environment)", err=True)
                sys.exit(0)
            if print_remote_url:
                repo_name = target_repo or "vps-infra"
                click.echo(f"https://{fallback_token}@github.com/{owner}/{repo_name}.git")
                sys.exit(0)
            if print_token or not (print_remote_url or check):
                click.echo(fallback_token)
                sys.exit(0)

        missing = []
        if not app_id:
            missing.append("GITHUB_APP_ID")
        if not installation_id:
            missing.append("GITHUB_APP_INSTALLATION_ID")
        if not private_key_pem:
            missing.append("GITHUB_APP_PRIVATE_KEY_PATH (or GITHUB_APP_PRIVATE_KEY)")
        click.echo(
            f"Error: Missing required GitHub App credentials: {', '.join(missing)}.\n"
            "See docs/github-app-auth.md for setup instructions, or set GH_TOKEN as fallback.",
            err=True,
        )
        sys.exit(1)

    try:
        data = mint_installation_token(
            app_id=app_id,
            installation_id=installation_id,
            private_key_pem=private_key_pem,
            repo=target_repo,
            use_cache=not no_cache,
        )
        token = data["token"]
    except Exception as exc:
        click.echo(f"Error: Failed to mint installation token: {exc}", err=True)
        sys.exit(1)

    if check:
        scope = f"scoped to {target_repo}" if target_repo else "scoped to all installed repos"
        cached_info = " (cached)" if data.get("cached") else " (freshly minted)"
        click.echo(f"OK: Successfully generated installation token {scope}{cached_info}.")
        sys.exit(0)

    if print_remote_url:
        repo_name = target_repo or "vps-infra"
        click.echo(f"https://x-access-token:{token}@github.com/{owner}/{repo_name}.git")
        sys.exit(0)

    # Default action: output the token
    click.echo(token)


if __name__ == "__main__":
    main()
