# Portable manufacturing specification

Schema version `1.0` uses JSON. Both prepared examples validate against the same platform service and can be imported through Configuration. Startup does not import them.

```json
{
  "schema_version": "1.0",
  "environment": {"id": "company", "name": "Company"},
  "ontology": {
    "entity_types": ["plant", "machine", "capability", "part", "variant", "product", "path", "stage", "guidance", "verification", "scrap"],
    "relation_types": []
  },
  "entities": [],
  "relationships": [],
  "constraints": [],
  "gateway": {"host": "127.0.0.1", "port": 9002, "protocol": "http"}
}
```

This is an empty structural outline. A usable environment supplies the relationship declarations and product/path records shown in the examples. The ontology must declare the platform entity types; additional types and properties may be added. Each relationship declaration supplies `id`, `from_types` and `to_types`. The validator checks every concrete relationship against those endpoint types and the supported manufacturing semantics.

Entities have `{id,type,name,properties}`. Relationships have `{id,type,source,target,properties}`. IDs are unique strings, stable across exports, and meaningful only within the specification. Machine IDs must also match the gateway integration. Runtime account IDs and order/task IDs are separate; exporting a specification does not export login credentials or operational records.

## Relationships used by the engine

| Relationship | Source → target | Relevant properties |
| --- | --- | --- |
| `located_at` | machine/product → plant | Optional environment metadata |
| `has_capability` | machine → capability | Equipment supports the capability |
| `variant_of` | variant → part | Every variant belongs to one part |
| `has_slot` | product → part | `slot_id`, `label`, positive `quantity`, `configurable` |
| `uses_path` | product → path | `priority`, optional `conditions` mapping slot IDs to variant IDs |
| `has_stage` | path → stage | Stages making up that feasible path |
| `precedes` | stage → stage | Dependency edges within the same path; cycles rejected |
| `requires_capability` | stage → capability | Machine-stage eligibility |
| `uses_guidance` | stage → guidance | Instructions for the stage |
| `uses_verification` | stage → verification | Required stage verification protocol |
| `uses_scrap` | stage → scrap | Stage material-loss declaration policy |
| `consumes` | stage → part | Optional `slot_id` restricts the stage's selected parts |

These relationships are consumed by the platform. Additional declared relationships remain portable graph data; they do not automatically introduce new execution semantics.

## Product slots and variants

A product slot describes the role of a part in an assembly, its quantity, and whether the customer chooses its variant. Variants are independent entities, not whole-product colour combinations. Arbitrary variant properties can describe colour, size, material, bin, part code or compatibility family. Common display properties are `color`, `bin` and optional part-specific `image_url`. `aliases` can contain alternate catalog phrases used by the shopping assistant, such as "blue base" or "small shelf". A fixed slot has `configurable:false` and exactly one variant.

The fan example defines separate slots for the two casing halves, handle, propeller, pins and each common gear. Pin 1 has quantity five and Pin 2 quantity one, following the supplied parts sheet. All configurable parts can be selected independently. Its standard mounting-family constraint permits the blue base and yellow propeller because their compatibility property matches. The yellow part/bin is prepared input data and should be confirmed with the lab, not inferred from the original photographs. Finished-fan photographs are verification references, not individual-part pictures.

Compatibility rules are separate from variant availability:

```json
{
  "id": "matching-panel-size",
  "name": "Side and shelf dimensions agree",
  "product_id": "product",
  "kind": "match_property",
  "slots": ["sides", "shelves"],
  "property": "size"
}
```

Supported kinds are `match_property` (equal selected properties across named slots), `requires` (when selected variants match `when`, require selections in `then`), and `excludes` (reject combinations matching all entries in `when`). Both `when` and `then` map slot IDs to variant IDs. An empty `when` on a requirement applies unconditionally. New compatible variants are configuration changes; the application does not enumerate every possible combination.

Products may include `description` and `visual` descriptors. `visual` is a list of generic primitives with `slot_id`, `primitive`, `position`, `rotation` (radians) and `scale`, each vector containing three numbers. Supported primitive names are `box`, `sphere`, `cylinder`, `cone` and `torus`. Multiple primitives can share one slot to represent a compound part, and its selected variant supplies colour. This provides an interactive illustrative preview, not CAD-level geometry or dimensional verification.

## Processes, guidance and gates

Stage properties include `kind:manual|machine` and `required_skills` (strings). A machine stage must require at least one configured capability. Skill names are configuration values; administrators give matching skills to operator accounts. Dependency-ready work is assigned automatically. Machine preparation instructions are shown before the operator explicitly starts equipment.

Guidance `instructions` are arrays of reusable templates. Supported placeholders are:

```text
{product.name}  {parts}  {machine.name}
{parts.<slot>.name}  {parts.<slot>.bin}
{parts.<slot>.quantity}  {parts.<slot>.color}
```

The engine resolves them from the selected order parts and assigned resource. The aggregate `{parts}` identifies selected components and quantities. Unsupported placeholders are rejected on configuration import rather than failing during an operator's physical work.

An optional `part_instructions` array expands its templates once for each selected part consumed at the stage, before the ordinary instructions. It supports `{part.name}`, `{part.quantity}`, `{part.bin}`, `{part.slot_id}` and `{part.color}`. For example, `"Collect {part.quantity} × {part.name} from bin {part.bin}."` gives the operator one focused collection step per component, rather than placing the entire bill of materials inside one instruction. The fan kitting guidance uses this mechanism, including the configured quantity of five for Pin 1.

For a machine stage, optional `completion_instructions` supply instructions shown after the gateway confirms the cycle completed. This separates loading/preparation from safe unloading, inspection and required scrap declarations. It uses the same ordinary guidance placeholders. The fan preparation guidance therefore shows guard/loading instructions before Start equipment and unloading/material-loss instructions after completion, without product-specific behavior in the application.

Verification properties include `provider:human|openai`, `instructions` (a string or list of strings), `reference_images` (relative asset filenames) and `min_confidence` (0–100). A stage has verification only if it has `uses_verification`. The human provider always requires a review; AI uncertainty, missing credentials or service failure also requires review. Stage configuration never permits evidence presence alone to bypass required approval.

Reference assets resolve under the server's `REFERENCE_IMAGE_DIR`. Use `blue.jpg` in `reference_images`, and `/api/shop/reference/blue.jpg` for a public part display image URL. Exports retain asset references but do not embed the image bytes; transfer the associated reference files when moving the environment to another server. File/path traversal is rejected by the asset handler.

Scrap properties are `required` (boolean), `max_quantity` (nonnegative integer) and `reasons` (string array). When required, a declaration must be recorded before completion, including a zero quantity when no loss occurred. This records stage loss; it does not implement a stock ledger, procurement or a complete material-accounting system.

## Update, export and recovery

GET `/api/configuration` returns `{revision,specification}`. Applying a complete specification requires its `expected_revision`; a concurrent edit returns 409. Validation happens before application, and invalid graphs do not replace the active revision. Administrative forms, advanced JSON/graph edits and MCP invoke the same operation.

The export is the current specification, including saved administrative changes. It does not include runtime assignments, account passwords, verification evidence or reviews. Re-importing updates the active manufacturing definition atomically and leaves that operational state intact. Active orders keep their order-time specification snapshots, and reserved unfinished equipment cannot be removed. Import a different company's environment after active work no longer reserves machines that the new configuration omits.
