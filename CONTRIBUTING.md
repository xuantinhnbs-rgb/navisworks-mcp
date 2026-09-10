# Contributing

Thanks for taking an interest in this project. Issues and pull requests are
welcome — **in English or Vietnamese**, whichever you are comfortable with.

---

## Before you start

The server drives a **Windows desktop application over COM**, so meaningful
development on the client needs Windows with Navisworks installed. You can still
work on documentation, the test suite and the repository layout from any
platform — `tests/` does not need Navisworks, and part of it does not even need
Windows.

---

## Setting up

```powershell
git clone https://github.com/xuantinhnbs-rgb/navisworks-mcp.git
cd navisworks-mcp

pip install -r requirements.txt        # mcp, pywin32, Pillow
pip install -r requirements-dev.txt    # ruff + pytest

python test_connection.py              # end-to-end, needs Navisworks
```

---

## Before opening a pull request

Run the same two checks CI runs:

```powershell
ruff check .        # lint (config lives in pyproject.toml)
pytest              # contract tests, no Navisworks needed
```

Both must pass. Nothing in `tests/` requires Navisworks to be installed: the
client connects lazily, so registering tools never touches COM. If your change
can only be verified with Navisworks open, run `test_connection.py` as well and
say so in the pull request — CI cannot cover that path.

---

## Code conventions

- **Comments and docstrings are written in Vietnamese.** Keep it that way in the
  server code; a tool's docstring is what the model reads to decide when to call
  it, and rewriting them mid-project would fragment the documentation. Prose
  documentation is bilingual: `README.md` (English) and `README.vi.md`
  (Vietnamese) are kept in sync.
- **Line length 120.** Enforced by ruff.
- **`pyupgrade` rules are deliberately off.** Tool signatures use
  `Optional[...]` / `List[...]`, and those annotations generate the JSON schema
  the model sees — see the comment in `pyproject.toml`.
- **Every COM call goes through the dedicated thread** in `navisworks_client.py`
  (`_ComThread`). Never call `win32com` directly from a tool: COM apartment rules
  make that work right up until it deadlocks.

### Adding a tool

1. Write the function in `server.py`, decorated `@mcp.tool()` then `@safe` — in
   that order.
2. Return a `dict`. `safe()` adds `"ok": true` when you do not set it, so return
   plain data on success and raise on failure.
3. Raise `NwError` with a message that says **how to fix the problem**, not just
   what broke. That message goes straight to the model.
4. Never let an exception escape a tool. `safe()` is the safety net, not the
   plan — validate inputs explicitly.
5. Document parameters with `:param name:` lines. They become the JSON schema
   description the model sees.
6. Address objects by index-path string (`"1/1/2"`), and parse them with
   `NavisworksClient._parse_id`. Never accept a raw COM path from the caller.
7. Update the tool table in **both** `README.md` and `README.vi.md`, and the
   count in `tests/test_tool_contracts.py` (`EXPECTED_TOOL_COUNT`) — the test
   fails otherwise, on purpose.

### Supporting another Navisworks version

`PROG_IDS` in `navisworks_client.py` lists the ProgIDs tried in order
(`Navisworks.Document.23` = 2026, `.22` = 2025, and so on). Adding a version
means adding its ProgID and **saying in the pull request which build you tested
against** — the version table in the README distinguishes verified from
unverified on purpose.

---

## Commits and pull requests

- One logical change per commit; a short imperative subject line is enough.
- Say in the pull request which checks you ran, and on which Windows / Python /
  Navisworks versions you tested.
- Screenshots help for anything that changes what the Navisworks window shows.

---

## Reporting bugs

Use the issue templates. The single most useful thing you can attach is the
output of:

```powershell
python test_connection.py
```

It prints the Navisworks version, the ProgID it connected through, and the
result of all 36 operations — which answers most environment questions at once.
