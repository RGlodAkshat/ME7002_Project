# HTTP API

Base path is `/api`; `/health` and `/mcp` also exist outside it. IDs are opaque strings. JSON is used except multipart evidence uploads. Errors use `{ "detail": "message" }`; state/revision conflicts return 409. `/docs` provides the live OpenAPI schema.

## Authentication and permissions

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/auth/status` | Whether first-administrator setup is required |
| POST | `/auth/setup` | Create the first administrator using `{name,email,password}` |
| POST | `/auth/login` | Authenticate `{email,password}` |
| GET | `/auth/me` | Current user and CSRF token |
| POST | `/auth/logout` | End the current session |
| GET / POST | `/users` | Administrator lists/creates accounts |
| PATCH | `/users/{id}` | Administrator edits account qualifications, legacy skills, status or credentials |
| PATCH | `/operator/availability` | Operator changes only their own availability |
| GET | `/skills` | Admin: ontology/process-derived skill options and their related stages |
| GET | `/qualifications` | Admin: ontology-defined qualification options, granted skills, processes and compatible roles |

Login/setup return `{user,csrf_token}` and set an HttpOnly session cookie. Mutations under authenticated sessions require `X-CSRF-Token`. User roles are `admin` and `operator`. Backend permission checks protect administrative routes and each operator task; manipulating the hash route or guessing another task ID does not bypass authorization.

Account creation/edit accepts `qualifications:["qualification-id",...]`. IDs must refer to configured qualification definitions compatible with the account role. Administrator-issued awards are persisted as operational `platform_user_qualifications` facts with active status, issuer and assignment time; they are not login records inside the portable ontology. Explicitly sending `qualifications` replaces active awards, while omitting it preserves them. User responses include active qualification IDs and effective skills from their grants. Processes with `requires_qualification` require an actual active award as well as all required skills; supplying a legacy `skills` string cannot bypass that requirement. Configurations without personnel relations retain the earlier process-derived skill behavior. Configured personnel roles do not create new HTTP authorization privileges.

## Manufacturing configuration

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/configuration` | `{revision,specification}`; specification may initially be null |
| POST | `/configuration/validate` | Validate `{specification}` without applying it |
| PUT | `/configuration` | Atomically apply `{specification,expected_revision}` |
| GET | `/configuration/export` | Portable active specification |
| GET | `/configuration/schema` | Supported model help |
| POST | `/configuration/import-turtle` | Validate/project `{turtle}` to a specification without applying it |

These are administrator operations. Imports, manual graph edits and MCP use this same service. Expected revision prevents lost updates; orders and users are not overwritten by importing configuration. See [configuration model](configuration.md).

## Separate public store

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/shop/catalog` | Configured environment and products with their slots/variants/visual descriptors |
| POST | `/shop/validate` | Validate `{product_id,selections}` and return BOM and eligible paths |
| POST | `/shop/converse` | Interpret selections from `{product_id,message,selections}` |
| POST | `/shop/orders` | Create an order from `{product_id,selections,customer_name,confirmed:true}` |
| GET | `/shop/reference/{filename}` | Configured public reference photo assets |

Selections map slot IDs to variant IDs; fixed slots are supplied by the catalog. No fan colours, fixed stages or whole-product combinations are embedded in these endpoints. The customer must confirm before an order is created.

## Operations and guidance

| Method | Path | Permission and purpose |
| --- | --- | --- |
| GET | `/orders`, `/orders/{id}` | Admin: orders and actual routes |
| POST | `/orders/{id}/cancel` | Admin: request cancellation using `{reason}`; preserves history and holds unresolved running equipment |
| GET | `/operator/tasks` | Operator: own assigned work only |
| POST | `/tasks/{id}/run` | Assigned operator: command prepared equipment, or open an observation window for an observed stage |
| POST | `/tasks/{id}/evidence` | Assigned operator: multipart image capture/upload |
| POST | `/tasks/{id}/complete` | Assigned operator: finish current manual operation subject to configured gates |
| POST | `/tasks/{id}/scrap` | Assigned operator: `{quantity,reason}` declaration |
| GET | `/reviews` | Admin: pending verification submissions |
| POST | `/reviews/{id}` | Admin: `{decision:approve|reject,reason}` |
| GET | `/machines` | Admin: configured fleet and runtime reservations |
| PATCH | `/machines/{id}` | Admin: `{status:available|down|maintenance}` |
| POST | `/gateway/test` | Admin: test the active configured endpoint |
| POST | `/machine/events` | Equipment integration: authenticated normalized event |
| GET | `/orders/{id}/graph` | Admin: the order's selected ontology instance, current operations, assignments and evidence |
| GET | `/telemetry/status` | Admin: safe central database identity and latest configured machine rows |
| POST | `/telemetry/sync` | Admin: read central telemetry now using the normal read-only bridge |
| POST | `/tasks/{id}/confirm-stopped` | Admin: `{physical_stop_confirmed:true}` releases a paused observed task after an actual physical stop |

Assignments are automatic. There is no operator impersonation selector, task acceptance, operator-driven routing or manual handoff API in the redesigned workflow. Machine start follows preparation; task assignment never starts equipment by itself.

For the central-database lab integration, stages use `execution_mode:"observed"`. `/run` opens an assignment-scoped observation window and never sends a machine command. `instruction_phase` changes from `preparation` to `work`, and instructions name the assigned equipment/workstation. `next_operation` identifies the next planned destination, explicitly distinguishing a plan from an assignment. Missing or ambiguous signals do not approve work. Configured human verification permits a specialist to confirm the entire physical operation; observed reservations cannot be released while physical equipment may still be running merely because an operator becomes unavailable.

Orders include selected configuration, configuration revision, task states, the full selected product `bom`, and a route `{path_id,path_name,nodes,edges}`. `bom` is the order's kit requirement; do not sum task part lists, because the same part can appear at several process stages. Nodes are real order tasks; edges use task IDs. Tasks include instructions rendered for their selected parts and assigned machine, applicable verification/scrap protocols, evidence, verification outcome, `order_status` and `cancellation_pending`. Task states include `queued`, `in_progress`, `awaiting_verification`, `awaiting_review`, `rejected`, `paused`, `completed` and `cancelled`.

Cancellation rejects completed orders with 409 and is idempotent for orders already cancelled/cancelling. Work without unresolved running equipment becomes `cancelled`; completed tasks and evidence remain intact and pending reviews are cancelled. An observed machine with an opened cycle remains paused, with its operator/equipment reservations held and order status `cancelling`, even if raw signals suggest completion. An administrator must actually confirm the physical stop with `/tasks/{id}/confirm-stopped` before resources are released. A commanded gateway may instead supply a validated stop acknowledgement. Neither order cancellation nor an observed stop-confirmation screen remotely stops laboratory equipment. Cancellation records include reason, requester, request time and individual stop-confirmation actors/times. Further starts, completions and verification mutations are blocked for cancelling/cancelled work.

Machine callbacks require `Authorization: Bearer <MACHINE_EVENT_TOKEN>` and `{task_id,machine_id,dispatch_id,event,external_id}`. The dispatch ID distinguishes the current attempt from obsolete telemetry; external event IDs provide deduplication. See [gateway protocol](architecture.md#gateway-protocol).

## MCP

POST `/mcp` and `/api/mcp` expose the same authenticated stateless Streamable HTTP endpoint. Supported JSON-RPC methods include `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `resources/list` and `resources/read`. Configuration tools and revision rules are documented in [MCP usage](mcp.md). This interface is an administrator integration, not an independent configuration database.
