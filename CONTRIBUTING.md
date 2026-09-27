# Contributing to AXIS Computer Use

We welcome contributions from developers, autonomous agents, and systems engineers.

---

## Code of Conduct & Principles

1. **Verification is the Contract:** Every feature, fix, or optimization must be backed by unit or integration tests.
2. **Action is the Evidence:** Concrete desktop and DOM state transitions supersede assumptions.
3. **Minimal Disruption:** Keep changes surgical. Preserve existing architecture and interfaces.
4. **Evidence > Speculation:** Benchmark and verify against live operating system applications.

---

## Development setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/IsmailAzzouz/axis-computer-use.git
   cd axis-computer-use
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install the Windows development dependencies:**
   ```bash
   python -m pip install --no-build-isolation -e '.[windows,dev]'
   ```

4. **Run test suite:**
   ```bash
   python -m pytest
   ```

The public API contract is version 2.0; the current package distribution is
0.1.0 alpha. Keep changes within the V2 runtime and contract. Windows is the
current development and qualification target; other platforms are not qualified.

---

## Pull Request Guidelines

- All tests must pass with 0 failures before opening a PR.
- Add focused tests for changed behavior and follow the current V2 test layout.
- Maintain typing annotations and clear docstrings.
- Follow PEP 8 style conventions.
