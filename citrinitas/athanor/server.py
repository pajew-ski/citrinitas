"""The one door: a small HTTP API with a bearer token. It reads the lake and writes nothing (Spec F8, C9, C17)."""
from __future__ import annotations

import hmac
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..quaestiones import relatio
from . import guard, lake, status, templates
from .core import Paths, commit

MAX_BODY = 256 << 10


def _asof(v) -> str:
    return datetime.fromisoformat(str(v).replace("Z", "")).replace(tzinfo=None).isoformat(sep=" ")


def answer(p: Paths, body: dict) -> dict:
    """Answer one /query request. Raises guard.Refused or templates.BadRequest for the caller to report."""
    asof = _asof(body["asof"]) if body.get("asof") else None
    if body.get("template") == "status":
        return status.build(p)
    if ("sql" in body) == ("template" in body):
        raise templates.BadRequest("give either template or sql")
    con = lake.connect(p, guard=True, asof=asof)
    try:
        if "sql" in body:
            res = guard.run(con, str(body["sql"]))
        else:
            sql, args = templates.render(str(body["template"]), body.get("params"))
            res = guard.run(con, sql, args, max_rows=templates.MAX_ROWS, timeout_s=templates.TIMEOUT_S)
    finally:
        con.close()
    return {"ok": True, "asof": asof, "commit": commit(), **res}


def make_handler(p: Paths, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "citrinitas"

        def log_message(self, fmt, *args):  # one line per request to the journal, never the token or the body
            print(f"{self.address_string()} {fmt % args}", flush=True)

        def _send(self, code: int, obj: dict) -> None:
            data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _authorised(self) -> bool:
            given = self.headers.get("Authorization", "")
            if hmac.compare_digest(given.encode(), f"Bearer {token}".encode()):
                return True
            self._send(401, {"ok": False, "error": "missing or wrong bearer token"})
            return False

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                return self._send(200, {"ok": True, "commit": commit()})
            if self.path == "/status":
                if self._authorised():
                    self._send(200, status.build(p))
                return None
            return self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path not in ("/query", "/relatio/check"):
                return self._send(404, {"ok": False, "error": "not found"})
            if not self._authorised():
                return None
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self._send(413, {"ok": False, "error": f"body must be 1 to {MAX_BODY} bytes"})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
            except ValueError as e:
                return self._send(400, {"ok": False, "error": f"bad request: {e}"})
            try:
                if self.path == "/query":
                    return self._send(200, answer(p, body))
                verdict = relatio.check(body, lambda asof: lake.connect(p, guard=True, asof=_asof(asof)))
                return self._send(200, verdict)
            except (guard.Refused, templates.BadRequest, ValueError, KeyError) as e:
                return self._send(400, {"ok": False, "error": str(e)})
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]})

    return Handler


def serve(p: Paths, host: str = "0.0.0.0", port: int = 8765) -> None:  # noqa: S104  the token is the gate
    token_file = p.etc / "token"
    token = token_file.read_text(encoding="utf-8").strip() if token_file.exists() else ""
    if len(token) < 24:
        raise SystemExit(f"{token_file} is missing or too short: refusing to serve without a token")
    httpd = ThreadingHTTPServer((host, port), make_handler(p, token))
    print(f"citrinitas {commit()[:12]} listening on {host}:{port}", flush=True)
    httpd.serve_forever()
