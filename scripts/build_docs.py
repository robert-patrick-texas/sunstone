#!/usr/bin/env python3
# Copyright 2026 Robert Patrick
# SPDX-License-Identifier: Apache-2.0

"""Build Sunstone's documentation site with tools/md2html. See docs/DEVELOPMENT.md.

    python3 scripts/build_docs.py            # build _site/ and check every link
    python3 scripts/build_docs.py OUT_DIR    # build somewhere else

Every Markdown file in the repository becomes a page, and README.md is the
index. Every page's left-hand index opens with the project name linking to the
GitHub repository. images/ is copied whole, so a picture works from Markdown
(![alt](images/x.png)) and from a raw HTML <img> tag. A broken internal link,
anchor, or image fails the build, and nothing is published.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MD2HTML = ROOT / "tools" / "md2html" / "md2html.py"
# md2html_git needs only the standard library, so the plain python3 that runs this
# script can import it from beside md2html.py.
sys.path.insert(0, str(MD2HTML.parent))
import md2html_git  # noqa: E402 - found through the path set just above

DEFAULT_OUT = ROOT / "_site"
IMAGES = ROOT / "images"
# Not documentation: GitHub's pull request template, and what a failed
# browser test leaves behind (Playwright writes an error-context.md).
EXCLUDE = [".github", "frontend/test-results", "frontend/playwright-report", "backend/.pytest_cache"]
# Directories md2html never renders, plus EXCLUDE, for the raw-HTML image check.
SKIP_DIRS = {".git", ".venv", "node_modules", "_site", *EXCLUDE}
IMG_SRC = re.compile(r"<img\b[^>]*?\ssrc\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
# A fenced code block's opening or closing line, and an inline code span. HTML
# inside either is shown as text, not rendered, so it is not checked.
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
CODE_SPAN = re.compile(r"(`+).+?\1")


def project() -> tuple[str, str]:
    """Return the project name and its GitHub URL from tools/release/release.toml."""
    doc = tomllib.loads((ROOT / "tools" / "release" / "release.toml").read_text(encoding="utf-8"))
    return "Sunstone", f"https://github.com/{doc['repo']}"


def markdown_files() -> list[Path]:
    """Every Markdown file md2html publishes: none that git ignores."""
    found = []
    for path in sorted(ROOT.rglob("*.md")):
        if not SKIP_DIRS.intersection(path.relative_to(ROOT).parts[:-1]):
            found.append(path)
    private = md2html_git.ignored(ROOT, [p.relative_to(ROOT).as_posix() for p in found])
    return [p for p in found if p.relative_to(ROOT).as_posix() not in private]


def broken_html_images() -> list[str]:
    """Raw HTML <img> tags whose local src does not exist.

    md2html checks Markdown links and images but passes raw HTML through
    unchecked, and pictures are often written as <img> for their width and
    height. A local src must name a file inside the repository. Tags inside
    code blocks and code spans are examples, shown as text, and are skipped.
    """
    problems = []
    for page in markdown_files():
        fence = ""
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            marker = FENCE.match(line)
            if marker:
                run = marker.group(1)
                if not fence:
                    fence = run
                elif run[0] == fence[0] and len(run) >= len(fence):
                    fence = ""
                continue
            if fence:
                continue
            for src in IMG_SRC.findall(CODE_SPAN.sub("", line)):
                parts = urlsplit(src)
                if parts.scheme or parts.netloc or src.startswith("data:"):
                    continue
                target = (page.parent / unquote(parts.path)).resolve()
                if not target.is_relative_to(ROOT) or not target.is_file():
                    problems.append(f"{page.relative_to(ROOT)}:{number}: broken image -> {src}")
    return problems


def copy_images(out: Path) -> int:
    """Copy images/ into the site at the same path, skipping dotfiles."""
    count = 0
    if not IMAGES.is_dir():
        return count
    for source in sorted(IMAGES.rglob("*")):
        rel = source.relative_to(ROOT)
        if not source.is_file() or any(part.startswith(".") for part in rel.parts):
            continue
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out / rel)
        count += 1
    return count


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    out = Path(argv[0]).resolve() if argv else DEFAULT_OUT
    if out == DEFAULT_OUT and out.exists():
        # md2html never empties its output. In the default build a page whose
        # source was removed must not linger; other directories are left alone.
        shutil.rmtree(out)
    name, url = project()
    command = [
        "uv",
        "run",
        "--quiet",
        str(MD2HTML),
        str(ROOT),
        str(out),
        "--title",
        name,
        "--repo-url",
        url,
        "--branch",
        "main",
        "--repo-in-index",
        "--check",
    ]
    for pattern in EXCLUDE:
        command += ["--exclude", pattern]
    status = subprocess.run(command, cwd=ROOT, check=False).returncode
    images = broken_html_images()
    if images:
        print("\n".join(images), flush=True)
    print(f"build_docs: broken HTML images: {len(images)}", file=sys.stderr)
    if status != 0 or images:
        return 1
    print(f"build_docs: copied {copy_images(out)} files from images/ into {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
