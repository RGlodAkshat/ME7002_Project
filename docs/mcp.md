# Configuration MCP integration

The server exposes stateless MCP Streamable HTTP at `/mcp` and the equivalent proxy path `/api/mcp`. Both use the active manufacturing configuration service. No second MCP configuration store exists.

Use `Authorization: Bearer <ADMIN_INTEGRATION_TOKEN>` from the ignored deployment environment. The launcher creates this credential once; it gives administrative configuration access and should be loaded into an integration's secret/environment settings. Browser administrator sessions can instead authenticate with the session cookie and `X-CSRF-Token`. Operators do not have configuration-tool permission.

The transport supports protocol versions `2025-03-26`, `2025-06-18` and `2025-11-25`. POST requests use `Content-Type: application/json` and must accept both `application/json` and `text/event-stream`. Responses are synchronous JSON; unsolicited server events/subscriptions are not implemented. GET does not open an event stream and returns 405.

With `ADMIN_INTEGRATION_TOKEN` already set in your local shell environment, initialize a client:

```bash
curl --fail-with-body http://localhost:8083/mcp \
  -H "Authorization: Bearer ${ADMIN_INTEGRATION_TOKEN}" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"configuration-client","version":"1.0"}}}'
```

Send `notifications/initialized`, then `tools/list` or `tools/call`. On subsequent requests include `MCP-Protocol-Version: 2025-11-25`. The stateless service does not issue a session ID. Do not paste generated credentials into source-controlled client configuration or logs.

| Tool | Arguments | Behavior |
| --- | --- | --- |
| `get_configuration` | `{}` | Current specification and revision |
| `validate_configuration` | `{specification}` | Validate without modifying state |
| `apply_configuration` | `{specification,expected_revision}` | Atomic full configuration edit |
| `upsert_entity` | `{entity,expected_revision}` | Add/replace one typed entity |
| `upsert_relationship` | `{relationship,expected_revision}` | Add/replace one typed graph link |
| `delete_entity` | `{entity_id,expected_revision}` | Remove an entity if graph/runtime protections allow it |
| `delete_relationship` | `{relationship_id,expected_revision}` | Remove a link if the remaining model is valid |

Entity objects use `{id,type,name,properties}`; relationship objects use `{id,type,source,target,properties}`. Always read the current configuration before editing. Edits validate the complete resulting graph and require the observed revision. A variant entity plus its `variant_of` relationship should be added atomically with `apply_configuration`, since a standalone unlinked variant is invalid. Likewise, dependent graph removals should be prepared as one valid specification change; deletion never cascades silently.

Example read request body:

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_configuration","arguments":{}}}
```

Successful tool responses include text content, `structuredContent` and `isError:false`. Validation/revision/permission failures do not mutate the active configuration. Tool execution errors return `isError:true`; malformed protocol requests return JSON-RPC errors. Tool schemas are available from `tools/list`.

The read-only resource `manufacturing://configuration` is available through `resources/list` and `resources/read`. It contains the same `{revision,specification}` wrapper. Configuration-changing tools preserve orders, evidence and account state and inherit the same active-machine removal protection as administrative import.
