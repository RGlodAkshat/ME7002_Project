# Manufacturing platform redesign

## Reassessment

The original implementation hardcodes one colour attribute, a five-stage workflow, startup equipment/operator fixtures and role switching without authentication. Configuration and graph constraints are absent. Operator acceptance and manual handoff expose assignment decisions; simulator controls leak into the product. Replace these boundaries as one coherent redesign.

## Implementation and verification checkpoints

1. Define a portable manufacturing specification and server-side revisioned configuration service. Ontology types and typed relationships drive catalog, BOM, paths, capabilities, guidance, verification and scrap requirements. Validate references, types, cycles, constraints and templates before applying a revision. Test round trips and conflict handling.
2. Add credential-based sessions, a first-administrator setup, administrator-managed accounts and server-side permissions. Operator identity comes from the session. Test anonymous access, role separation and cross-operator actions.
3. Execute orders from configuration snapshots and feasible DAG paths. Automatically reserve available skilled operators and compatible machines, advance only after dependency and verification gates, and reroute safely on unavailability. Test alternate products, parallel dependencies, assignments, failures and historical snapshots.
4. Build separate shop, login/admin and immersive operator entry points. Add structured administration plus contextual advanced graph editing, imports/exports, real order routes, evidence/review and configured scrap reporting. Test mobile/laptop workflows and screenshots.
5. Expose configuration tools through an authenticated MCP endpoint using the same configuration service. Keep machine simulation in a separate HTTP server; exercise commands/events through its normal protocol. Test MCP initialization/tools, machine events, duplicate callbacks and complete order execution.

## Shared contract

Base path: `/api`. All entity IDs and operational IDs are strings. Responses use JSON and errors use `{detail: string}`. Session cookie is HttpOnly, SameSite=Lax; mutating authenticated requests require `X-CSRF-Token` from login/session responses. No fixed credentials or equipment are seeded. Existing database tables/data are preserved; new platform tables are separate.

### Manufacturing specification

```json
{
  "schema_version": "1.0",
  "environment": {"id": "company", "name": "Company"},
  "ontology": {
    "entity_types": ["plant", "machine", "capability", "part", "variant", "product", "path", "stage", "guidance", "verification", "scrap"],
    "relation_types": [{"id": "variant_of", "from_types": ["variant"], "to_types": ["part"]}]
  },
  "entities": [{"id": "base-blue", "type": "variant", "name": "Blue base", "properties": {"color": "#2855c5", "bin": "B16a"}}],
  "relationships": [{"id": "base-link", "type": "variant_of", "source": "base-blue", "target": "base", "properties": {}}],
  "constraints": [],
  "gateway": {"host": "127.0.0.1", "port": 9002, "protocol": "http"}
}
```

Core relation semantics: `located_at` (equipment/product to plant), `has_capability` (machine to capability), `variant_of` (variant to part), `has_slot` (product to part; properties `slot_id`, `label`, `quantity`, `configurable`), `uses_path` (product to path; properties `conditions` mapping slot IDs to variant IDs, `priority`), `has_stage` (path to stage), `precedes` (stage to stage), `requires_capability` (stage to capability), `uses_guidance` (stage to guidance), `uses_verification` (stage to verification), `uses_scrap` (stage to scrap), `consumes` (stage to part; optional properties `slot_id`). The configured ontology must declare every relationship and its allowed endpoint types. Extra entity/relation types and properties are supported.

Stage properties: `kind` (`manual` or `machine`), `required_skills` (string array). Guidance properties: `instructions` (string array with placeholders `{product.name}`, `{parts}`, `{parts.<slot>.name}`, `{parts.<slot>.bin}`, `{machine.name}`). Verification properties: `provider` (`human` or `openai`), `instructions`, `reference_images` (configured reference asset paths), `min_confidence` (0–100). Scrap properties: `required` (boolean), `max_quantity` (nonnegative), `reasons` (string array). Variant properties include arbitrary attributes plus `bin`, `image_url`, `color`. Product properties may include `description` and `visual` (generic assembly primitive descriptors keyed by `slot_id`, with `primitive`, `position`, `rotation`, `scale`).

Constraints: `{id,name,product_id,kind,when,then,slots,property}`. `requires`: when selections match `when`, selections must match `then`. `excludes`: selections may not all match `when`. `match_property`: variants chosen in `slots` must have equal values for `property`. Empty `when` on requires applies always. Variant IDs are defined independently of combination rules.

