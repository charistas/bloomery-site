#!/usr/bin/env python3
"""Static checks for the site without requiring a build step."""

from __future__ import annotations

import json
import struct
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "site.config.json").read_text(encoding="utf-8"))


class ParsedHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag.lower(), {k.lower(): v or "" for k, v in attrs}))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data)


def fail(message: str) -> None:
    raise AssertionError(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def parse_html(path: str) -> ParsedHTML:
    parser = ParsedHTML()
    parser.feed(read(path))
    return parser


def page_url(page: str) -> str:
    suffix = "/" if page == "index.html" else f"/{page}"
    return f"{CONFIG['domain']}{suffix}"


def normalize_local_url(value: str, source_page: str) -> str | None:
    if not value or value.startswith(("#", "mailto:", "tel:", "data:", "javascript:")):
        return None

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        if f"{parsed.scheme}://{parsed.netloc}" != CONFIG["domain"]:
            return None
        value = parsed.path or "/"
    elif parsed.netloc:
        return None

    value = value.split("#", 1)[0].split("?", 1)[0]
    if value in {"", "/"}:
        return "index.html"

    if value.startswith("/"):
        local = value.lstrip("/")
    else:
        local = str(Path(source_page).parent.joinpath(value))

    return str(Path(local))


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        fail(f"{path} is not a PNG")
    return struct.unpack(">II", data[16:24])


def get_meta(parser: ParsedHTML, key: str, value: str) -> str | None:
    for tag, attrs in parser.tags:
        if tag == "meta" and attrs.get(key) == value:
            return attrs.get("content")
    return None


def get_link(parser: ParsedHTML, rel: str) -> str | None:
    for tag, attrs in parser.tags:
        if tag == "link" and rel in attrs.get("rel", "").split():
            return attrs.get("href")
    return None


def all_attr_values(parser: ParsedHTML, tag_names: Iterable[str], attr_names: Iterable[str]) -> list[str]:
    tags = set(tag_names)
    attrs = set(attr_names)
    values: list[str] = []
    for tag, tag_attrs in parser.tags:
        if tag in tags:
            values.extend(tag_attrs[attr] for attr in attrs if tag_attrs.get(attr))
    return values


def check_required_files() -> None:
    for path in CONFIG["requiredFiles"]:
        if not (ROOT / path).exists():
            fail(f"Required file missing: {path}")


def check_pages_publish_config() -> None:
    if (ROOT / ".nojekyll").exists():
        fail(".nojekyll disables _config.yml excludes; remove it before publishing from the repository root")

    config_text = read("_config.yml")
    pages_config = CONFIG.get("pagesConfig", {})
    for item in pages_config.get("requiredIncludes", []):
        if f'- "{item}"' not in config_text and f"- {item}" not in config_text:
            fail(f"_config.yml must include {item}")

    for item in pages_config.get("requiredExcludes", []):
        if f'- "{item}"' not in config_text and f"- {item}" not in config_text:
            fail(f"_config.yml must exclude {item}")


def check_html_pages() -> None:
    external_seen: set[str] = set()

    for page in CONFIG["pages"]:
        parser = parse_html(page)
        expected = page_url(page)

        title_seen = any(tag == "title" for tag, _ in parser.tags)
        if not title_seen:
            fail(f"{page} is missing <title>")

        if get_link(parser, "canonical") != expected:
            fail(f"{page} canonical URL must be {expected}")
        if get_meta(parser, "property", "og:url") != expected:
            fail(f"{page} og:url must be {expected}")
        if not get_meta(parser, "name", "description"):
            fail(f"{page} is missing meta description")
        if not get_meta(parser, "property", "og:image"):
            fail(f"{page} is missing og:image")
        if not get_meta(parser, "name", "twitter:image"):
            fail(f"{page} is missing twitter:image")

        for tag, attrs in parser.tags:
            if tag == "img" and "alt" not in attrs:
                fail(f"{page} has image without alt text: {attrs.get('src', '<missing src>')}")

        for value in all_attr_values(parser, {"a", "link", "script", "img", "source", "form"}, {"href", "src", "action"}):
            parsed = urlparse(value)
            if parsed.scheme in {"http", "https"} and f"{parsed.scheme}://{parsed.netloc}" != CONFIG["domain"]:
                external_seen.add(value)

            local = normalize_local_url(value, page)
            if local and not (ROOT / local).exists():
                fail(f"{page} references missing local asset/page: {value} -> {local}")

        page_text = " ".join(parser.text).casefold()
        for required in CONFIG["requiredPageText"].get(page, []):
            if required.casefold() not in page_text:
                fail(f"{page} is missing required text: {required}")

    for expected in CONFIG["expectedExternalLinks"]:
        if expected not in external_seen:
            fail(f"Expected external link/form action not found: {expected}")


def check_forms() -> None:
    allowed = set(CONFIG.get("allowedFormActions", []))
    for page in CONFIG["pages"]:
        parser = parse_html(page)
        for tag, attrs in parser.tags:
            if tag == "form" and attrs.get("action") not in allowed:
                fail(f"{page} has unexpected form action: {attrs.get('action')}")


def check_mailto_placeholders() -> None:
    expected = set(CONFIG.get("requiredMailtoLinks", []))
    found: set[str] = set()
    for page in CONFIG["pages"]:
        parser = parse_html(page)
        for tag, attrs in parser.tags:
            if tag in {"span", "a"} and attrs.get("data-email-user") and attrs.get("data-email-domain"):
                found.add(f"{attrs['data-email-user']}@{attrs['data-email-domain']}")
            if tag == "a" and attrs.get("href", "").startswith("mailto:"):
                found.add(attrs["href"].removeprefix("mailto:"))
    missing = expected - found
    if missing:
        fail(f"Missing expected mailto/data-email links: {sorted(missing)}")

    for page, page_expected in CONFIG.get("requiredPageMailtoLinks", {}).items():
        parser = parse_html(page)
        page_found: set[str] = set()
        for tag, attrs in parser.tags:
            if tag in {"span", "a"} and attrs.get("data-email-user") and attrs.get("data-email-domain"):
                page_found.add(f"{attrs['data-email-user']}@{attrs['data-email-domain']}")
            if tag == "a" and attrs.get("href", "").startswith("mailto:"):
                page_found.add(attrs["href"].removeprefix("mailto:"))
        page_missing = set(page_expected) - page_found
        if page_missing:
            fail(f"{page} is missing expected mailto/data-email links: {sorted(page_missing)}")


def check_sitemap_and_robots() -> None:
    robots = read("robots.txt")
    expected_sitemap = f"Sitemap: {CONFIG['domain']}/sitemap.xml"
    if expected_sitemap not in robots:
        fail(f"robots.txt must contain {expected_sitemap}")

    tree = ET.parse(ROOT / "sitemap.xml")
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [node.text for node in tree.findall(".//sm:loc", ns)]
    expected = [f"{CONFIG['domain']}{path}" for path in CONFIG["sitemapPaths"]]
    if locs != expected:
        fail(f"sitemap.xml locs differ. Expected {expected}, got {locs}")


def check_social_card() -> None:
    image = ROOT / "social-card.png"
    if png_dimensions(image) != (1200, 630):
        fail("social-card.png must be 1200x630")


def check_security_txt() -> None:
    text = read(".well-known/security.txt")
    required = [
        "Contact: mailto:hello@twodesks.app",
        f"Canonical: {CONFIG['domain']}/.well-known/security.txt",
        "Expires:"
    ]
    for item in required:
        if item not in text:
            fail(f"security.txt missing {item}")


def check_banned_public_terms() -> None:
    public_files = [*CONFIG["pages"], "llms.txt", "robots.txt", "sitemap.xml"]
    terms = [term.casefold() for term in CONFIG.get("bannedPublicTerms", [])]
    for path in public_files:
        haystack = read(path).casefold()
        for term in terms:
            if term in haystack:
                fail(f"{path} contains banned public term: {term}")


def check_disallowed_script_markers() -> None:
    paths = [*CONFIG["pages"], "assets/site.js"]
    markers = [marker.casefold() for marker in CONFIG.get("disallowedScriptMarkers", [])]
    for path in paths:
        haystack = read(path).casefold()
        for marker in markers:
            if marker in haystack:
                fail(f"{path} contains disallowed script marker: {marker}")


def main() -> int:
    checks = [
        check_required_files,
        check_pages_publish_config,
        check_html_pages,
        check_forms,
        check_mailto_placeholders,
        check_sitemap_and_robots,
        check_social_card,
        check_security_txt,
        check_banned_public_terms,
        check_disallowed_script_markers
    ]

    for check in checks:
        check()

    print(f"Static verification passed for {CONFIG['siteName']}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"Static verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
