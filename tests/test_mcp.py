from orion.mcp import handle


def test_mcp_lists_and_calls_tools():
    assert handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"]["serverInfo"]["name"] == "orion"
    names = [t["name"] for t in handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
    assert "orion_investigate" in names
    out = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "orion_investigate", "arguments": {"incident": "sms-timeouts"}}})
    assert "notification-service" in out["result"]["content"][0]["text"]
