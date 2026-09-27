# AXIS roadmap

AXIS is distributed as **0.1.0 alpha** with API contract **2.0**. The public
surface is V2 only. Current availability does not imply native qualification.

## Available in the alpha

- Six MCP tools: `axis.help`, `axis.targets`, `axis.observe`, `axis.run`,
  `axis.job`, and `axis.capture`.
- A resident Windows host with explicit application/target permissions, a
  loopback broker, job recovery, and a Python SDK.
- Ordered plans, semantic observations, postconditions, and explicit reporting
  of unverified or uncertain effects.
- Windows accessibility, input, clipboard, OCR, and capture paths, subject to
  the capability declarations of the running host.

## Qualification and delivery work

- Run the current native fixture corpus repeatedly, including interruption,
  input cleanup, and resource/endurance scenarios.
- Complete broader Excel workflows, including range selection, locale cases,
  save/reopen verification, and repeated trials.
- Complete the Edge workflow corpus and repeated native qualification.
- Evaluate actual model usability with declared models, settings, budgets, tool
  calls, images, and token measurements.
- Establish supported platform scope. macOS/Linux adapters are not qualified
  for this alpha.
- Reassess release certification after the required native and model evidence is
  complete.

The project is not currently release-certified. See the
[qualification record](docs/AXIS_V2_QUALIFICATION.md) for evidence definitions,
current gaps, and limits; see the [API reference](docs/API_REFERENCE.md) for the
public contract.
