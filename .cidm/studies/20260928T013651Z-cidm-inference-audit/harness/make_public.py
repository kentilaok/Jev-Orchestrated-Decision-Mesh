"""Produce public copies of study documents by withholding <!--PRIVATE-->...<!--/PRIVATE--> spans.

    python -B make_public.py <in.md> <out.md>
The private originals keep the full text; the public copy never contains marked spans.
"""
import re
import sys
from pathlib import Path

MARK = re.compile(r"<!--PRIVATE-->.*?<!--/PRIVATE-->", re.S)


def publicize(text):
    out = MARK.sub(" [withheld: private project evidence]", text)
    if "<!--PRIVATE-->" in out or "<!--/PRIVATE-->" in out:
        raise SystemExit("unbalanced private markers")
    return out


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(publicize(Path(sys.argv[1]).read_text(encoding="utf-8")), encoding="utf-8")
