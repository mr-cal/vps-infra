#!/usr/bin/env python3
"""validate_static_media.py

Scans HTML files in static-sites/ to verify that locally referenced media
(images, stylesheets, media links) exist on disk, taking into account Caddy rewrite/redirect rules.
"""

from __future__ import annotations

import glob
import os
import sys
from html.parser import HTMLParser
from pathlib import Path


class MediaExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "img" and attrs_dict.get("src"):
            self.references.append(attrs_dict["src"])
        if (tag == "img" or tag == "source") and attrs_dict.get("srcset"):
            for part in attrs_dict["srcset"].split(","):
                url = part.strip().split()[0]
                if url:
                    self.references.append(url)
        if tag == "link" and attrs_dict.get("href"):
            rel = attrs_dict.get("rel", "")
            if rel in ["stylesheet"]:
                self.references.append(attrs_dict["href"])
        if tag == "a" and attrs_dict.get("href"):
            href = attrs_dict["href"]
            exts = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".pdf", ".zip", ".xlsx", ".csv")
            if any(href.lower().endswith(ext) for ext in exts):
                self.references.append(href)


def load_pcbisolation_redirects(redirect_file: Path) -> dict[str, str]:
    """Parse caddy/pcbisolation-image-redirects.caddy rules."""
    redirects: dict[str, str] = {}
    if not redirect_file.exists():
        return redirects
    for line in redirect_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("redir "):
            parts = line.split()
            if len(parts) >= 3:
                src = parts[1]
                dest = parts[2]
                redirects[src] = dest
    return redirects


def check_site(
    site_domain: str,
    root_dir: str,
    redirects: dict[str, str] | None = None,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    root_path = Path(root_dir)
    if not root_path.exists():
        return errors

    if redirects is None:
        redirects = {}

    for html_path in glob.glob(f"{root_dir}/**/*.html", recursive=True):
        html_file = Path(html_path)
        try:
            content = html_file.read_text(encoding="utf-8", errors="ignore")
        except Exception as err:
            errors.append((str(html_file), "", f"Failed to read file: {err}"))
            continue

        parser = MediaExtractor()
        parser.feed(content)

        for ref in parser.references:
            clean_ref = ref.split("?")[0].split("#")[0].strip()
            if not clean_ref:
                continue

            # Determine local path
            if clean_ref.startswith(f"https://{site_domain}/") or clean_ref.startswith(f"http://{site_domain}/"):
                url_path = clean_ref.split(site_domain, 1)[1]
            elif clean_ref.startswith("/"):
                url_path = clean_ref
            elif clean_ref.startswith("http://") or clean_ref.startswith("https://") or clean_ref.startswith("//"):
                continue  # External reference
            else:
                rel_to_root = html_file.parent.relative_to(root_path)
                url_path = "/" + str((rel_to_root / clean_ref).as_posix()).lstrip("/")

            # Check if url_path has a Caddy redirect
            resolved_url_path = redirects.get(url_path, url_path)
            target = root_path / resolved_url_path.lstrip("/")

            if not target.exists():
                errors.append((str(html_file), ref, str(target)))

    return errors


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)

    pcb_redirects = load_pcbisolation_redirects(repo_root / "caddy" / "pcbisolation-image-redirects.caddy")

    sites = [
        ("eggcalculator.com", "static-sites/egg-calculator/src", None),
        ("flashcandy.us", "static-sites/flashcandy/public", None),
        ("pcbisolation.com", "static-sites/pcbisolation", pcb_redirects),
    ]

    all_errors: list[tuple[str, str, str]] = []
    for domain, docroot, redirs in sites:
        errs = check_site(domain, docroot, redirs)
        if errs:
            print(f"FAILED: {domain} ({len(errs)} broken media links)")
            for src_file, link, target_path in errs:
                print(f"  {src_file}: '{link}' -> {target_path} not found")
            all_errors.extend(errs)
        else:
            print(f"OK: {domain}")

    if all_errors:
        print(f"\nTotal broken references found: {len(all_errors)}")
        return 1

    print("\nAll static site media references exist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
