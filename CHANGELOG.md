# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [1.0.0] - 2026-09-10

First public release.

### Added

- **`navisworks` MCP server: 25 tools** driving Autodesk Navisworks over its
  out-of-process COM API — no .NET add-in, nothing to compile. Document
  operations (`open_model`, `append_model`, `save_model_as`, `get_model_info`),
  tree and property reading (`get_model_tree`, `get_node_info`,
  `get_node_properties`), search (`find_objects`), selection, appearance
  (colour, transparency, hide, isolate), views and saved viewpoints, and window
  capture.
- **Attach-or-launch connection**: the server binds to a running Navisworks via
  `GetActiveObject`, and starts a hidden instance when there is none.
  `PROG_IDS` covers Navisworks 2022–2026, verified on 2026 (Roamer 23.3).
- **A single response contract**: every tool returns JSON with an `ok` key, and
  no tool ever lets a raw COM exception escape — the `safe()` wrapper translates
  failures into an actionable message instead.
- **All COM traffic funnelled onto one dedicated thread** (`_ComThread` in
  `navisworks_client.py`), so apartment rules cannot deadlock the server.
- **Index-path object ids** (`"1/1/1/2/1"`, Navisworks' own
  `InwOaPath.ArrayData`), converted both ways and validated on input, because
  `InwOaPath.Serialise` returns `Not implemented` on this API.
- **Screenshot capture through GDI** (`PrintWindow` with `PW_RENDERFULLCONTENT`,
  falling back to `BitBlt`), with blank-capture detection —
  `state.CreatePicture` raises `Catastrophic failure` on Navisworks 2026 for
  every parameter combination.
- **Search corrections over the Navisworks defaults**: case-insensitive by
  default (`case_sensitive`), and descendant collapsing turned off by default
  (`only_topmost_match`), both of which silently return near-empty result sets
  otherwise.
- **`isolate_objects` computes the tree complement itself** rather than relying
  on `InwOpSelection.Invert()`, which returns empty for a single-node selection
  and would report success while hiding nothing.
- **`test_connection.py`** — 36 end-to-end operations against a real model,
  including negative checks (bad id, colour out of range, wrong file extension)
  and a semantic check that treats "isolate hid 0 branches" as a failure.
- **`tests/`** — contract tests that run without Navisworks installed: id
  parsing round-trips, parameter validation, the `safe()` wrapper contract, tool
  count and schema, and repository/documentation consistency.
- **CI** on GitHub Actions: ruff on Linux, pytest on Windows across Python
  3.10–3.13, with read-only permissions and superseded runs cancelled.
- **Documentation**: bilingual `README.md` / `README.vi.md`, `CONTRIBUTING.md`,
  `SECURITY.md` (including the trust model for giving a model control of
  Navisworks), `CODE_OF_CONDUCT.md`, `mcp.json.example`, issue and pull-request
  templates, and a Dependabot configuration for pip and GitHub Actions.
- MIT licence.

[Unreleased]: https://github.com/xuantinhnbs-rgb/navisworks-mcp/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/xuantinhnbs-rgb/navisworks-mcp/releases/tag/v1.0.0
