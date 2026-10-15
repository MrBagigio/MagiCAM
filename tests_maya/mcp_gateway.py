"""Client minimo MCP (streamable HTTP, solo stdlib) per il gateway dcc-mcp di Maya: esegue Python DENTRO Maya.

I banchi di `tests_maya/` lo usano dal PC per pilotare il Maya aperto dall'utente (regola: niente mayapy, niente Maya
nostri con la farm al lavoro). Gateway predefinito: http://127.0.0.1:9765/mcp (dcc-mcp-maya, menu «DCC MCP»).
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

URL = "http://127.0.0.1:9765/mcp"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


class Gateway:
    def __init__(self, url: str = URL) -> None:
        self.url = url
        self.session: str | None = None
        self.n = 0
        self.exec_slug: str | None = None

    def _post(self, body: dict[str, Any], timeout: float) -> dict[str, Any] | None:
        h = dict(HEADERS)
        if self.session:
            h["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            sid = r.headers.get("Mcp-Session-Id")
            if sid:
                self.session = sid
            raw = r.read().decode("utf-8", "replace")
            ctype = r.headers.get("Content-Type", "")
        if not raw.strip():
            return None
        if "text/event-stream" in ctype:
            msgs = [json.loads(ln[5:].strip()) for ln in raw.splitlines() if ln.startswith("data:")]
            for m in reversed(msgs):
                if m.get("id") == body.get("id"):
                    return m
            return msgs[-1] if msgs else None
        return json.loads(raw)

    def rpc(self, method: str, params: dict[str, Any] | None = None, timeout: float = 120.0) -> dict[str, Any]:
        self.n += 1
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": self.n, "method": method}
        if params is not None:
            body["params"] = params
        resp = self._post(body, timeout)
        if resp is None:
            raise RuntimeError(f"{method}: risposta vuota")
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error']}")
        return resp["result"]

    def start(self) -> None:
        self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "magicam-bench", "version": "0"},
            },
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, 30.0)
        found = self.rpc("tools/call", {"name": "search", "arguments": {"query": "execute python", "kind": "tool"}})
        text = "\n".join(c.get("text", "") for c in found.get("content", []))
        m = re.search(r'"tool_slug":\s*"([^"]*execute_python)"', text)
        if not m:
            raise RuntimeError("tool execute_python non trovato sul gateway")
        self.exec_slug = m.group(1)

    def py(self, code: str, timeout: float = 600.0) -> str:
        """Esegue `code` nel Maya aperto (main thread, globali persistenti) e torna lo stdout."""
        assert self.exec_slug is not None
        res = self.rpc(
            "tools/call",
            {"name": "call", "arguments": {"tool_slug": self.exec_slug, "arguments": {"code": code}}},
            timeout,
        )
        text = "\n".join(c.get("text", "") for c in res.get("content", []))
        try:
            doc = json.loads(text[text.index("{") :])
        except (ValueError, json.JSONDecodeError) as e:
            raise RuntimeError(f"risposta non JSON: {text[:300]}") from e
        ctx = doc.get("context") or {}
        if not doc.get("success", False) or doc.get("error"):
            raise RuntimeError(f"Maya: {doc.get('error')}\n{ctx.get('stderr', '')}")
        if ctx.get("stderr"):
            print("[maya stderr]", ctx["stderr"])
        return str(ctx.get("stdout", ""))

    def py_json(self, code: str, tag: str = "JSON", timeout: float = 600.0) -> Any:
        """Esegue e legge l'ultimo `TAG=<json>` stampato."""
        out = self.py(code, timeout)
        matches = list(re.finditer(rf"{tag}=(\{{.*\}}|\[.*\])", out))
        m = matches[-1] if matches else None
        if m is None:
            raise RuntimeError(f"nessun {tag}= nello stdout:\n{out[-800:]}")
        return json.loads(m.group(1))
