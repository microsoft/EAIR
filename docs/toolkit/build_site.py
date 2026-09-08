"""Generate offline website data and examples from the CLI and doc sources."""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from enterprise_toolkit.cli import create_parser
from enterprise_toolkit.resources import load_catalog
from site_content import code, pages, section, table
from verifier.cli import _parser as verifier_parser


def command_reference() -> list[dict]:
    records = []

    def collect(parser: argparse.ArgumentParser, name: str) -> None:
        parser.formatter_class = lambda prog: argparse.HelpFormatter(prog, width=88)
        parameters = []
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for command, child in action.choices.items():
                    if name == "eair" and command == "verify":
                        collect(verifier_parser(prog="eair verify"), "eair verify")
                    else:
                        collect(child, f"{name} {command}")
                continue
            if action.help == argparse.SUPPRESS:
                continue
            default = action.default
            if default == argparse.SUPPRESS or default is None:
                default = None
            parameters.append({
                "name": ", ".join(action.option_strings) if action.option_strings else action.dest,
                "required": action.required,
                "default": str(default) if default is not None else None,
                "choices": list(action.choices) if action.choices is not None else [],
                "help": action.help or "",
            })
        records.append({"name": name, "usage": parser.format_usage().strip(), "parameters": parameters})

    collect(create_parser(), "eair")
    return records


def generate() -> dict[Path, bytes]:
    package = ROOT / "enterprise_toolkit"
    catalog = load_catalog()
    world = (package / "templates" / "world.yaml").read_text(encoding="utf-8")
    scope = (package / "templates" / "scope.md").read_text(encoding="utf-8")
    content = pages(catalog["release_version"], world, scope)
    group_order = {"start": 0, "worlds": 1, "verification": 2, "reference": 3}
    content.sort(key=lambda page: group_order[page["group"]])
    reference = command_reference()
    reference_sections = []
    for command in reference:
        rows = [
            [
                f"<code>{escape(parameter['name'])}</code>",
                escape(parameter["help"]),
                escape(" | ".join(str(choice) for choice in parameter["choices"])) or "-",
                f"<code>{escape(parameter['default'])}</code>" if parameter["default"] is not None else "-",
                "yes" if parameter["required"] else "no",
            ] for parameter in command["parameters"]
        ]
        markup = code(command["usage"], "Usage", "text") + table(["Argument", "Description", "Choices", "Default", "Required"], rows)
        reference_sections.append(section(
            command["name"].replace("eair", "command").replace(" ", "-"),
            command["name"], "", markup,
        ))
    content.append({
        "id": "cli", "group": "reference", "icon": "square-terminal",
        "title": "CLI reference",
        "description": "Generated from the actual argument parsers. eair is the primary entry point; existing console aliases remain available.",
        "sections": [section("conventions", "Command conventions",
            '<p>Run <code>eair COMMAND --help</code> for local help. Paths containing spaces must be quoted. Positional paths are resolved relative to the terminal working directory. Options marked required do not encode all semantic constraints: follow the workflow guides as well.</p><p><code>study</code> previews unless <code>--execute</code> is supplied. <code>run-world</code> requires either <code>--mock</code> or <code>--provider</code>. The <code>verify</code> subtree retains its original argument names and defaults.</p>'), *reference_sections],
    })
    payload = {"version": catalog["release_version"], "pages": content, "commands": reference, "catalog": catalog}
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    checks = {"smoke_command": ["python", "checks.py", "smoke"], "utility_command": ["python", "checks.py", "utility"]}
    return {
        package / "site" / "data.js": ("globalThis.TOOLKIT_DOCS = " + serialized + ";\n").encode("utf-8"),
        package / "site" / "examples" / "world.yaml": (package / "templates" / "world.yaml").read_bytes(),
        package / "site" / "examples" / "scope.md": (package / "templates" / "scope.md").read_bytes(),
        package / "site" / "examples" / "checks.json": (json.dumps(checks, indent=2) + "\n").encode("utf-8"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = generate()
    for path, content in generated.items():
        if args.check:
            if not path.is_file() or path.read_bytes() != content:
                raise SystemExit(f"Stale website artifact: {path.relative_to(ROOT)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print(f"{'Checked' if args.check else 'Generated'} {len(generated)} website artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())