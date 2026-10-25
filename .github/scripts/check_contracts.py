"""Check NUL-delimited git diff paths against the docs/ARCHITECTURE.md (Routes and extensions) / GIT §2 carve-outs.

Ownership is enforced separately: only the four documented team extension trees are exempt
from the core contracts changelog requirement, not contracts/ext/ as a whole.
"""

import sys

TEAM_EXTENSION_PREFIXES = tuple(f"contracts/ext/{team}/".encode() for team in ("red", "green", "blue", "fe"))


def main() -> int:
    paths = set(sys.stdin.buffer.read().split(b"\0"))
    core_changed = any(path.startswith(b"contracts/") and not path.startswith(TEAM_EXTENSION_PREFIXES) for path in paths)
    if core_changed and b"contracts/CHANGELOG.md" not in paths:
        print("::error::core contracts changed without contracts/CHANGELOG.md entry")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
