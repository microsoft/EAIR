# Release Checks

The release is built from an explicit allowlist in
[`_toolkit_build.py`](../../_toolkit_build.py), the exact package declarations,
and the [catalog](../../enterprise_toolkit/catalog.json). It does not archive the
entire working tree. Build staging is outside the source tree; selected config
bytes are copied into build-only assets without modifying research inputs.

## Local Build

```console
python -m pip install ".[dev]"
python -m pytest tests/test_toolkit_cli.py tests/test_toolkit_custom.py tests/test_toolkit_packaging.py tests/test_verifier_release_profiles.py tests/test_run_risk.py -q
python -m build
```

The packaging regression builds an sdist and rebuilds the wheel from that sdist,
checks the exact member inventory, and imports installed modules away from the
checkout while blocking optional live/analysis SDKs. It verifies selected
configuration bytes and Harbor template completeness. It must not be skipped
because the README or release entry point is missing.

For a clean-install check, use a fresh virtual environment outside the repo,
install the wheel, change to another empty directory, and run:

```console
eair --version
eair list
eair demo --out demo
enterprise-risk authority_bias --runs-dir smoke-a1
enterprise-risk semantic_drift --runs-dir smoke-b1
enterprise-risk kpi_gaming --runs-dir smoke-c1
enterprise-risk d1 --runs-dir smoke-d1
enterprise-risk f1 --runs-dir smoke-f1
```

Also run the A1 title-effect study with its selected config in mock mode; it is
not the same implementation as the Authority compatibility smoke. Preserve
test output, artifact hashes, interpreter version, and dependency versions.

The source release includes [check_installed_toolkit.py](../../tests/check_installed_toolkit.py)
to automate these checks. Run it using the clean environment's Python with
`--report installed-checks.json`. It executes installed console scripts from a
temporary directory outside the checkout and requires live SDKs to be absent.
Its output is explicitly an offline smoke report, not a semantic evaluation.

The wheel contains executable code, 15 catalog-selected configs, roles,
artifacts, starter templates, and three Harbor task templates. The source
archive also contains the development tests and documentation. Historical
experiment reports/trajectories and isolated repaired source trees are not
bundled; their catalog paths are provenance references to the research checkout.

## Before Public Publication

- Retain the repository's MIT license and the bundled third-party license files.
  Builds include the repository license in source and wheel distributions.
- Choose the public repository/package registry and ensure the version is free.
- Review actual wheel/sdist members and metadata for secrets and private data.
- Run real Harbor auditor/Coder/Repair Auditor smoke cases with authorized
  providers and a functioning container runtime; offline tests do not replace
  this deployment validation.
- Record current source and distribution hashes. Historical selection hashes
  identify the selection-time files, not proof of the original experiment bytes
  or a replacement for the wheel's RECORD and distribution checksums.
- Keep smoke success, mechanical evidence validation, semantic adjudication,
  mitigation review, and fresh risk/utility measurements as separate claims.

No public upload, paid model matrix, or production deployment is performed by
the local build. Do not publish private generated task folders.