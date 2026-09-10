# Security Policy

## Trust model — read this before you connect the server

This MCP server hands a language model **direct control of Autodesk Navisworks
on your machine**. That is the whole point of the project, and it is also the
main thing to be aware of:

| Capability | What it means in practice |
|---|---|
| `open_model`, `append_model` | Any file the Windows user can read can be opened into the session |
| `save_model_as` | Files are written to a path the model chooses, overwriting what is there |
| `capture_screenshot` | A PNG of the Navisworks window is written to a path the model chooses — whatever is on screen ends up in that file |
| `hide_objects`, `isolate_objects`, `set_color`, `set_transparency` | The appearance of the open model is changed; `reset_appearance` and `show_all_objects` undo it |
| `show_navisworks_window` | A hidden Navisworks instance can be made visible on your desktop |

There is **no sandbox and no confirmation prompt inside the server**. Every
guard rail lives in the MCP client. So:

- **Only connect this server to an MCP client you trust**, and keep that
  client's tool-approval prompts on rather than blanket-approving everything.
- **Work on copies of your models** while you get used to it. Navisworks has no
  undo for a `save_model_as` that already happened.
- The server **starts Navisworks itself** if none is running, in hidden mode.
  That process outlives the conversation — close it when you are done.
- Treat model content as untrusted input if it came from outside your
  organisation: text inside an IFC or Revit property can carry prompt-injection
  payloads that the model will read when it queries the model tree.

The server opens no network port and sends your data nowhere. It communicates
over stdio with the local MCP client only, and with Navisworks over local COM.

## Supported versions

Only the latest commit on `main` is supported. There are no maintenance
branches.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Report it privately through GitHub:
[**Security → Report a vulnerability**](https://github.com/xuantinhnbs-rgb/navisworks-mcp/security/advisories/new)

Please include the affected file or tool, what an attacker could achieve, and a
minimal way to reproduce it. Reports in English or Vietnamese are both fine.

This is a personal, unpaid project — expect an answer in days, not hours, and no
formal SLA. Credit will be given in the changelog unless you prefer otherwise.
