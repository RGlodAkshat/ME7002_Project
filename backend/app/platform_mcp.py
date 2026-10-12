"""Configuration tools over stateless MCP Streamable HTTP.

Every edit calls the same validated, revision-checked service as the admin API.
Transport is deliberately synchronous JSON; unsolicited SSE is not offered.
"""

from __future__ import annotations

from copy import deepcopy
import hmac
import json
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db


router = APIRouter(tags=["Manufacturing configuration MCP"])
PROTOCOL_VERSIONS = ("2025-03-26", "2025-06-18", "2025-11-25")
REVISION = {"type": "integer", "minimum": 0, "description": "Revision returned by get_configuration; a stale revision is rejected."}
SPECIFICATION = {"type": "object", "description": "Portable manufacturing specification: schema_version, environment, ontology, entities, relationships, constraints and gateway."}
ENTITY = {
    "type": "object",
    "properties": {"id": {"type": "string"}, "type": {"type": "string"}, "name": {"type": "string"}, "properties": {"type": "object"}},
    "required": ["id", "type", "name"],
    "additionalProperties": False,
}
RELATIONSHIP = {
    "type": "object",
    "properties": {"id": {"type": "string"}, "type": {"type": "string"}, "source": {"type": "string"}, "target": {"type": "string"}, "properties": {"type": "object"}},
    "required": ["id", "type", "source", "target"],
    "additionalProperties": False,
}


def tool(name: str, description: str, properties: dict, required: list[str], read_only: bool = False) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        "annotations": {"readOnlyHint": read_only, "destructiveHint": not read_only, "openWorldHint": False},
    }


TOOLS = [
    tool("get_configuration", "Read the current server-managed specification and revision before editing.", {}, [], True),
    tool("validate_configuration", "Validate graph types, references, manufacturing rules and assembly paths without applying changes.", {"specification": SPECIFICATION}, ["specification"], True),
    tool("apply_configuration", "Atomically apply a complete specification at the expected revision. Operational orders and history are retained.", {"specification": SPECIFICATION, "expected_revision": REVISION}, ["specification", "expected_revision"]),
    tool("upsert_entity", "Create or replace a graph entity through normal configuration validation. Properties are extensible.", {"entity": ENTITY, "expected_revision": REVISION}, ["entity", "expected_revision"]),
    tool("upsert_relationship", "Create or replace a typed manufacturing relationship through normal configuration validation.", {"relationship": RELATIONSHIP, "expected_revision": REVISION}, ["relationship", "expected_revision"]),
    tool("delete_entity", "Remove an unreferenced configuration entity. References and active-machine protections still apply; no cascade deletion.", {"entity_id": {"type": "string"}, "expected_revision": REVISION}, ["entity_id", "expected_revision"]),
    tool("delete_relationship", "Remove a relationship if the resulting manufacturing model remains valid.", {"relationship_id": {"type": "string"}, "expected_revision": REVISION}, ["relationship_id", "expected_revision"]),
]
TOOL_MAP = {item["name"]: item for item in TOOLS}


def validate_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    try:
        parsed = urlparse(origin)
        port = parsed.port
    except ValueError:
        raise HTTPException(403, "Invalid MCP origin")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise HTTPException(403, "Invalid MCP origin")
    allowed = {item.strip().rstrip("/") for item in get_settings().cors_origins.split(",") if item.strip() != "*"}
    same_host = parsed.hostname == request.url.hostname and port in {request.url.port, 8082}
    if origin.rstrip("/") not in allowed and not same_host:
        raise HTTPException(403, "MCP origin is not allowed")


def authorize(request: Request, db: Session) -> str:
    validate_origin(request)
    secret = get_settings().admin_integration_token
    supplied = request.headers.get("authorization", "")
    if secret and supplied.startswith("Bearer ") and hmac.compare_digest(supplied[7:].encode(), secret.encode()):
        return "mcp-integration"
    from .platform_auth import current_user, require_admin
    return require_admin(current_user(request, db)).id


def rpc_error(request_id, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, status_code=status)


def check_arguments(name: str, arguments: dict) -> None:
    schema = TOOL_MAP[name]["inputSchema"]
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
    if set(arguments) - set(schema["properties"]):
        raise ValueError("Unknown tool arguments")
    if any(key not in arguments for key in schema["required"]):
        raise ValueError("Missing required tool arguments")
    if "expected_revision" in arguments:
        revision = arguments["expected_revision"]
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ValueError("expected_revision must be a nonnegative integer")
    for key in ("specification", "entity", "relationship"):
        if key in arguments and not isinstance(arguments[key], dict):
            raise ValueError(f"{key} must be an object")
    for key in ("entity_id", "relationship_id"):
        if key in arguments and (not isinstance(arguments[key], str) or not arguments[key]):
            raise ValueError(f"{key} must be a nonempty string")


