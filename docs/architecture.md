# Platform architecture

ForgeGuide is a modular monolith with one transactional authority for configuration revisions, identities, assignments, execution and verification. The customer store, administrator application and operator guidance have separate entry points and server-enforced permissions. Legacy code is not a runtime dependency.

## Configuration graph

The server stores a portable JSON specification: ontology declarations, typed entities, typed relationships, product compatibility constraints and a gateway endpoint. These are the actual configuration model, not a separate illustration. Catalog generation traverses product slots and variant relationships. Routing traverses eligible paths, stage dependencies and required capabilities. Guidance renders configured templates against the selected parts and assigned equipment. Verification and scrap records determine stage gates. See [specification](configuration.md).

Administrative controls, import/export and MCP all use the same configuration service. Applying a specification validates graph references, allowed endpoint types, acyclic stage dependencies, variant membership, constraints and template placeholders before committing an expected revision. Configuration is distinct from runtime orders, account credentials, machine availability, evidence and review decisions.

An order snapshots the active specification and its selected variants. Its route contains actual generated task nodes and dependency edges. Later configuration edits affect the current environment while preserving historical order definitions. Equipment still reserved by active orders cannot simply be removed. Resource reconciliation checks the live available fleet and operator accounts.

## Execution invariants

- Only dependency-ready tasks can run; operators are assigned from available accounts with all required skills.
- Resource reservation and assignment are engine responsibilities. Operators cannot select another identity, route, machine or destination operator.
- Completing a machine-preparation screen explicitly starts the reserved equipment; assignment alone never issues a physical start command.
- Machine completion requires a matching authenticated callback for the current task, machine and dispatch attempt. Stale callbacks from a previous resource are ignored, and stable event IDs prevent repeat transitions.
- Manual stages complete only after applicable verification and scrap gates. Evidence alone does not prove approval.
- Human or unavailable/uncertain AI verification requires administrative review; rejected work supports corrected evidence.
- Unavailability releases compatible unfinished work for reassignment and preserves completed tasks and evidence. If no resource is eligible, work remains queued/paused rather than silently completing.
- A running physical cycle must acknowledge stop before its reservation can be released. If stopping equipment fails, the platform retains the paused task and machine reservation for reconciliation rather than starting another machine simultaneously.

## Boundaries

| Boundary | Responsibility |
| --- | --- |
| Authentication and permissions | Credential sessions, CSRF protection, administrator access, own-operator actions |
| Configuration service | Validated ontology/graph revisions; consistent UI/import/export/MCP edits |
| Catalog and constraint engine | Product slots, variant membership, compatibility and BOM |
| Routing and scheduler | Eligible configured paths, dependencies, skilled operator and machine reservations |
| Execution service | Authoritative transitions, recovery and order snapshots |
| Verification provider | Structured assessment; execution retains the decision to advance |
| Machine gateway adapter | Commands and health through the configured HTTP endpoint |
| Evidence storage | Durable uploads, access control and reference assets |

Provider boundaries permit additional verification services and protocol translation without encoding simulation into the domain. The selected platform implementation uses HTTP equipment integration and per-stage human/OpenAI verification. Frontend polling fetches authoritative state; no unsecured legacy role-switching websocket is necessary.

## Gateway protocol

One endpoint may front the full machine fleet. Equipment IDs in the specification must correspond to IDs understood by that gateway.

```text
GET /health              → 200 {"status":"ok","version":"1.0"}
GET /v1/capabilities      → supported commands/events
POST /api/v1/machines/{machine_id}/commands
```

Commands require `Authorization: Bearer <MACHINE_EVENT_TOKEN>`. The command envelope is:

```json
{
  "action": "start",
  "task_id": "task-id",
  "order_id": "order-id",
  "dispatch_id": "unique-attempt-id",
  "external_id": "unique-attempt-id",
  "callback_url": "http://backend-host:8083/api/machine/events"
}
```

The gateway acknowledges a start with HTTP 202 and `{dispatch_id,status:"accepted"}`. Repeating a dispatch ID with identical content must not run the equipment twice; reusing it for different content is a conflict. `action:"stop"` addresses the same current dispatch ID and task/order; its acknowledgement must contain the matching `dispatch_id` and `status:"stopped"` and cancel further completion of that cycle. The adapter validates these fields; a generic successful HTTP response is insufficient to release physical reservations. Repeated stop requests return the same acknowledgement. Completion is separate from acknowledgement:

```http
POST /api/machine/events
Authorization: Bearer <MACHINE_EVENT_TOKEN>
Content-Type: application/json
```

```json
{
  "task_id": "task-id",
  "machine_id": "machine-id",
  "dispatch_id": "unique-attempt-id",
  "event": "completed",
  "external_id": "unique-attempt-id:completed"
}
```

Events are `started`, `completed` or `failed`. Retries use the same event ID. The simulator is an independent server under `infra/`; the platform has no in-process simulation switch. Changing the configured IP/port is sufficient only when the real PC implements this interface or translates its native machine protocol to it.

## Runtime and deployment

| Service | Local port | Compose internal address |
| --- | ---: | --- |
| Website and API proxy | 8082 | frontend:80 |
| FastAPI | 8083 | backend:8000 |
| Gateway endpoint | 9002 | gateway:9002 |
| PostgreSQL (Compose) | 5432, bound to localhost | postgres:5432 |

Local development uses a new SQLite database. Compose uses new platform PostgreSQL and evidence volumes. Previous SQLite and Docker volume state is retained rather than destructively migrated. Initial startup has no accounts or manufactured products; first-admin setup and ordinary configuration import establish them.

Deployment tokens are generated once into ignored environment files. Operator/admin sessions are separate from equipment callback and MCP credentials. Gateway traffic and its callback require bidirectional reachability; Wi-Fi client isolation, firewalls and HTTP/TLS termination must be considered when connecting the lab PC. Production operation requires observed equipment protocol tests, backups and durable physical-command recovery beyond the simulator's in-memory command history.
