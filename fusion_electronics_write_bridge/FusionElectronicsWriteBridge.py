"""Fusion add-in: a minimal, local-only MCP write bridge for Electronics.

The Fusion Electronics API exposes rich read objects but does not expose
mutators for parts, wires, routes, or polygons.  Fusion's own Electronics
editor does expose a command line, so this bridge serializes validated EAGLE
commands onto Fusion's UI thread and lets an MCP client verify the resulting
design with its existing Electronics read tools.
"""
import adsk.core
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 27183
EVENT_ID = "fusionElectronicsWriteBridgeEvent"
MAX_COMMAND_LENGTH = 4096
MAX_BATCH_SIZE = 128

_jobs = queue.Queue()
_handlers = []
_server = None
_server_thread = None
_event = None


def _is_electronics_product():
    product = adsk.core.Application.get().activeProduct
    return product and "electron" in product.objectType.lower()


def _status():
    """Return active Fusion state before a potentially stateful write."""
    app = adsk.core.Application.get()
    ui = app.userInterface
    command_ids = ["NewElectronDesignDocumentCommand", "NewElectronSchDocumentCommand", "Electron::FocusEagleCommandLine"]
    return {
        "document": app.activeDocument.name if app.activeDocument else None,
        "product_type": app.activeProduct.objectType if app.activeProduct else None,
        "is_electronics": bool(_is_electronics_product()),
        "available_commands": {command_id: bool(ui.commandDefinitions.itemById(command_id)) for command_id in command_ids},
    }


def _validate_command(value):
    command = str(value).strip()
    if not command or len(command) > MAX_COMMAND_LENGTH or "\n" in command or "\r" in command:
        raise ValueError("Command must be one non-empty line of at most 4096 characters.")
    return command


def _send_text(text):
    """Send one command to the focused Fusion Electronics command line."""
    if not _is_electronics_product():
        raise RuntimeError("Activate a Fusion Electronics schematic or board before writing.")
    command = _validate_command(text)
    ui = adsk.core.Application.get().userInterface
    focus = ui.commandDefinitions.itemById("Electron::FocusEagleCommandLine")
    if not focus:
        raise RuntimeError("Fusion Electronics command line is unavailable.")
    focus.execute()
    # Send UTF-16 characters, rather than virtual-key codes. Virtual-key input
    # loses punctuation such as ':' and '(', which are common in EAGLE commands.
    import ctypes
    user32 = ctypes.windll.user32
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_void_p)]
    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("ki", KEYBDINPUT)]
    inputs = []
    for char in command:
        inputs.append(INPUT(1, KEYBDINPUT(0, ord(char), 0x0004, 0, None)))
        inputs.append(INPUT(1, KEYBDINPUT(0, ord(char), 0x0006, 0, None)))
    inputs.extend([INPUT(1, KEYBDINPUT(0x0D, 0, 0, 0, None)), INPUT(1, KEYBDINPUT(0x0D, 0, 0x0002, 0, None))])
    payload = (INPUT * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), ctypes.byref(payload), ctypes.sizeof(INPUT)) != len(inputs):
        raise RuntimeError("Fusion Electronics command text could not be injected.")
    return {"submitted": command}


def _new_schematic():
    ui = adsk.core.Application.get().userInterface
    definition = ui.commandDefinitions.itemById("NewElectronSchDocumentCommand")
    if not definition:
        raise RuntimeError("New Electronics Schematic command is unavailable.")
    definition.execute()
    return {"created": "schematic"}


def _new_design():
    ui = adsk.core.Application.get().userInterface
    definition = ui.commandDefinitions.itemById("NewElectronDesignDocumentCommand")
    if not definition:
        raise RuntimeError("New Electronics Design command is unavailable.")
    definition.execute()
    return {"created": "electronics_design"}


def _batch(arguments):
    commands = arguments.get("commands")
    if not isinstance(commands, list) or not commands:
        raise ValueError("commands must be a non-empty array.")
    if len(commands) > MAX_BATCH_SIZE:
        raise ValueError("A batch can contain at most %d commands." % MAX_BATCH_SIZE)
    results = []
    for index, command in enumerate(commands):
        try:
            results.append({"index": index, **_send_text(command)})
        except Exception as exc:
            raise RuntimeError("Batch stopped at command %d: %s" % (index, exc))
    return {"submitted_count": len(results), "commands": results}


def _generate_board():
    if not _is_electronics_product():
        raise RuntimeError("Activate a schematic before generating its board.")
    return _send_text("BOARD")