def call_tool(db: Session, name: str, arguments: dict, actor: str | None = None) -> dict:
    from .platform_configuration import apply_configuration, get_configuration, validate_specification
    check_arguments(name, arguments)
    if name == "get_configuration":
        return get_configuration(db)
    if name == "validate_configuration":
        errors = validate_specification(arguments["specification"])
        return {"valid": not errors, "errors": errors}
    if name == "apply_configuration":
        return apply_configuration(db, arguments["specification"], arguments["expected_revision"], actor=actor)
    current = get_configuration(db)
    if current["revision"] != arguments["expected_revision"]:
        raise HTTPException(409, "Configuration changed. Read its current revision before editing.")
    if current["specification"] is None:
        raise HTTPException(409, "Create or import a manufacturing specification before editing entities.")
    specification = deepcopy(current["specification"])
    if name in {"upsert_entity", "upsert_relationship"}:
        key = "entity" if name == "upsert_entity" else "relationship"
        collection = "entities" if key == "entity" else "relationships"
        item = deepcopy(arguments[key])
        item.setdefault("properties", {})
        if not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError("Entity and relationship IDs must be nonempty strings")
        specification[collection] = [value for value in specification[collection] if value["id"] != item["id"]] + [item]
    else:
        collection = "entities" if name == "delete_entity" else "relationships"
        item_id = arguments["entity_id" if name == "delete_entity" else "relationship_id"]
        if not any(value["id"] == item_id for value in specification[collection]):
            raise HTTPException(404, "Configuration element not found")
        specification[collection] = [value for value in specification[collection] if value["id"] != item_id]
    return apply_configuration(db, specification, arguments["expected_revision"], actor=actor)


@router.get("/mcp")
@router.get("/api/mcp", include_in_schema=False)
def mcp_stream(request: Request, db: Session = Depends(get_db)):
    authorize(request, db)
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
@router.post("/api/mcp", include_in_schema=False)
async def mcp(request: Request, db: Session = Depends(get_db)):
    actor = authorize(request, db)
    accept = request.headers.get("accept", "")
    if "application/json" not in accept or "text/event-stream" not in accept:
        raise HTTPException(406, "MCP clients must accept application/json and text/event-stream")
    version = request.headers.get("mcp-protocol-version")
    if version and version not in PROTOCOL_VERSIONS:
        return rpc_error(None, -32602, "Unsupported MCP protocol version", 400)
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return rpc_error(None, -32700, "Invalid JSON", 400)
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return rpc_error(None, -32600, "Invalid JSON-RPC request", 400)
    request_id = body.get("id")
    if request_id is not None and (isinstance(request_id, bool) or not isinstance(request_id, (str, int))):
        return rpc_error(None, -32600, "Invalid JSON-RPC request ID", 400)
    method, params = body["method"], body.get("params", {})
    if not isinstance(params, dict):
        return rpc_error(request_id, -32602, "Parameters must be an object")
    if "id" not in body:
        if method in {"notifications/initialized", "notifications/cancelled"}:
            return Response(status_code=202)
        return rpc_error(None, -32601, "Notification method not supported", 400)
    if method == "initialize":
        if not isinstance(params.get("protocolVersion"), str) or not isinstance(params.get("clientInfo"), dict) or not isinstance(params.get("capabilities"), dict):
            return rpc_error(request_id, -32602, "Initialization requires protocolVersion, capabilities and clientInfo")
        requested = params["protocolVersion"]
        result = {
            "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[-1],
            "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False, "listChanged": False}},
            "serverInfo": {"name": "manufacturing-configuration", "version": "1.0.0"},
            "instructions": "Read the active configuration and revision before applying edits. All changes are validated and preserve operational history.",
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "resources/list":
        result = {"resources": [{"uri": "manufacturing://configuration", "name": "Active manufacturing specification", "mimeType": "application/json"}]}
    elif method == "resources/read":
        if params.get("uri") != "manufacturing://configuration":
            return rpc_error(request_id, -32602, "Unknown manufacturing resource")
        value = call_tool(db, "get_configuration", {})
        result = {"contents": [{"uri": params["uri"], "mimeType": "application/json", "text": json.dumps(value)}]}
    elif method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or name not in TOOL_MAP:
            return rpc_error(request_id, -32602, "Unknown manufacturing tool")
        try:
            value = call_tool(db, name, params.get("arguments", {}), actor=actor)
            result = {"content": [{"type": "text", "text": json.dumps(value)}], "structuredContent": value, "isError": False}
        except (ValueError, HTTPException) as error:
            db.rollback()
            detail = error.detail if isinstance(error, HTTPException) else str(error)
            result = {"content": [{"type": "text", "text": json.dumps({"error": detail})}], "isError": True}
    else:
        return rpc_error(request_id, -32601, "Method not found")
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})
