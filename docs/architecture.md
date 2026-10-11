# Architecture and integration contract

## Scope and principles

This project is a new implementation. Legacy sources inform terminology, fan-process behavior, and likely external payload shapes only. They are not runtime dependencies.

The proof of concept is a modular monolith with a responsive web client. This keeps one transactional authority for assignments, workflow transitions, evidence, and handoffs while retaining narrow boundaries for services that genuinely need replacement.

Design constraints:

- Workflow state and policy do not depend on React, OpenAI, MQTT, or a particular machine protocol.
- External events are normalized before reaching the workflow engine.
- Every mutating command is authorized by current state; general retry/idempotency handling is a live-integration follow-up.
- Orders snapshot their selected configuration; workflow-definition versioning is a future extension.
- Reassignment and rerouting append history; they do not erase completed work or evidence.

## Runtime components and ports

| Component | Container port | Default host port | Exposure |
| --- | ---: | ---: | --- |
| Web UI / reverse proxy | 80 | 8082 | Lab clients |
| FastAPI | 8000 | 8083 | Lab clients for API docs/dev; normally proxied |
| PostgreSQL | 5432 | 5432 | Host/dev only; not required by clients |
| Mosquitto MQTT | 1883 | 1883 | Future adapters only |
| Mosquitto WebSocket | 9001 | 9001 | Future adapters only |
| Mock/lab gateway | 9002 | 9002 | Backend only |

Ports are environment-configurable host mappings. Internal Compose service names and container ports remain stable.

## Domain boundaries

| Boundary | Responsibility | Stable interface |
| --- | --- | --- |
| Catalog/ontology | Options, components, compatibility, workflow templates | Validate configuration and return reasons |
| Workflow core | Instantiate DAG, enforce prerequisites and state machine | Commands plus immutable events |
| Assignment strategy | Rank eligible available operators | Inputs: task requirements/resources; output: candidate/operator |
| Routing strategy | Select a compatible available machine/route | Inputs: capability and state; output: resource/blocked reason |
| Verification provider | Evaluate submitted evidence | Structured decision, confidence, reasons, observations |
| Machine gateway | Send commands and normalize device events | Versioned HTTP/JSON adapter contract |
| Notification publisher | Deliver persisted domain events | WebSocket now; other transports later |
| Evidence storage | Store and address uploaded photos | File metadata plus adapter-owned path |

Dependencies point inward: HTTP handlers and adapters call application services; application services call domain policies; domain code has no infrastructure imports.

## Workflow invariants

Canonical task states:

```text
blocked -> ready -> assigned -> in_progress
                              -> awaiting_verification -> completed
                              -> paused -> ready/assigned
                              -> rejected -> in_progress
```

- A task becomes `ready` only when all dependencies are completed.
- Only an eligible, available operator may hold an assignment.
- Manual work does not complete from RFID/location arrival alone.
- A verification-required task completes only after policy accepts a persisted verification attempt.
- Machine events carrying the same `external_id` are applied at most once; reuse for another task/event is rejected.
- Handoff is an immediate, recorded reassignment to an available qualified operator in this POC.
- Operator unavailability triggers recorded reassignment of affected work while completed history remains unchanged.
- Machine unavailability reroutes affected active work to a compatible available machine when one exists.

## Stable internal events

Persisted audit events returned by `GET /api/events` use this envelope:

```json
{
  "id": 81,
  "event_type": "task.assigned",
  "entity_type": "task",
  "entity_id": 12,
  "created_at": "2026-10-11T10:00:00Z",
  "payload": {}
}
```

WebSocket messages are lightweight invalidations:

```json
{"type":"task.updated","entity_id":12}
```

The implemented audit event types are:

- `order.created`, `order.completed`
- `task.assigned`, `task.accepted`, `task.awaiting_verification`, `task.completed`, `task.handed_off`, `task.rerouted`
- `operator.availability_changed`
- `machine.started`, `machine.completed`, `machine.failed`, `machine.status_changed`
- `evidence.created`, `verification.decided`, `verification.reviewed`
- `settings.machine_gateway_updated`

