# Platform architecture

ForgeGuide is a modular monolith with one transactional authority for configuration revisions, identities, assignments, execution and verification. The customer store, administrator application and operator guidance have separate entry points and server-enforced permissions. Legacy code is not a runtime dependency.

## Configuration graph

The server stores a portable JSON specification: ontology declarations, typed entities, typed relationships, product compatibility constraints and optional integration metadata. These are the actual configuration model, not a separate illustration. Catalog generation traverses product slots and variant relationships. Routing traverses eligible paths, stage dependencies and required capabilities. Guidance renders configured templates against the selected parts and assigned equipment. Verification and scrap records determine stage gates. See [specification](configuration.md).

The admin Ontology view is the reusable manufacturing model (type schema plus configured equipment, products, all supported variants, compatibility rules and feasible paths). An order instantiates a selected knowledge graph: its configuration snapshot, actual operation dependencies, current resource assignments and evidence. `/orders/{id}/graph` derives these facts from persisted workflow state, so reassignment changes the order graph rather than a disconnected diagram. Configuration revisions do not silently rewrite active or historical orders.

Turtle imports preserve all source RDF triples and namespace declarations as provenance. The supported lab projection creates executable product/BOM/route/resource definitions. Administrators edit that executable model through the same revisioned service as JSON imports and MCP; exported source provenance is intentionally not presented as a regenerated OWL serialization of later edits. This is not an unrestricted OWL reasoner.

Personnel definitions belong to this reusable ontology: `role`, `qualification` and `skill` entities plus `requires_skill`, `requires_qualification`, `qualification_grants_skill` and `role_allows_qualification` relationships. A qualification grants configured skills; a process can require both those skills and an issued qualification. Actual people, passwords and administrator-issued `platform_user_qualifications` facts remain operational data, separate from portable definitions. Qualification awards record active status, issuer and assignment time. Scheduling requires an active available operator with all required skills and role-compatible active awards; legacy skill strings alone cannot satisfy an explicit qualification requirement. Older configurations without personnel relationships retain their skill-list contract. Personnel role definitions do not widen backend HTTP authorization.

Each order exposes its complete selected-product `bom`, representing the kit once. Stage `parts` lists are consumption/guidance views of that same kit, not separate inventory deductions or quantities to total together. Source-defined route snapshots, runtime assignments and verification facts form the order-specific graph. This does not introduce physical unit/RFID inventory tracking or a stock ledger.

## Central database integration

The lab configuration uses a read-only PostgreSQL bridge through `TELEMETRY_DATABASE_URL`, separate from the platform's operational database. Existing publishers write compatible `smart_database` telemetry tables. The platform never accesses CNC, PLC, OPC UA, FOCAS, MQTT or machine WebSocket endpoints in this integration. The optional command gateway is a distinct adapter for other configurations.

Observed machine work opens its collection window before a physical cycle. Persisted observation cursors and strict configured signal reducers prevent duplicate rows or prior batches from being treated as current completion. A monotonic `platform_ingest_id` is preferred; existing tables fall back to timestamp watermarks with documented limitations. Source and backend clocks must agree for batch-window correlation. The publisher's `Online` status is never sufficient completion evidence. Missing subprogram/running signals require the configured trained-specialist review, not a fabricated event. See [lab guide](lab-demo.md).

Administrative controls, import/export and MCP all use the same configuration service. Applying a specification validates graph references, allowed endpoint types, acyclic stage dependencies, variant membership, constraints and template placeholders before committing an expected revision. Configuration is distinct from runtime orders, account credentials, machine availability, evidence and review decisions.

An order snapshots the active specification and its selected variants. Its route contains actual generated task nodes and dependency edges. Later configuration edits affect the current environment while preserving historical order definitions. Equipment still reserved by active orders cannot simply be removed. Resource reconciliation checks the live available fleet and operator accounts.

## Execution invariants

- Only dependency-ready tasks can run; operators are assigned from active available accounts with all required skills and explicitly required qualifications.
- Resource reservation and assignment are engine responsibilities. Operators cannot select another identity, route, machine or destination operator.
- Completing machine preparation opens a current observation window for `observed` stages, or explicitly commands the reserved equipment for gateway stages. Assignment alone never issues a physical start command; observed lab stages never send one.
- Gateway machine completion requires a matching authenticated callback for the current task, machine and dispatch attempt. Stale callbacks from a previous resource are ignored, and stable event IDs prevent repeat transitions. Observed stages use only strict configured central-database rules or trained-specialist review; raw availability alone never proves completion.
- Manual stages complete only after applicable verification and scrap gates. Evidence alone does not prove approval.
- Human or unavailable/uncertain AI verification requires administrative review; rejected work supports corrected evidence.
- Unavailability releases compatible unfinished work for reassignment and preserves completed tasks and evidence. If no resource is eligible, work remains queued/paused rather than silently completing.
- A running physical cycle must acknowledge stop before its reservation can be released. If stopping equipment fails, the platform retains the paused task and machine reservation for reconciliation rather than starting another machine simultaneously.
- Cancellation preserves completed work and evidence. Untouched future operations are cancelled, but unresolved observed cycles remain paused and reserved until an administrator confirms a real physical stop. Cancellation blocks additional work and records requester/reason and stop confirmations; it never claims to remotely stop an observed lab machine.

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

The explicitly requested `start-demo.sh` workflow creates a separate persistent `.run/demo` environment, provisions individual qualified accounts, imports through the ordinary API and starts independent raw-data publishers against real local PostgreSQL. Native PostgreSQL binaries may be installed into that ignored directory without Docker. Application startup itself remains unseeded; there is no simulator switch in core execution. Demo credentials are private files, PostgreSQL is loopback-only, and the website/API bind on the LAN. Demo publishers cannot approve work or bypass process gates. See [demo instructions](lab-demo.md).

Deployment tokens are generated once into ignored environment files. Operator/admin sessions are separate from equipment callback and MCP credentials. Gateway traffic and its callback require bidirectional reachability; Wi-Fi client isolation, firewalls and HTTP/TLS termination must be considered when connecting the lab PC. Production operation requires observed equipment protocol tests, backups and durable physical-command recovery beyond the simulator's in-memory command history.
