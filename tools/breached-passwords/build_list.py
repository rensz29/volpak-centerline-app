"""Build the api's offline breached-password list (guide §12, IAM-03, ADR-0016).

    python tools/breached-passwords/build_list.py NCSC.txt XATO.txt

Inputs, from SecLists (MIT licence), Passwords/Common-Credentials/:
  - 100k-most-used-passwords-NCSC.txt: the UK NCSC's top 100,000 breached passwords;
  - xato-net-10-million-passwords-1000000.txt: the top million of Mark Burnett's ten million.

Only passwords of 12 characters or more are kept: shorter ones fail the length rule anyway.
They're lower-cased, because the check ignores case, and written sorted, one per line, to
services/api/centerline_api/auth/breached-passwords.txt.gz. Hashcat's $hex[...] entries are
decoded first.
"""

from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "services" / "api" / "centerline_api" / "auth" / "breached-passwords.txt.gz"
MIN_LENGTH = 12
HEX = re.compile(r"\$hex\[([0-9a-fA-F]+)\]")


def entries(path: Path):
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        word = line.strip()
        m = HEX.fullmatch(word)
        if m:
            try:
                word = bytes.fromhex(m.group(1)).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                continue
        if len(word) >= MIN_LENGTH and "\n" not in word:
            yield word.lower()


def main(paths: list[str]) -> int:
    if not paths:
        print(__doc__)
        return 2
    words = sorted(set().union(*(entries(Path(p)) for p in paths)))
    data = ("\n".join(words) + "\n").encode("utf-8")
    with open(OUT, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as gz:
        gz.write(data)  # mtime 0: the same inputs give the same file
    print(f"{len(words)} passwords of {MIN_LENGTH}+ characters -> {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