### APIs

Auth: GET `/auth/status` → `{needs_setup}`; POST `/auth/setup` `{name,email,password}` → first admin session; POST `/auth/login` `{email,password}` → `{user,csrf_token}`; GET `/auth/me` → same; POST `/auth/logout`. User `{id,name,email,role:admin|operator,skills,available,active}`. Admin GET/POST `/users`, PATCH `/users/{id}` including password reset, availability and skills. Operator PATCH `/operator/availability` `{available}` only affects self.

Configuration: admin GET `/configuration` → `{revision,specification}` (null specification when empty); POST `/configuration/validate` `{specification}` → `{valid,errors}`; PUT `/configuration` `{specification,expected_revision}` → saved wrapper; GET `/configuration/export` → specification; GET `/configuration/schema` → schema/model help. PUT is atomic replace of configuration only, optimistic revision check. No runtime state is erased; active orders retain snapshots. Entity edits in UI/MCP read the current wrapper and apply a revised specification through this service. References from active tasks prevent removal of their machines; configuration edits cause compatible runtime reassignment. Revision conflicts return 409.

Public catalog: GET `/shop/catalog` → `{environment,products:[{id,name,description,slots:[{id,label,quantity,configurable,part_id,variants:[{id,name,properties}]}],visual}]}`; POST `/shop/validate` `{product_id,selections}` → `{valid,errors,bom,paths}`; POST `/shop/converse` `{product_id,message,selections}` → `{message,selections,requires_confirmation}` (provider optional; deterministic catalog interpretation honestly described as assistant); POST `/shop/orders` `{product_id,selections,customer_name,confirmed:true}` → order.

Admin GET `/orders`, GET `/orders/{id}` → `{id,customer_name,product_id,product_name,selections,status,configuration_revision,created_at,tasks,route}`. Route `{path_id,path_name,nodes:[task],edges:[{source,target}]}`. Task `{id,order_id,name,kind,status,dependencies:[task IDs],assigned_operator_id,machine_id,machine_name,product_name,instructions:[string],parts:[{slot_id,name,quantity,bin,image_url,color}],verification:{...}|null,scrap:{...}|null,evidence:[{id,url,name}],verification_outcome,verification_reason}`. Operational state names `queued`, `in_progress`, `awaiting_verification`, `awaiting_review`, `rejected`, `paused`, `completed`. Automatic assignment puts work directly `in_progress`, no accept/start/handoff endpoints exposed to operators.

Operator GET `/operator/tasks` → own active tasks; POST `/tasks/{id}/run` starts the assigned machine after physical preparation; POST `/tasks/{id}/evidence` multipart image; POST `/tasks/{id}/complete` → task (calls configured verification when required; otherwise completes); POST `/tasks/{id}/scrap` `{quantity,reason}` → task. Machine cycles with post-cycle gates stay assigned until those gates are satisfied, displaying configured `completion_instructions`. Admin GET `/reviews` → pending `{id,task_id,order_id,reason,evidence,...}`; POST `/reviews/{id}` `{decision:approve|reject,reason}`; admin GET `/machines` → graph machines plus runtime status/reservations; PATCH `/machines/{id}` `{status:available|down|maintenance}`; POST `/gateway/test` tests configured endpoint. POST `/machine/events` `{task_id,machine_id,event:started|completed|failed,external_id,dispatch_id}` uses `Authorization: Bearer <MACHINE_EVENT_TOKEN>` (deployment secret) and reconciles events idempotently. No simulator commands in product UI. Authenticated polling refreshes operator work.

MCP: `/mcp` supports authenticated JSON-RPC initialize, notifications/initialized, tools/list and tools/call for reading/validating/applying configuration and entity/relationship upserts. Use session+CSRF or environment-backed admin integration token. This endpoint calls the same service with expected revisions. Its stateless JSON transport follows the [MCP Streamable HTTP specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports); it does not offer an unsolicited SSE stream. Tool discovery/results follow the [MCP tools contract](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).

## Scope and operational limits

This is a functional platform foundation, not a claim of production certification: production deployment still requires TLS, appropriate network controls, backups and observed lab protocol integration. Use existing reference photographs solely as configuration data. Do not copy legacy code. Existing fan-only orders remain archived in their old tables; they cannot safely be reinterpreted as graph-driven orders.
