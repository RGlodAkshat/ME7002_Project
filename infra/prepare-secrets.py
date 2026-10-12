"""Create deployment integration secrets once, without displaying them."""

import argparse
import os
from pathlib import Path
import secrets
import tempfile


def prepare(path: Path, database: bool = False) -> None:
    content = path.read_text() if path.exists() else ""
    lines = content.splitlines()
    keys = ["MACHINE_EVENT_TOKEN", "ADMIN_INTEGRATION_TOKEN"]
    if database:
        keys.append("POSTGRES_PASSWORD")
    for key in keys:
        indices = [i for i, line in enumerate(lines) if line.startswith(f"{key}=")]
        if indices and lines[indices[-1]].partition("=")[2].strip():
            continue
        entry = f"{key}={secrets.token_urlsafe(48)}"
        if indices:
            lines[indices[-1]] = entry
        else:
            lines.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".secrets-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write("\n".join(lines) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path)
    parser.add_argument("--database", action="store_true", help="Also generate a PostgreSQL password")
    arguments = parser.parse_args()
    prepare(arguments.env_file, arguments.database)
