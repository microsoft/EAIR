from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from enterprise_toolkit.cli import create_parser, main
from enterprise_toolkit.resources import load_catalog
from verifier.cli import _parser as verifier_parser
from verifier.schemas.report import RiskReport
from verifier.schemas.trajectory import Message


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "enterprise_toolkit" / "site"


def site_data():
    raw = (SITE / "data.js").read_text(encoding="utf-8")
    assert raw.startswith("globalThis.TOOLKIT_DOCS = ") and raw.endswith(";\n")
    return json.loads(raw.removeprefix("globalThis.TOOLKIT_DOCS = ").removesuffix(";\n"))


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.code = []
        self._language = None
        self._content = []

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        for key in ("href", "src"):
            if key in values:
                self.links.append(values[key])
        if tag == "code" and "data-language" in values:
            self._language = values["data-language"]
            self._content = []

    def handle_data(self, text):
        if self._language is not None:
            self._content.append(text)

    def handle_endtag(self, tag):
        if tag == "code" and self._language is not None:
            self.code.append((self._language, "".join(self._content)))
            self._language = None


def all_content():
    data = site_data()
    yield (SITE / "index.html").read_text(encoding="utf-8")
    for page in data["pages"]:
        for section in page["sections"]:
            yield section["body"]


def test_generated_website_is_current():
    result = subprocess.run(
        [sys.executable, "docs/toolkit/build_site.py", "--check"], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_complete_english_navigation():
    data = site_data()
    expected = {
        "quickstart", "installation", "concepts", "worlds", "custom-worlds",
        "adapters", "research", "auditing", "reports", "mitigation", "replay",
        "models", "reproducibility", "troubleshooting", "cli",
    }
    assert {page["id"] for page in data["pages"]} == expected
    assert len(data["pages"]) == len(expected)
    assert data["version"] == load_catalog()["release_version"]
    for page in data["pages"]:
        assert isinstance(page["title"], str) and page["title"]
        assert isinstance(page["description"], str) and page["description"]
        assert len(page["sections"]) >= 4
        assert len({section["id"] for section in page["sections"]}) == len(page["sections"])
        for section in page["sections"]:
            assert isinstance(section["title"], str) and section["title"]
            assert isinstance(section["body"], str) and len(section["body"]) >= 90


def test_documentation_is_english_only_in_source_and_distribution():
    selected = [
        SITE / "index.html", SITE / "app.js", SITE / "data.js",
        ROOT / "docs" / "toolkit" / "site_content.py",
        ROOT / "docs" / "toolkit" / "build_site.py",
    ]
    for path in selected:
        content = path.read_text(encoding="utf-8")
        assert re.search(r"[\u3400-\u9fff]", content) is None, path
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in html
    assert 'id="language"' not in html
    script = (SITE / "app.js").read_text(encoding="utf-8")
    assert "navigator.language" not in script
    assert "enterprise-docs-language" not in script


def test_every_document_link_resolves_without_remote_assets():
    routes = {page["id"]: {section["id"] for section in page["sections"]} for page in site_data()["pages"]}
    for content in all_content():
        elements = Elements()
        elements.feed(content)
        for target in elements.links:
            if target == "#main-content":
                continue
            if target.startswith("#"):
                page, _, section = target[1:].partition("/")
                assert page in routes, target
                assert not section or section in routes[page], target
                continue
            assert not urlsplit(target).scheme, f"Unexpected external runtime dependency: {target}"
            path = (SITE / unquote(target)).resolve()
            assert path.is_relative_to(SITE.resolve()) and path.is_file(), target
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    for path in re.findall(r'url\("([^\"]+)"\)', css):
        assert (SITE / path).is_file()
    assert "letter-spacing: 0" in css


def test_console_examples_match_real_argument_parsers():
    checked = set()
    for content in all_content():
        elements = Elements()
        elements.feed(content)
        for language, source in elements.code:
            if language != "console":
                continue
            for line in source.splitlines():
                assert not line.startswith("enterprise-toolkit "), line
                if not line.startswith("eair ") or line in checked:
                    continue
                tokens = shlex.split(line)[1:]
                if "--help" in tokens or "--version" in tokens:
                    continue
                parser = verifier_parser() if tokens[0] == "verify" else create_parser()
                parser.parse_args(tokens[1:] if tokens[0] == "verify" else tokens)
                checked.add(line)
    assert len(checked) >= 35


def test_eair_identity_is_text_only_and_reference_uses_primary_command():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "Enterprise Agent Risk (EAIR)" in html
    assert 'class="brand-name">EAIR<span>Enterprise Agent Risk</span>' in html
    assert 'rel="icon"' not in html
    assert "brand-symbol" not in html
    assert "brand-symbol" not in (SITE / "styles.css").read_text(encoding="utf-8")
    assert not (SITE / "assets" / "mark.png").exists()
    for filename in ("index.html", "app.js"):
        assert "Enterprise Microworld" not in (SITE / filename).read_text(encoding="utf-8")
    names = {command["name"] for command in site_data()["commands"]}
    assert {"eair", "eair run", "eair docs", "eair verify coder-task"} <= names
    assert all(name == "eair" or name.startswith("eair ") for name in names)


def test_schema_examples_use_actual_contracts():
    checked = set()
    for content in all_content():
        elements = Elements()
        elements.feed(content)
        for language, source in elements.code:
            if language != "json":
                continue
            value = json.loads(source)
            if "risk_detected" in value:
                RiskReport.model_validate(value)
                checked.add("report")
            elif "step_id" in value:
                Message.model_validate(value)
                checked.add("message")
            elif "smoke_command" in value:
                assert set(value) == {"smoke_command", "utility_command"}
                assert all(isinstance(items, list) and items for items in value.values())
                checked.add("checks")
    assert checked == {"report", "message", "checks"}


def test_documentation_exports_complete_offline_site(tmp_path):
    destination = tmp_path / "published"
    assert main(["docs", "--export", str(destination), "--no-open"]) == 0
    expected = {path.relative_to(SITE).as_posix() for path in SITE.rglob("*") if path.is_file()}
    actual = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
    assert actual == expected
    for path in expected:
        assert (destination / path).read_bytes() == (SITE / path).read_bytes()


def test_downloads_match_validated_starters_and_vendor_licenses():
    from enterprise_toolkit.custom import WorldSpec

    assert WorldSpec.load(SITE / "examples" / "world.yaml").world_id == "purchase_review"
    for filename in ("world.yaml", "scope.md"):
        assert (SITE / "examples" / filename).read_bytes() == (ROOT / "enterprise_toolkit" / "templates" / filename).read_bytes()
    sources = json.loads((SITE / "assets" / "sources.json").read_text(encoding="utf-8"))
    for filename, entry in sources.items():
        assert (SITE / "assets" / filename).is_file()
        if "license_file" in entry:
            assert (SITE / "assets" / entry["license_file"]).stat().st_size > 100