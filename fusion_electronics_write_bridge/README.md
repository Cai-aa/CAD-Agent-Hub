# Fusion Electronics Write Bridge

Local-only Fusion Add-In that exposes a small MCP endpoint at
`http://127.0.0.1:27183/mcp`. It bridges selected Fusion Electronics editor
commands to an MCP client, always serializing calls to Fusion's UI thread.

Tools: inspect the active Fusion state, create an Electronics design or
schematic, execute one EAGLE command or an ordered batch, generate the linked
board, ERC, DRC, polygon refill, and explicit EAGLE export. Use the existing
Autodesk Fusion MCP `electronics_read` tool after each write to verify the
design state.

Version 0.2 uses UTF-16 `SendInput` for the command line, so punctuation and
non-ASCII text are not corrupted by virtual-key translation. The bridge only
reports that Fusion accepted each command for injection; it does not claim the
design operation completed. Verify parts, nets, board signals, and errors with
`electronics_read` after every phase.

Install by copying this directory to the Fusion Add-Ins folder, then start it
from Fusion's Add-Ins dialog. Register the local HTTP endpoint in the MCP
client and restart the client so it discovers the additional tools.