Audit events are stored with state changes. WebSocket delivery is advisory; clients reconnect and fetch authoritative state by REST. Consumers must tolerate new event types and payload fields.

## Machine gateway contract

There is exactly one configured gateway PC per deployment. Browsers and domain services never store individual gateway/device IP addresses. Supervisor settings persist a runtime `{protocol, host, port}` endpoint plus `use_mock`. With `use_mock:true`, the backend selects its deterministic in-process adapter and does not contact the endpoint. Set `use_mock:false` with `mock-devices:9002` to test the HTTP boundary, or with the lab gateway PC address for real integration. Secrets, if later needed, remain deployment configuration.

### Connectivity

```text
GET /health
200 {"status":"ok","adapter":"mock|lab","version":"1.0"}

GET /v1/capabilities
200 {"protocolVersion":"1.0","commands":["start","stop","reset"]}
```

### Command

```http
POST /v1/commands
Content-Type: application/json
```

```json
{
  "commandId": "uuid",
  "machineId": "MC-01",
  "action": "start"
}
```

An accepted response is `202`:

```json
{
  "commandId": "uuid",
  "gatewayEventId": "uuid",
  "status": "accepted",
  "timestamp": 1791712800
}
```

The mock implements health, capabilities, and command acknowledgement. A real adapter may poll/subscribe to the gateway and normalize incoming telemetry to the application's machine-event request.

Example normalized event:

```json
{
  "event": "completed",
  "external_id": "gateway-unique-id"
}
```

The POC deduplicates normalized machine events by `external_id`. A real adapter must additionally treat command timeout as an unknown outcome and reconcile by command ID before retrying device operations.

## Verification contract

Providers receive task criteria, captured evidence, optional reference images, and configured instructions. They return structured data:

```json
{
  "outcome": "approved",
  "confidence": 94,
  "reason": "Configured blue fan assembly is visibly complete"
}
```

Allowed outcomes are `approved`, `rejected`, and `manual_review`. The workflow policy interprets this result and owns the transition. Rejected tasks allow corrected evidence and resubmission. Manual review updates the pending attempt with its decision and reason; the audit event records when that occurred.

## Runtime configuration and recovery

Gateway configuration is edited through the supervisor UI and persisted by the backend. A change is validated and audited; the explicit test action reports reachability. If an HTTP gateway command is unreachable, the API reports failure and the persisted workflow state remains recoverable.

Operator unavailability releases affected assigned/in-progress/rejected work and immediately attempts a recorded compatible reassignment. Machine unavailability immediately attempts rerouting. If no compatible operator or machine exists, the task returns to `ready`; the event history and completed work remain intact.

## Network assumptions

- All lab clients and devices can route to the host/gateway on one network; wireless client isolation must be disabled or bypassed.
- The host firewall admits TCP `8082` for the UI and, when accessed directly, `8083` for the API.
- Backend-to-gateway traffic reaches the runtime-configured host and port.
- Outbound HTTPS is available for OpenAI.
- MQTT is optional for this POC and is not authoritative workflow state.
- The bundled anonymous MQTT and plain HTTP settings are demo-only.

## Real adapter replacement checklist

1. Capture actual gateway protocol, authentication, machine IDs, failure modes, and sample messages.
2. Implement or translate to the versioned gateway contract without leaking transport types into domain code.
3. Add contract tests using recorded, sanitized payloads.
4. Configure gateway host/IP and port through supervisor settings and verify `/health` and capabilities.
5. Implement and test command idempotency, timeout reconciliation, duplicate-event suppression, disconnect/reconnect, and malformed messages.
6. Run one machine in shadow mode before allowing it to advance production workflow.
7. Switch the adapter/configuration; retain the mock for deterministic demos and tests.
