# Contributing to AXIS Computer Use

We welcome contributions from developers, autonomous agents, and systems engineers.

---

## Code of Conduct & Principles

1. **Verification is the Contract:** Every feature, fix, or optimization must be backed by unit or integration tests.
2. **Action is the Evidence:** Concrete desktop and DOM state transitions supersede assumptions.
3. **Minimal Disruption:** Keep changes surgical. Preserve existing architecture and interfaces.
4. **Evidence > Speculation:** Benchmark and verify against live operating system applications.

---

## Development Setup

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

3. **Install dependencies in editable mode:**
   ```bash
   pip install -e .[windows,dev]  # On macOS: pip install -e .[macos,dev]
   ```

4. **Run test suite:**
   ```bash
   python -m unittest discover -s tests -v
   ```

---

## Pull Request Guidelines

- All tests must pass with 0 failures before opening a PR.
- Add new tests in `tests/` for any new platform provider, kinematic curve, or input handler.
- Maintain typing annotations and clear docstrings.
- Follow PEP 8 style conventions.
