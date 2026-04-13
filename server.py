import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Tuple

APP_NAME = "buy-now-or-wait-v2"
TOOL_NAME = "decide_buy_now_or_wait"
PROTOCOL_VERSION = "2024-11-05"
SAVINGS_PER_DAY_THRESHOLD = 10.0


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
                        "urgency": {"type": "string", "enum": ["urgent", "not_urgent"]},
                    },
                    "required": ["current_price", "future_price", "wait_time_days", "urgency"],
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "decision": {"type": "string", "enum": ["buy_now", "wait"]},
                        "savings": {"type": "number"},
                        "wait_cost": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["decision", "savings", "wait_cost", "reason"],
                    "additionalProperties": False,
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
    urgency = str(arguments["urgency"])

    savings = round(current_price - future_price, 2)
    wait_cost = round(wait_time_days, 2)

    if urgency == "urgent":
        decision = "buy_now"
        reason = (
            "Urgency is 'urgent', so the deterministic rule is to buy now "
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

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "app": APP_NAME})
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
