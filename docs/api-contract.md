# HTTP and WebSocket API contract

Base path: `/api`. JSON is used unless a photo upload is `multipart/form-data`. Resource IDs are opaque (the POC currently serializes integer IDs). Timestamps are ISO 8601 UTC. The interactive schema at `/docs` is authoritative for implemented field details.

Errors currently use FastAPI's standard shape:

```json
{
  "detail": "Task must be in progress before completion"
}
```

State conflicts return `409`; validation errors return `422`; missing resources return `404`. Normalized machine events are idempotent when callers supply a stable `external_id`; general HTTP idempotency keys remain a live-integration follow-up.

## Health and catalog

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness/readiness summary (outside `/api`) |
| `GET` | `/api/catalog` | Product option schema, compatibility metadata, workflow summary |
| `POST` | `/api/configurations/validate` | Deterministically validate the selected colour/product mapping |
| `POST` | `/api/configurations/converse` | Propose a colour conversationally and optionally confirm/place the order |

Validation request/response:

```json
{"color":"blue"}
```

```json
{
  "valid":true,
  "configuration":{"color":"blue"},
  "bom":[
    {"component":"Gear1","part_id":"G1","bin_id":"B1","quantity":1,"product_code":"PR3"},
    {"component":"Base","part_id":"CLB","bin_id":"B16a","quantity":1,"product_code":"PR3"}
  ]
}
```

The response above abbreviates the BOM. The API returns all common and colour-specific parts. The mapping is `red -> PR1`, `green -> PR2`, `blue -> PR3`, and `white -> PR4`; every variant has the same design/component structure, with colour-specific part and source-bin identifiers returned as catalog data rather than embedded in client logic.

Conversation request:

```json
{
  "message":"I want the blue model",
  "configuration":{},
  "history":[],
  "confirmed":false,
  "customer_name":"Demo Customer"
}
```

The response includes `message`, nullable `proposed_configuration`/`configuration`, `requires_confirmation`, and nullable `order_id`. Send `confirmed:true` with the proposed `configuration` only after the customer confirms; this creates the order.

## Orders and workflows

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/orders` | Confirm configuration, snapshot it, create workflow and initial assignments |
| `GET` | `/api/orders` | List orders with their workflow tasks |
| `GET` | `/api/orders/{orderId}` | Full order, task graph, assignments, and event summary |

Order creation requires explicit confirmation:

```json
{
  "configuration":{"color":"blue"},
  "confirmed":true,
  "customer_name":"Demo Customer"
}
```

## Operators and tasks

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/operators` | List operators, skills, availability, and load |
| `GET` | `/api/operators/{operatorId}/tasks` | Operator queue and active assignment |
| `PUT` | `/api/operators/{operatorId}/availability` | Set `available`/`unavailable`; invoke recovery policy |
| `GET` | `/api/tasks/{taskId}` | Read one task and its evidence/assignment |
| `POST` | `/api/tasks/{taskId}/accept` | Accept an assigned task, optionally as a compatible operator |
| `POST` | `/api/tasks/{taskId}/start` | Acknowledge assignment and begin work |
| `POST` | `/api/tasks/{taskId}/complete` | Complete work when verification is not required |
| `POST` | `/api/tasks/{taskId}/handoff` | Record an explicit transfer to a qualified operator |
| `POST` | `/api/tasks/{taskId}/evidence` | Upload and persist photo evidence |
| `GET` | `/api/evidence/{evidenceId}/file` | Read persisted evidence for operator/supervisor review |
| `POST` | `/api/tasks/{taskId}/verify` | Run configured verification provider for latest evidence |

Availability example (`PUT`):

```json
{"available":false}
```

Handoff example:

```json
{"to_operator_id":3}
```

Evidence is multipart form data with one required `file` field (image, maximum 10 MB). Verification returns the provider's outcome, integer confidence, reason, and resulting task state.

## Machines and normalized events

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/machines` | List capability and availability state |
| `PUT` | `/api/machines/{machineId}/status` | Supervisor sets `available`, `down`, or `maintenance` |
| `POST` | `/api/machines/tasks/{taskId}/event` | Submit a normalized, idempotent machine event |

```json
{
  "event":"completed",
  "external_id":"mock-evt-001"
}
```

Only an event compatible with the current task state may advance work. Re-sending the same `external_id` and content returns current task state without reapplying the transition; using that ID for another task/event returns `409`.

## Supervisor and gateway

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/supervisor/tasks` | Cross-workflow task queue, blocked reasons, review state |
| `POST` | `/api/supervisor/tasks/{taskId}/review` | Approve/reject an attempt with a reason |
| `GET` | `/api/verifications?status=manual_review` | List verification attempts, optionally filtered by outcome |
| `POST` | `/api/verifications/{verificationId}/review` | Approve/reject a manual-review attempt |
| `GET` | `/api/settings/machine-gateway` | Read the active single gateway PC configuration/status |
| `PUT` | `/api/settings/machine-gateway` | Validate and persist host/IP and port at runtime |
| `POST` | `/api/settings/machine-gateway/test` | Test health/capabilities without changing workflow state |

Gateway update:

```json
{"protocol":"http","host":"192.168.1.50","port":9002,"enabled":true,"use_mock":false}
```

Response fields echo configuration plus `configured`, nullable `reachable`, and nullable `error`. Browser clients never call this address directly.

`use_mock:true` selects the backend's in-process mock and does not contact `host`/`port`. Use `false` with `mock-devices:9002` for the bundled HTTP mock, or with the lab gateway PC host and port for real integration.

Manual review:

```json
{"decision":"approve","reason":"Configured blue fan assembly confirmed visually"}
```

## Events and WebSocket

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/events?after_id={cursor}` | Ordered event catch-up/audit feed |
| `WS` | `/ws` | Low-latency notification stream |

WebSocket messages are `{ "type": "task.updated", "entity_id": 12 }`. Clients treat them as invalidations and fetch current REST state after reconnect. The REST event feed provides ordered catch-up by integer `id`; WebSocket delivery may repeat.

## Compatibility policy

- Additive response fields do not change the API version.
- Removing/renaming fields, changing meaning, or tightening accepted values requires a new API/schema version.
- External adapter payloads carry their own `schemaVersion` or `protocolVersion`.
- The OpenAPI document and adapter contract tests prevent UI/provider drift.
