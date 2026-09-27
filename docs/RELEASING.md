# Releasing AXIS

AXIS 0.1.0 uses contract version 2.0. V2 is the only implementation. Release
numbers and protocol versions are independent.

1. Update `pyproject.toml`, `cu_suite/__init__.py`, the installed smoke version
   assertion, README, and CHANGELOG together.
2. Run `python -m pytest -q` and `python -m tests.v2.schema_smoke` with the
   development and Windows dependencies installed.
3. Build in a fresh checkout of the reviewed commit: `python -m build`.
   Reusing an old `build/` directory may package deleted modules.
4. Run `python -m twine check dist/*`, then install the wheel in a separate
   environment. Run `python -m tests.v2.installed_mcp_smoke --python PATH_TO_PYTHON`
   from the checkout. This validates installed transports and simulated workers;
   native qualification is tracked separately in `AXIS_V2_QUALIFICATION.md`.
5. Review the source archive and wheel contents, excluding credentials, traces,
   profiles, local databases, and obsolete implementations. Generate SHA-256
   checksums for both distributions.
6. Commit and push the reviewed sources, verify CI, tag the same commit as
   `vVERSION`, and publish a GitHub release with wheel, sdist, and checksums.

Publish 0.1.0 as an alpha prerelease. Keep the current native qualification
limitations visible in the release notes. GitHub publication does not publish
to PyPI; that is a separate distribution destination.
