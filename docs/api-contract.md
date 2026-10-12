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
| PATCH | `/users/{id}` | Administrator edits account skills, status or credentials |
| PATCH | `/operator/availability` | Operator changes only their own availability |

Login/setup return `{user,csrf_token}` and set an HttpOnly session cookie. Mutations under authenticated sessions require `X-CSRF-Token`. User roles are `admin` and `operator`. Backend permission checks protect administrative routes and each operator task; manipulating the hash route or guessing another task ID does not bypass authorization.

## Manufacturing configuration

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/configuration` | `{revision,specification}`; specification may initially be null |
| POST | `/configuration/validate` | Validate `{specification}` without applying it |
| PUT | `/configuration` | Atomically apply `{specification,expected_revision}` |
| GET | `/configuration/export` | Portable active specification |
| GET | `/configuration/schema` | Supported model help |

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
| GET | `/operator/tasks` | Operator: own assigned work only |
| POST | `/tasks/{id}/run` | Assigned operator: start prepared reserved equipment |
| POST | `/tasks/{id}/evidence` | Assigned operator: multipart image capture/upload |
| POST | `/tasks/{id}/complete` | Assigned operator: finish current manual operation subject to configured gates |
| POST | `/tasks/{id}/scrap` | Assigned operator: `{quantity,reason}` declaration |
| GET | `/reviews` | Admin: pending verification submissions |
| POST | `/reviews/{id}` | Admin: `{decision:approve|reject,reason}` |
| GET | `/machines` | Admin: configured fleet and runtime reservations |
| PATCH | `/machines/{id}` | Admin: `{status:available|down|maintenance}` |
| POST | `/gateway/test` | Admin: test the active configured endpoint |
| POST | `/machine/events` | Equipment integration: authenticated normalized event |

Assignments are automatic. There is no operator impersonation selector, task acceptance, operator-driven routing or manual handoff API in the redesigned workflow. Machine start follows preparation; task assignment never starts equipment by itself.

Orders include selected configuration, configuration revision, task states and a route `{path_id,path_name,nodes,edges}`. Nodes are real order tasks; edges use task IDs. Tasks include instructions rendered for their selected parts and assigned machine, applicable verification/scrap protocols, evidence and verification outcome. Task states include `queued`, `in_progress`, `awaiting_verification`, `awaiting_review`, `rejected`, `paused` and `completed`.

Machine callbacks require `Authorization: Bearer <MACHINE_EVENT_TOKEN>` and `{task_id,machine_id,dispatch_id,event,external_id}`. The dispatch ID distinguishes the current attempt from obsolete telemetry; external event IDs provide deduplication. See [gateway protocol](architecture.md#gateway-protocol).

## MCP

POST `/mcp` and `/api/mcp` expose the same authenticated stateless Streamable HTTP endpoint. Supported JSON-RPC methods include `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `resources/list` and `resources/read`. Configuration tools and revision rules are documented in [MCP usage](mcp.md). This interface is an administrator integration, not an independent configuration database.
