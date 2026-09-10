# navisworks-mcp

***English** · [Tiếng Việt](README.vi.md)*

[![CI](https://github.com/xuantinhnbs-rgb/navisworks-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/xuantinhnbs-rgb/navisworks-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](#requirements)

An MCP server that lets Claude — or any MCP client such as Claude Code, Claude
Desktop, Cursor or Cline — drive **Autodesk Navisworks** running on your Windows
machine: browse the model tree, read IFC/Revit properties, search, select,
colour, hide, isolate, zoom, and capture the window.

Verified on **Navisworks Manage 2026** (Roamer 23.3.1460.83), Python 3.14,
Windows 10. All 36 end-to-end checks pass against a real model.

Every tool returns JSON with an `ok` key — `{"ok": true, ...}` on success,
`{"ok": false, "error": "..."}` on failure. No tool ever lets a raw COM
exception escape.

![Navisworks driven by the MCP server: MSE wall panels found by name, coloured
orange and zoomed to](docs/demo.png)

*Everything above happened without a single click in Navisworks:
`find_objects("PANEL")` → 375 matches, `set_color(...)` on twenty of them,
`zoom_to_objects(...)`, `capture_screenshot(...)`.*

## How it talks to Navisworks

Navisworks registers an out-of-process COM server:

```
HKLM\SOFTWARE\Classes\Navisworks.Document.23\CLSID
  -> LocalServer32 = C:\Program Files\Autodesk\Navisworks Manage 2026\Roamer.exe
```

That handle gives you the **whole** COM API, not just open/save commands:

```python
doc   = win32com.client.Dispatch("Navisworks.Document.23")
state = doc.State          # InwOpState10: model tree, properties, search,
                           # selection, colour, visibility, viewpoints...
```

No .NET add-in to write, nothing to compile. The server **attaches to a running
Navisworks** if there is one (`GetActiveObject`), and starts a hidden instance
otherwise.

## Requirements

- Windows
- Autodesk Navisworks (Manage or Simulate) — verified on **2026**; 2022–2025
  connect through the matching ProgID in `PROG_IDS` but are unverified
- Python 3.10 or newer

## Installation

```powershell
git clone https://github.com/xuantinhnbs-rgb/navisworks-mcp.git
cd navisworks-mcp
pip install -r requirements.txt
python test_connection.py          # finds a .nwd/.nwc on your machine and tests against it
```

Then declare the server in your MCP client's configuration. Copy
[`mcp.json.example`](mcp.json.example) and replace `<PYTHON>` with the path to
your `python.exe` and `<PATH>` with the directory you just cloned into:

```json
{
  "mcpServers": {
    "navisworks": {
      "command": "<PYTHON>/python.exe",
      "args": ["<PATH>/navisworks-mcp/server.py"],
      "cwd": "<PATH>/navisworks-mcp",
      "env": { "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

`PYTHONIOENCODING=utf-8` is not optional: the Windows console defaults to cp1252
and any non-ASCII message will kill the server with `UnicodeEncodeError`.

## Object identifiers

Objects are addressed by a **1-based index path** counted from the model root:

```
""                 the model root (whole file)
"1"                first child of the root
"1/1/1/2/1/1/1"    seven levels down
```

This is Navisworks' own `InwOaPath.ArrayData`, and it converts both ways. Get
ids from `get_model_tree`, `find_objects` or `get_selection` — never invent one.

A model exported from Revit/IFC has a typical tree:

```
File > Assembly > IfcSite > IfcBuilding > IfcBuildingStorey > Category > Family
     > Instance > Mesh
```

## Tools

24 tools in total:

| Group | Tools |
|---|---|
| Connection | `check_navisworks_connection`, `show_navisworks_window` |
| Document | `open_model`, `append_model`, `save_model_as`, `get_model_info` |
| Tree & properties | `get_model_tree`, `get_node_info`, `get_node_properties` |
| Search | `find_objects` |
| Selection | `get_selection`, `select_objects`, `clear_selection` |
| Appearance | `set_color`, `set_transparency`, `reset_appearance`, `hide_objects`, `isolate_objects`, `show_all_objects` |
| Views | `zoom_to_objects`, `list_saved_views`, `apply_saved_view`, `list_selection_sets` |
| Images | `capture_screenshot` |

## Performance: read this before a large query

Every field in a result is one cross-process COM round trip. Measured on this
machine:

| Condition | Cost per object |
|---|---|
| Window hidden, `detail="basic"` | ~19 ms |
| Window hidden, `detail="full"` | ~26 ms |
| **Window visible**, `detail="basic"` | **~200 ms** |

A visible window makes every call drag a UI repaint along with it — 5–10× more
expensive. So: **hide the window for bulk queries, show it only when you need to
look at something or take a screenshot.** `find_objects` defaults to
`detail="basic"`; call `get_node_info` on a single object when you need the
detail.

## Three Navisworks behaviours that surprise people

**1. Search is case-sensitive by default in Navisworks.** The server sets
`case_sensitive=False` instead, because component names in civil models are
mostly upper case (`TAM PANEL...`). Searching `"panel"` with
`case_sensitive=True` returns 0 results where `"PANEL"` returns 374.

**2. Search results collapse onto the parent node.** Navisworks defaults to
"disjoint": once a node matches, its descendants are not listed separately.
Searching for a type containing `"Ifc"` therefore returns exactly **1** row
(IfcSite — ancestor of everything) instead of 779. The server turns collapsing
off by default; re-enable it with `only_topmost_match=True`.

**3. `isolate_objects` has to compute the complement itself.**
`InwOpSelection.Invert()` does not give a tree-wise complement: calling it on a
single-node selection returns **empty**, so the obvious "select, invert, hide"
approach reports success while hiding exactly nothing. The server instead walks
from the root and hides every branch that is neither an ancestor nor a
descendant of the target.

## Three pywin32 traps with this API

1. `doc.State` is a **property**, not a method. `doc.State()` raises
   `Member not found`.
2. Parameterised properties must be called through the `Set`/`Get` prefix:
   `state.SetSelectionHidden(sel, True)`.
3. Pointers obtained via `GetActiveObject` and via `Dispatch` **do not bind the
   same way**: the same `IsModified` is a method on one and a plain `bool` on the
   other. Read through the `_member` helper.

## Not supported yet

Stated plainly so you do not waste time trying:

- **Clash Detective**: not wired up. Clash lives outside `InwOpState10` and needs
  `Navisworks.Clash.Mfc.Interop` — unverified, so it is not included.
- **TimeLiner / Quantification**: likewise, not wired up.
- **`state.CreatePicture`**: COM exposes it, but on Navisworks 2026 it raises
  `Catastrophic failure` for every parameter combination, even with the window
  visible. `capture_screenshot` therefore grabs the Roamer window directly
  through GDI (`PrintWindow` with `PW_RENDERFULLCONTENT`, falling back to
  `BitBlt`), with automatic detection of a blank white/black capture.
- **`InwOaPath.Serialise`**: Navisworks returns `Not implemented`, which is why
  ids are index paths rather than serialised strings.
- **Creating or editing selection sets and viewpoints**: read and apply only, no
  creation.

## Testing

```powershell
python test_connection.py                                  # auto-detects a model
python test_connection.py "D:\projects\bridge_super_t.nwd" # specific model
```

The script runs 36 real operations against a real model, including **negative**
checks (bad id, colour out of range, wrong file extension must all fail) and one
semantic check: an isolate that hides 0 branches counts as FAIL, because that is
exactly the "reports ok but the screen does not change" failure mode.

## Development

```powershell
pip install -r requirements-dev.txt
ruff check .        # lint
pytest              # 62 tests, Navisworks NOT required
```

`tests/` runs on a machine without Navisworks because the client connects
lazily — registering tools never touches COM:

| File | Covers | Needs Windows |
|---|---|---|
| `test_server.py` | Id parsing, value conversion, COM member access, file validation, the `safe()` contract | partly |
| `test_tool_contracts.py` | The tool surface the model sees: count, descriptions, JSON schemas | yes |
| `test_repo_layout.py` | Documentation and code stay in sync — the tool tables in both READMEs must match `server.py` | no |

The part that needs a real Navisworks lives in `test_connection.py` and is run
by hand.

See [CONTRIBUTING.md](CONTRIBUTING.md) for conventions and the pre-PR checklist,
[SECURITY.md](SECURITY.md) for the trust model (this server gives a language
model control of an application on your machine), and [CHANGELOG.md](CHANGELOG.md)
for release history.

## License

[MIT](LICENSE) © 2026 Xuân Tình
