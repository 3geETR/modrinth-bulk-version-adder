from __future__ import annotations

import os
import re
import sys
import time
import requests
import questionary
from questionary import Choice
from typing import List, Dict

API_BASE = "https://api.modrinth.com/v2"
MY_UA = "bulk-version-adder/1.0"

# Optionally hardcode your token here (not recommended for public scripts)
HARDCODED_TOKEN: str = ""  # "pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

###############################################################################
# Modrinth REST helpers
###############################################################################

def auth_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": MY_UA,
        "Content-Type": "application/json",
    }


def get_username(headers: Dict[str, str]) -> str:
    r = requests.get(f"{API_BASE}/user", headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()["username"]


def list_projects(username: str, headers: Dict[str, str]):
    r = requests.get(f"{API_BASE}/user/{username}/projects", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def list_versions(slug: str, headers: Dict[str, str]):
    r = requests.get(f"{API_BASE}/project/{slug}/version", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def patch_version(version_id: str, new_game_versions: List[str], headers: Dict[str, str]):
    payload = {"game_versions": new_game_versions}
    r = requests.patch(f"{API_BASE}/version/{version_id}", json=payload, headers=headers, timeout=30)
    r.raise_for_status()

###############################################################################
# Version string parsers
###############################################################################

def parse_versions(input_str: str) -> List[str]:
    """Parses user input into a list of versions.
    Supports single versions, comma-separated, ranges, and combinations."""
    if not input_str.strip():
        raise ValueError("Version input cannot be empty!")

    versions: List[str] = []
    parts = [p.strip() for p in input_str.split(',') if p.strip()]
    range_re = re.compile(r"^(\d+(?:\.\d+){1,2})-(\d+(?:\.\d+){1,2})$")

    for part in parts:
        m = range_re.match(part)
        if m:
            start, end = m.group(1), m.group(2)
            versions.extend(expand_range(start, end))
        else:
            versions.append(part)

    return sorted(set(versions), key=version_key)


def expand_range(start: str, end: str) -> List[str]:
    s_parts, e_parts = start.split('.'), end.split('.')
    if len(s_parts) != len(e_parts):
        raise ValueError(f"Mismatched version formats: {start}-{end}")
    if s_parts[:-1] != e_parts[:-1]:
        raise ValueError("Only the last numeric segment can vary in range")

    try:
        s_last, e_last = int(s_parts[-1]), int(e_parts[-1])
    except ValueError:
        raise ValueError("Range segments must be numeric (e.g. 1.21.1-1.21.6)")
    if s_last > e_last:
        raise ValueError("Range start must not be greater than end")

    base = '.'.join(s_parts[:-1])
    return [f"{base}.{i}" for i in range(s_last, e_last + 1)]


def version_key(v: str):
    return [int(x) if x.isdigit() else x for x in re.split(r"[.-]", v)]

###############################################################################
# Terminal UI
###############################################################################

def prompt_token() -> str:
    if HARDCODED_TOKEN:
        return HARDCODED_TOKEN
    return questionary.password("Modrinth Access Token:").ask() or ""


def prompt_versions() -> str:
    hint = "e.g. 1.21.6 | 1.21.1-1.21.6 | 1.21.3,1.21.6"
    return questionary.text(f"Target Minecraft version(s) ({hint}):").ask() or ""


def main():
    print("\n=== Modrinth Bulk Version Adder ===\n")

    token = prompt_token().strip()
    if not token:
        print("❌  No token provided. Exiting.")
        sys.exit(1)

    headers = auth_headers(token)
    try:
        username = get_username(headers)
    except Exception as exc:
        print(f"❌  Failed to get user info: {exc}")
        sys.exit(1)

    try:
        projects = list_projects(username, headers)
    except Exception as exc:
        print(f"❌  Failed to list projects: {exc}")
        sys.exit(1)

    if not projects:
        print("ℹ️  No projects found.")
        sys.exit(0)

    choices = [Choice(title=f"{p['title']} ({p['slug']})", value=p['slug'], checked=True) for p in projects]
    selected_slugs = questionary.checkbox(
        "Select projects to apply versions to (space to toggle, enter to continue):",
        choices=choices,
    ).ask()

    if not selected_slugs:
        print("ℹ️  No projects selected. Exiting.")
        sys.exit(0)

    vers_input = prompt_versions().strip()
    if not vers_input:
        print("❌  No version specified.")
        sys.exit(1)
    try:
        versions = parse_versions(vers_input)
    except ValueError as exc:
        print(f"❌  Invalid version input: {exc}")
        sys.exit(1)

    print(f"\n🟢  Logged in as: {username}")
    print("Selected projects:")
    for slug in selected_slugs:
        proj = next(p for p in projects if p['slug'] == slug)
        print(f"  • {proj['title']} ({slug})")
    print("Target Minecraft versions: " + ', '.join(versions))
    print()

    touched = 0
    for slug in selected_slugs:
        proj = next(p for p in projects if p['slug'] == slug)
        print(f"🔹  {proj['title']} ({slug})")
        try:
            version_data = list_versions(slug, headers)
        except Exception as exc:
            print(f"   ⟶ Failed to get versions: {exc}")
            continue

        for v in version_data:
            gv = v['game_versions']
            missing = [ver for ver in versions if ver not in gv]
            if not missing:
                continue
            new_gv = sorted(set(gv + missing), key=version_key)
            print(f"   • {v['name']}: {gv} → {new_gv}")
            try:
                patch_version(v['id'], new_gv, headers)
                time.sleep(0.3)
            except Exception as exc:
                print(f"      ⟶ Failed to update: {exc}")
                continue
            touched += 1
    print(f"\n✅  Done. Versions updated: {touched}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