def _export(arguments):
    command = _validate_command(arguments.get("command", ""))
    if not command.upper().startswith("EXPORT "):
        raise ValueError("Export requests must use one explicit EAGLE EXPORT command.")
    return _send_text(command)


def _dispatch(tool, arguments):
    if tool == "electronics_status":
        return _status()
    if tool == "electronics_create_design":
        return _new_design()
    if tool == "electronics_create_schematic":
        return _new_schematic()
    if tool == "electronics_command":
        return _send_text(arguments.get("command", ""))
    if tool == "electronics_batch":
        return _batch(arguments)
    if tool == "electronics_generate_board":
        return _generate_board()
    if tool == "electronics_erc":
        return _send_text("ERC")
    if tool == "electronics_drc":
        return _send_text("DRC")
    if tool == "electronics_refill_polygons":
        return _send_text("RATSNEST")
    if tool == "electronics_export":
        return _export(arguments)
    raise ValueError("Unknown tool: " + tool)


class _MainThreadHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        while True:
            try:
                job = _jobs.get_nowait()
            except queue.Empty:
                return
            try:
                job["result"] = _dispatch(job["tool"], job["arguments"])
            except Exception as exc:
                job["error"] = str(exc)
            finally:
                job["done"].set()


def _submit(tool, arguments):
    done = threading.Event()
    job = {"tool": tool, "arguments": arguments or {}, "done": done}
    _jobs.put(job)
    adsk.core.Application.get().fireCustomEvent(EVENT_ID)
    if not done.wait(20):
        raise TimeoutError("Fusion did not complete the Electronics command within 20 seconds.")
    if "error" in job:
        raise RuntimeError(job["error"])
    return job["result"]


TOOLS = [
    {"name": "electronics_status", "description": "Return the active Fusion product/document state and required Electronics command availability.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "electronics_create_design", "description": "Create a Fusion Electronics design document.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "electronics_create_schematic", "description": "Create and activate a Fusion Electronics schematic.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "electronics_command", "description": "Run one validated EAGLE command in the active Fusion Electronics editor. Follow with Electronics read verification.", "inputSchema": {"type": "object", "properties": {"command": {"type": "string", "description": "Single-line EAGLE command."}}, "required": ["command"]}},
    {"name": "electronics_batch", "description": "Run up to 128 ordered, validated EAGLE commands. Stops on the first injection failure; verify with Electronics read.", "inputSchema": {"type": "object", "properties": {"commands": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 128}}, "required": ["commands"]}},
    {"name": "electronics_generate_board", "description": "Issue BOARD in the active schematic to create/open its linked PCB. Verify the document afterwards because Fusion can display a confirmation dialog.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "electronics_erc", "description": "Run ERC in the active schematic.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "electronics_drc", "description": "Run DRC in the active board.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "electronics_refill_polygons", "description": "Recalculate polygon fills in the active board.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "electronics_export", "description": "Run one explicit EAGLE EXPORT command. The caller supplies the target and output path; no files are fabricated.", "inputSchema": {"type": "object", "properties": {"command": {"type": "string", "description": "Single-line EAGLE EXPORT command."}}, "required": ["command"]}},
]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass
    def do_POST(self):
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
            method = request.get("method")
            request_id = request.get("id")
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "fusion-electronics-write-bridge", "version": "0.2.0"}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = request.get("params", {})
                result = {"content": [{"type": "text", "text": json.dumps(_submit(params["name"], params.get("arguments", {})), ensure_ascii=False)}]}
            else:
                raise ValueError("Unsupported MCP method: " + str(method))
            body = {"jsonrpc": "2.0", "id": request_id, "result": result}
            self.send_response(200)
        except Exception as exc:
            body = {"jsonrpc": "2.0", "id": request.get("id") if "request" in locals() else None, "error": {"code": -32000, "message": str(exc)}}
            self.send_response(500)
        payload = json.dumps(body).encode("utf-8")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run(_context):
    global _server, _server_thread, _event
    app = adsk.core.Application.get()
    handler = _MainThreadHandler()
    _event = app.registerCustomEvent(EVENT_ID)
    _event.add(handler)
    _handlers.append(handler)
    _server = ThreadingHTTPServer((HOST, PORT), _Handler)
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()


def stop(_context):
    global _server, _event
    if _server:
        _server.shutdown()
        _server.server_close()
        _server = None
    app = adsk.core.Application.get()
    for handler in _handlers:
        try:
            if _event:
                _event.remove(handler)
        except Exception:
            pass
    _handlers.clear()
    try:
        app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    _event = None
