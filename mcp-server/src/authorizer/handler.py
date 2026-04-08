"""Simple Bearer token authorizer for MCP API Gateway."""
import os

EXPECTED_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")


def lambda_handler(event, context):
    """Validate Bearer token from Authorization header."""
    token = ""
    headers = event.get("headers", {})
    auth_header = headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if token and token == EXPECTED_TOKEN:
        return {
            "isAuthorized": True,
            "context": {"principalId": "mcp-client"}
        }

    return {"isAuthorized": False}
