"""Build the toolkit from a staged, explicit release allowlist."""

from __future__ import annotations

import json
import os
import re
import shutil
import tomllib
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory


ROOT_FILES = ("LICENSE", "MANIFEST.in", "README.md", "_toolkit_build.py", "pyproject.toml", "setup.py")
SOURCE_DOCS = (
    "docs/toolkit/PROVENANCE.md", "docs/toolkit/CUSTOM_WORLDS.md",
    "docs/toolkit/STUDIES.md", "docs/toolkit/VERIFIER.md", "docs/toolkit/RELEASING.md",
    "docs/toolkit/build_site.py", "docs/toolkit/site_content.py",
    "docs/toolkit/draw_site_assets.py",
)
SOURCE_TESTS = (
    "tests/test_toolkit_packaging.py", "tests/test_run_risk.py",
    "tests/test_toolkit_cli.py", "tests/test_toolkit_custom.py",
    "tests/test_verifier_release_profiles.py",
    "tests/check_installed_toolkit.py",
    "tests/test_toolkit_docs.py",
)
PAPER_IDS = frozenset({"A1", "B1", "C1", "D1", "F1"})
HISTORICAL_CONFIG = (
    "verifier/runs/20260803_v3_fresh_100/"
    "authority_liveness_repair_candidate/authority_20.yaml"
)
EXCLUDED_CODE = frozenset({
    "tools/build_paper_trajectory_manifest.py",
    "verifier/orchestrator/mast.py",
})
EXCLUDED_PARTS = frozenset({
    "__pycache__", "runs", "analysis", "bundles", "manifests", "private",
    "private_source", "private_sources", "credentials", "credential", "secrets",
    "secret", "api_keys", "tacit_collusion", "aggregator_sway", "build", "dist",
})
EGG_INFO_FILES = frozenset({
    "PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt",
    "requires.txt", "top_level.txt", "zip-safe", "not-zip-safe",
})


def _relative_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in ("\\", ":", "\x00"))
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError(f"Unsafe release path: {value!r}")
    return value


def _allowed_path(relative_path: str) -> bool:
    path = PurePosixPath(_relative_path(relative_path))
    if re.search(r"(?:^|[/_.-])(?:a2|b2)(?:$|[/_.-])", relative_path.casefold()):
        return False
    if relative_path in EXCLUDED_CODE:
        return False
    return all(
        not part.startswith(".")
        and part.casefold() not in EXCLUDED_PARTS
        and PurePosixPath(part).stem.casefold() not in EXCLUDED_PARTS
        and not part.casefold().endswith((".pyc", ".pyo", ".pem", ".key", ".egg-info"))
        for part in path.parts
    )


def _source_file(root: Path, relative_path: str) -> Path:
    relative_path = _relative_path(relative_path)
    candidate = root / relative_path
    for ancestor in (candidate, *candidate.parents):
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise ValueError(f"Symlinks are not release sources: {relative_path}")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Release source escapes its root: {relative_path}")
    if not candidate.is_file():
        raise FileNotFoundError(f"Required release source is missing: {relative_path}")
    return candidate


def _metadata(root: Path) -> dict:
    return tomllib.loads(_source_file(root, "pyproject.toml").read_text(encoding="utf-8"))


def selected_configs(root: Path) -> tuple[str, ...]:
    """Select only catalog presets, never report or historical source references."""
    catalog = json.loads(
        _source_file(root, "enterprise_toolkit/catalog.json").read_text(encoding="utf-8")
    )
    worlds = catalog["worlds"]
    if len(worlds) != len(PAPER_IDS) or {world["paper_id"] for world in worlds} != PAPER_IDS:
        raise ValueError("The release catalog must contain exactly A1, B1, C1, D1, and F1")
    selected = {
        _relative_path(path)
        for world in worlds
        for path in (
            world["smoke_config"],
            *world.get("recommended_configs", []),
            *world.get("supplemental_configs", []),
        )
    }
    for relative_path in selected:
        if relative_path == HISTORICAL_CONFIG:
            continue
        if (
            not relative_path.startswith("configs/")
            or PurePosixPath(relative_path).suffix not in {".yaml", ".yml"}
            or not _allowed_path(relative_path)
        ):
            raise ValueError(f"Config is outside the release allowlist: {relative_path}")
    return tuple(sorted(selected))


def source_files(root: Path) -> tuple[str, ...]:
    """Return the exact source inventory, without walking generated directories."""
    root = root.resolve()
    settings = _metadata(root)["tool"]["setuptools"]
    discovery = settings["packages"]["find"]
    packages = discovery["include"]
    if discovery.get("namespaces", True) or any(
        not all(component.isidentifier() for component in package.split("."))
        for package in packages
    ):
        raise ValueError("Release packages must be exact names with namespaces disabled")

    selected = set(ROOT_FILES) | set(SOURCE_DOCS) | set(SOURCE_TESTS)
    for module in settings["py-modules"]:
        if not module.isidentifier() or not _allowed_path(f"{module}.py"):
            raise ValueError(f"Top-level module is outside the release allowlist: {module}")
        selected.add(f"{module}.py")
    for package in packages:
        package_path = package.replace(".", "/")
        if not _allowed_path(package_path):
            raise ValueError(f"Package is outside the release allowlist: {package}")
        _source_file(root, f"{package_path}/__init__.py")
        selected.update(
            path.relative_to(root).as_posix()
            for path in (root / package_path).glob("*.py")
            if _allowed_path(path.relative_to(root).as_posix())
        )

    for package, patterns in settings.get("package-data", {}).items():
        if package not in packages:
            raise ValueError(f"Package data requires an explicitly selected package: {package}")
        package_path = root / package.replace(".", "/")
        for pattern in patterns:
            _relative_path(pattern)
            if not _allowed_path(pattern):
                raise ValueError(f"Unsafe package-data pattern: {pattern}")
            matches = [path for path in package_path.glob(pattern) if path.is_file()]
            if not matches and not any(character in pattern for character in "*?["):
                raise FileNotFoundError(f"Required package data is missing: {package}/{pattern}")
            selected.update(
                path.relative_to(root).as_posix()
                for path in matches
                if _allowed_path(path.relative_to(root).as_posix())
            )
    selected.update(selected_configs(root))
    return tuple(sorted(selected))


