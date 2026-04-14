import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Tuple

APP_NAME = "buy-now-or-wait-v2"
TOOL_NAME = "decide_buy_now_or_wait"
PROTOCOL_VERSION = "2024-11-05"
SAVINGS_PER_DAY_THRESHOLD = 10.0
CONTACT_EMAIL = "sidcraigau@gmail.com"
OPENAI_APPS_CHALLENGE_TOKEN = "W8pCh6el9UMivB2UlLu_hJxTu52QcYM1d7APAjiMhyhU"

PRIVACY_HTML = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Buy Now or Wait v2 - Privacy Policy</title>
</head>
<body>
  <h1>Privacy Policy</h1>
  <p>Buy Now or Wait v2 processes user-provided shopping decision inputs to return deterministic guidance.</p>
  <h2>Inputs We Process</h2>
  <ul>
    <li>current_price</li>
    <li>future_price</li>
    <li>wait_time_days</li>
    <li>urgency</li>
  </ul>
  <h2>How Data Is Used</h2>
  <p>Inputs are used only to compute a deterministic buy-now-or-wait recommendation and reasoning for the current request.</p>
  <h2>Data Sharing</h2>
  <p>We do not sell user input data and do not share it with third parties for advertising.</p>
  <h2>Retention</h2>
  <p>This service is stateless and does not intentionally retain request data beyond normal transient processing and platform operational logs.</p>
  <h2>Contact</h2>
  <p>For privacy questions, contact <a href=\"mailto:{CONTACT_EMAIL}\">{CONTACT_EMAIL}</a>.</p>
</body>
</html>
"""

TERMS_HTML = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Buy Now or Wait v2 - Terms of Service</title>
</head>
<body>
  <h1>Terms of Service</h1>
  <p>Buy Now or Wait v2 is provided for informational use only.</p>
  <h2>No Guarantee</h2>
  <p>We do not guarantee future prices, discounts, product availability, or timing of promotions.</p>
  <h2>User Responsibility</h2>
  <p>Users must verify final prices, seller terms, and eligibility for any discount before purchasing.</p>
  <h2>Service Availability</h2>
  <p>Service features and availability may change at any time.</p>
  <h2>Contact</h2>
  <p>For terms questions, contact <a href=\"mailto:{CONTACT_EMAIL}\">{CONTACT_EMAIL}</a>.</p>
</body>
</html>
"""


def jsonrpc_result(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def jsonrpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def initialize_payload() -> Dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "serverInfo": {
            "name": APP_NAME,
            "version": "1.0.0",
        },
        "capabilities": {
            "tools": {},
        },
    }


def tools_list_payload() -> Dict[str, Any]:
    return {
        "tools": [
            {
                "name": TOOL_NAME,
                "description": (
                    "Decide whether to buy now or wait using current price, expected "
                    "future price, waiting time, and urgency."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "current_price": {"type": "number"},
                        "future_price": {"type": "number"},
                        "wait_time_days": {"type": "number", "minimum": 0},
                        "urgency": {
                            "type": "string",
                            "enum": ["urgent", "soon", "not_urgent", "flexible"],
                        },
                    },
                    "required": ["current_price", "future_price", "wait_time_days", "urgency"],
                    "additionalProperties": False,
                },
                "annotations": {
                    "readOnlyHint": False,
                    "openWorldHint": True,
                    "destructiveHint": False,
                },
            }
        ]
    }


def validate_required(arguments: Dict[str, Any]) -> Tuple[bool, str]:
    required = ["current_price", "future_price", "wait_time_days", "urgency"]
    missing = [field for field in required if field not in arguments]
    if missing:
        return False, f"Missing required field(s): {', '.join(missing)}"
    return True, ""


def decide(arguments: Dict[str, Any]) -> Dict[str, Any]:
    is_valid, error_message = validate_required(arguments)
    if not is_valid:
        raise ValueError(error_message)

    current_price = float(arguments["current_price"])
    future_price = float(arguments["future_price"])
    wait_time_days = float(arguments["wait_time_days"])
    urgency = str(arguments["urgency"]).lower().strip()

    if urgency not in {"urgent", "soon", "not_urgent", "flexible"}:
        raise ValueError("Invalid urgency. Use one of: urgent, soon, not_urgent, flexible")

    savings = round(current_price - future_price, 2)
    wait_cost = round(wait_time_days, 2)

    if urgency in {"urgent", "soon"}:
        decision = "buy_now"
        reason = (
            f"Urgency is '{urgency}', so the deterministic rule is to buy now "
            "regardless of potential savings."
        )
    else:
        if wait_time_days <= 0:
            savings_per_day = savings
        else:
            savings_per_day = savings / wait_time_days

        if savings_per_day > SAVINGS_PER_DAY_THRESHOLD:
            decision = "wait"
            reason = (
                f"Not urgent, and savings/day is {savings_per_day:.2f}, above the "
                f"threshold {SAVINGS_PER_DAY_THRESHOLD:.2f}."
            )
        else:
            decision = "buy_now"
            reason = (
                f"Not urgent, but savings/day is {savings_per_day:.2f}, at or below "
                f"the threshold {SAVINGS_PER_DAY_THRESHOLD:.2f}."
            )

    return {
        "decision": decision,
        "savings": savings,
        "wait_cost": wait_cost,
        "reason": reason,
    }


class MCPHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status_code: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status_code: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "app": APP_NAME})
            return

        if self.path == "/privacy":
            self._send_html(200, PRIVACY_HTML)
            return

        if self.path == "/terms":
            self._send_html(200, TERMS_HTML)
            return

        if self.path == "/mcp":
            self._send_json(200, {"message": "MCP endpoint is available. Use POST for JSON-RPC requests."})
            return

        if self.path == "/.well-known/openai-apps-challenge":
            self._send_text(200, OPENAI_APPS_CHALLENGE_TOKEN)
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/mcp":
            self._send_json(404, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            request = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, jsonrpc_error(None, -32700, "Parse error"))
            return

        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            result = initialize_payload()
            if "protocolVersion" not in result:
                self._send_json(500, jsonrpc_error(request_id, -32603, "protocolVersion missing"))
                return
            self._send_json(200, jsonrpc_result(request_id, result))
            return

        if method == "tools/list":
            self._send_json(200, jsonrpc_result(request_id, tools_list_payload()))
            return

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if tool_name != TOOL_NAME:
                self._send_json(200, jsonrpc_error(request_id, -32602, f"Unknown tool: {tool_name}"))
                return

            try:
                decision = decide(arguments)
            except ValueError as exc:
                self._send_json(200, jsonrpc_error(request_id, -32602, str(exc)))
                return
            except (TypeError, KeyError):
                self._send_json(200, jsonrpc_error(request_id, -32602, "Invalid arguments"))
                return

            result = {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Decision: {decision['decision']}. Savings={decision['savings']}, "
                            f"WaitCost={decision['wait_cost']}. Reason: {decision['reason']}"
                        ),
                    }
                ],
                "structuredContent": decision,
            }
            self._send_json(200, jsonrpc_result(request_id, result))
            return

        self._send_json(200, jsonrpc_error(request_id, -32601, f"Method not found: {method}"))


def run() -> None:
    port = int(os.environ.get("PORT", "8000"))
    server = HTTPServer(("0.0.0.0", port), MCPHandler)
    print(f"Serving {APP_NAME} on 0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