def stage_sources(root: Path, destination: Path) -> tuple[str, ...]:
    """Copy only release sources into an empty staging directory."""
    root = root.resolve()
    destination = destination.resolve()
    if destination == root or destination.is_relative_to(root):
        raise ValueError("Release staging must be outside the source tree")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Release staging requires an empty destination")
    selected = source_files(root)
    sources = [(relative_path, _source_file(root, relative_path)) for relative_path in selected]
    for relative_path, source in sources:
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return selected


def copy_selected_configs(root: Path, build_root: Path) -> tuple[str, ...]:
    """Copy config bytes deterministically into build-only package assets."""
    root = root.resolve()
    build_root = build_root.resolve()
    assets_root = build_root / "enterprise_toolkit" / "assets"
    if assets_root.resolve().is_relative_to(root / "enterprise_toolkit"):
        raise ValueError("Config assets must not be written into the source package")
    selected = selected_configs(root)
    sources = [(relative_path, _source_file(root, relative_path)) for relative_path in selected]
    if assets_root.is_symlink():
        raise ValueError("Build assets must not be a symlink")
    if assets_root.exists():
        shutil.rmtree(assets_root)
    timestamp = int(os.environ.get("SOURCE_DATE_EPOCH", "315532800"))
    outputs = []
    for relative_path, source in sources:
        target = assets_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        os.utime(target, (timestamp, timestamp))
        outputs.append(str(target))
    return tuple(outputs)


def setuptools_commands() -> dict:
    """Load setuptools only in a build environment, not for resource checks."""
    from setuptools.command.build_py import build_py
    from setuptools.command.sdist import sdist

    class ToolkitBuildPy(build_py):
        def find_package_modules(self, package, package_dir):
            allowed = set(source_files(Path.cwd()))
            return [
                entry for entry in super().find_package_modules(package, package_dir)
                if Path(entry[2]).resolve().relative_to(Path.cwd().resolve()).as_posix() in allowed
            ]

        def find_data_files(self, package, src_dir):
            allowed = set(source_files(Path.cwd()))
            return [
                path for path in super().find_data_files(package, src_dir)
                if Path(path).resolve().relative_to(Path.cwd().resolve()).as_posix() in allowed
            ]

        def get_source_files(self):
            return list(source_files(Path.cwd()))

        def run(self):
            super().run()
            self._resource_outputs = copy_selected_configs(Path.cwd(), Path(self.build_lib))

        def get_outputs(self, include_bytecode=1):
            return [
                *super().get_outputs(include_bytecode),
                *getattr(self, "_resource_outputs", ()),
            ]

    class ToolkitSdist(sdist):
        def make_release_tree(self, base_dir, files):
            root = Path.cwd().resolve()
            selected = set(source_files(root))
            egg_info = Path(self.get_finalized_command("egg_info").egg_info).resolve()
            if not egg_info.is_relative_to(root):
                raise ValueError("Release metadata must be inside the staging directory")
            selected.update(
                path.relative_to(root).as_posix()
                for path in egg_info.iterdir()
                if path.is_file() and path.name in EGG_INFO_FILES
            )
            super().make_release_tree(base_dir, sorted(selected))

    return {"build_py": ToolkitBuildPy, "sdist": ToolkitSdist}


def _setuptools_backend():
    from setuptools import build_meta

    return build_meta


@contextmanager
def _staged_source():
    source_root = Path(__file__).resolve().parent
    original_directory = Path.cwd()
    with TemporaryDirectory(prefix="enterprise-toolkit-build-") as temporary:
        stage = Path(temporary)
        stage_sources(source_root, stage)
        try:
            os.chdir(stage)
            yield
        finally:
            os.chdir(original_directory)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    output = str(Path(wheel_directory).resolve())
    metadata = str(Path(metadata_directory).resolve()) if metadata_directory else None
    with _staged_source():
        return _setuptools_backend().build_wheel(output, config_settings, metadata)


def build_sdist(sdist_directory, config_settings=None):
    output = str(Path(sdist_directory).resolve())
    with _staged_source():
        return _setuptools_backend().build_sdist(output, config_settings)


def get_requires_for_build_wheel(config_settings=None):
    with _staged_source():
        return _setuptools_backend().get_requires_for_build_wheel(config_settings)


def get_requires_for_build_sdist(config_settings=None):
    with _staged_source():
        return _setuptools_backend().get_requires_for_build_sdist(config_settings)


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    output = str(Path(metadata_directory).resolve())
    with _staged_source():
        return _setuptools_backend().prepare_metadata_for_build_wheel(output, config_settings)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    return _setuptools_backend().build_editable(wheel_directory, config_settings, metadata_directory)


def get_requires_for_build_editable(config_settings=None):
    with _staged_source():
        return _setuptools_backend().get_requires_for_build_editable(config_settings)


def prepare_metadata_for_build_editable(metadata_directory, config_settings=None):
    output = str(Path(metadata_directory).resolve())
    with _staged_source():
        return _setuptools_backend().prepare_metadata_for_build_editable(output, config_settings)