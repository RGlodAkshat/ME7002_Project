# Smart Manufacturing Lab demonstration

The laboratory environment is imported data, not hardcoded platform behavior. [lab-smart-factory.json](../configs/examples/lab-smart-factory.json) is derived from `smart_factory_v2_modular_3_final_updated.ttl`. Its source ontology, individual entity identifiers and relationships are retained as reference graph data alongside executable product, process and resource definitions. The Turtle file is authoritative for product IDs and routing; supplied photographs inform guidance text only. Program identifiers in the executable data are not silently replaced by conflicting photographed labels. A responsible lab operator must verify the actual machine program and approved procedure before physical work.

The current demo uses red PR1, blue PR2, green PR3 and white PR4. Red/green use MC1 then MC2; blue/white use MC3 then MC4, followed by the configured pressing/assembly stages. The eight-stage routes end at WS9 (final assembly); WS8 quality-check is disabled and MC10 is not on these routes. Customer login is not required. The earlier independent-colour fan example remains a separate example, not an automatic extension of this lab ontology.

The **Ontology view** is the reusable manufacturing model: schema/type declarations, configured equipment inventory, all offered products/part variants, compatibility rules and feasible process paths. A particular order instantiates a **knowledge graph** from that model's selected product, bill of materials and route; live operations, machine/operator assignments and evidence are added as runtime facts. Type/schema nodes remain distinguishable from concrete entity nodes within the same canvas. Original RDF triples are retained as source provenance, not silently rewritten when an administrator edits the executable projection. Exports contain both source provenance and the current edited manufacturing model. This is a supported semantic projection, not a general OWL inference engine.

All template entities, constraints and type definitions are presented in one large editable ontology canvas. Zoom, pan and locate a selected definition to inspect the model; a focused-context option changes the same canvas rather than creating separate ontology diagrams. Order knowledge graphs remain separate order-specific views.

| Product | Configured eight-stage route |
| --- | --- |
| PR1 · red | WS1 → MC1 → MC2 → WS4 → MC5 → MC6 → MC8 → WS9 |
| PR2 · blue | WS1 → MC3 → MC4 → WS4 → MC5 → MC6 → MC9 → WS9 |
| PR3 · green | WS1 → MC1 → MC2 → WS4 → MC5 → MC7 → MC8 → WS9 |
| PR4 · white | WS1 → MC3 → MC4 → WS4 → MC5 → MC7 → MC9 → WS9 |

These are the source-defined paths, not interchangeable CNC assumptions. Unavailability pauses work when no compatible alternative has been configured; the engine does not invent a physically invalid substitute.

## One-command local demonstration

From the project directory:

```bash
./start-demo.sh
```

This installs ordinary application dependencies and, when PostgreSQL is not installed, downloads a pinned PostgreSQL binary distribution into ignored `.run/demo/runtime`. The downloaded wheel's SHA-256 is checked against its official PyPI metadata. The PostgreSQL executables run directly; Docker, Homebrew and a matching Python wheel ABI are not needed. Supported bundled targets are macOS Apple Silicon, macOS Intel and Linux x86-64; on another system install PostgreSQL and set `POSTGRES_BIN` to the directory containing `initdb` and `pg_ctl`.

The launcher creates a **separate durable demo environment** under `.run/demo`: an operational SQLite database, a real PostgreSQL `smart_database`, individual admin/operator accounts with graph-issued qualifications, and private generated database credentials. It imports the lab configuration once through the ordinary authenticated configuration API. Subsequent launches preserve configuration edits, orders and accounts. Nothing replaces the usual `backend/manufacturing_platform.db`, and the application itself does not seed data on startup.

The independent CNC/conveyor simulator publishers insert real lab-shaped rows into PostgreSQL. They discover explicitly started observation windows through ordinary authenticated read-only API requests, then emit the configured program sequence or conveyor signal edge. They do not mark tasks complete, call core callbacks, supply evidence or approve reviews. The same production telemetry reader consumes these rows. Human kitting/assembly actions, photos, scrap declarations and administrator approvals remain necessary. This local simulator demonstration does not require starting physical equipment; follow the on-screen preparation and monitoring controls to exercise simulated cycles.

Open the launcher’s printed website URL. Default website/API ports are 8082/8083; occupied ports are skipped without stopping existing applications. The launcher also prints the host’s LAN URL for phones and other PCs. The customer store is `/#/shop` and requires no login. Credentials for `admin@sml.local` and the eight qualified workers are in **`.run/demo/credentials.json`**, owner-readable only; open that file locally in your editor. Passwords are unique and generated, not printed to logs or committed. PostgreSQL listens on localhost only; other devices need website access, not database access. Wireless client isolation or the host firewall may still prevent LAN access.

For an independent test environment or explicit ports:

```bash
./start-demo.sh --directory .run/my-demo --website-port 8282 --api-port 8283 --postgres-port 55432
```

`DEMO_STATE_DIR`, `FRONTEND_PORT` and `API_PORT` also select those defaults. Keep demo directories under `.run`. Press `Ctrl+C` to stop this launcher’s website, API, publishers and PostgreSQL; data is retained for the next launch. Private logs and selected addresses are in the same demo directory. The demo never changes the real lab publishers or their database IP; commissioning that integration remains a separate step below.

For developer verification only, launch a separate `.run/demo-smoke` environment and run `backend/.venv/bin/python infra/demo-smoke-test.py --api http://127.0.0.1:<printed-website-port> --directory .run/demo-smoke`. This check creates orders, authenticates the provisioned qualified workers, waits for actual PostgreSQL rules, approves clearly synthetic test photographs and exercises pending/running cancellation. It writes an ignored `smoke-report.json`. Do not run it against a live demonstration or lab installation; its automated test approvals are not manufacturing verification.

## Prepare accounts for the ordinary laboratory installation

From the project directory:

```bash
./start-local.sh --install-only
backend/.venv/bin/python infra/provision-lab-accounts.py
./start-local.sh
```

The provisioning command is explicitly opt-in. It creates `admin@sml.local` plus an operator for each distinct stage qualification/skill requirement group in the lab configuration. Each receives a unique generated password; credentials are saved to ignored `.run/lab-accounts.json` with owner-only permissions. Qualifications are administrator-issued operational facts granting the ontology-defined process skills, not free-typed labels. View that file locally in your editor; do not upload or commit it. Re-running preserves existing users, their credentials and their qualifications. Use `--sync-qualifications` only when explicitly issuing the configured qualification facts to matching previously generated operator accounts. No customer accounts are created. Provisioning does not import configuration, replace orders or seed application data. If using a nondefault operational database, supply the same `--database-url` used by the backend.

For additional operators, use **Accounts** in the admin dashboard and select compatible process-derived qualifications. A skill checkbox alone cannot satisfy a stage that also requires an issued qualification. Roles, qualifications, grants and process requirements can be configured in the ontology; credential records remain separate. Set availability for the people actually demonstrating the process. Accounts and passwords are not part of configuration exports.

## Database-only machine integration

The platform does not connect directly to CNC, PLC, RFID or their WebSocket feeds. Existing lab publishers continue collecting machine data and write into a PostgreSQL database named `smart_database`. Their database connection settings are redirected to the agreed intake host. The platform reads that database; its operational database and credential tables remain separate.

The supplied `db_manager.py` inserts CNC data into quoted tables `telemetry_MC1` through `telemetry_MC4`. MC2 has no `y_pos`; the other three insert it. The conveyor `smc_db.py` inserts into quoted `telemetry_MC5` through `telemetry_MC10`, using the case-sensitive `"Timestamp"` field and exact PLC signal column names. Its implementation silently omits signals absent from the table, so an incomplete schema can appear connected while losing useful data.

[telemetry-schema.sql](../infra/telemetry-schema.sql) provides compatible tables for a **fresh** intake database. It preserves existing tables rather than migrating them and requires no TimescaleDB extension. It adds `platform_ingest_id` for monotonic polling; existing tables without it use a timestamp watermark and cannot reliably distinguish same-timestamp late inserts. Have the database administrator inspect an existing deployment before applying schema changes.

```bash
# Use PostgreSQL's password prompt or local credentials store; never inline passwords.
psql -h <intake-host> -p 5432 -U <database-owner> -d smart_database -W -f infra/telemetry-schema.sql
```

Store the platform's read connection in ignored `backend/.env`:

```dotenv
TELEMETRY_DATABASE_URL=postgresql+psycopg://<reader>:<URL-encoded-password>@<intake-host>:5432/smart_database
TELEMETRY_TIMEZONE=Asia/Kolkata
```

Use separate least-privilege accounts: publishers need INSERT and SELECT on their intake tables (the conveyor publisher inspects available columns) and sequence USAGE for new schema IDs; the platform reader needs SELECT only. Keep credentials out of the portable configuration and source control. Restart the backend after changing environment settings.

The historical database address in the archive is `192.168.0.109:5432`. The photographs show PCs at `192.168.0.105` and `192.168.0.196`; they do not establish which PC hosts the database or whether addresses are still current. Verify the agreed host locally. The lab SSID is `SM Lab 2.4Ghz`; its password stays outside this repository. Allow the database port only from the lab publishers and backend. Phones need website access at `http://<website-host>:8082`, not direct database access. Shared Wi-Fi alone does not prove reachability.

The existing loggers supply no trustworthy order ID, dispatch ID or explicit five-gear completion signal. Status `Online`, idle spindle, motion stopping or a green tower **must not automatically complete an order stage**. The lab template therefore uses operator-confirmed completion with configured photo review. Only an explicitly configured and validated cycle rule may infer process completion from future signal data. Live database readings provide context and fault/availability evidence, not invented manufacturing proof. MC10 may be collected by the publisher but is not automatically made an executable resource when absent from the active ontology.

## Administrator workflow

1. Open the launcher’s website URL and sign in using the local administrator credentials. With `start-demo.sh`, the lab specification is already imported. For the ordinary installation, import `configs/examples/lab-smart-factory.json` in **Configuration**.
2. Review the imported products, process stages, machine capabilities, verification policies and instructions. Use the graph interface to inspect ontology definitions, entity connections and typed relationships; save validated changes as a new revision. Export the specification for a portable backup.
3. In **Accounts**, choose process-derived qualifications for each worker and mark demonstrators available. Keep other worker accounts unavailable when they should not receive jobs. The demo preassigns one qualified person per workstation requirement so its eight-step workflow is ready to execute.
4. Check telemetry integration status after the publishers have been redirected. Verify fresh timestamps and correct machine IDs; a successful DB connection alone is not proof that publishers are writing.
5. Watch **Orders** and its order-specific graph as an order is created, work is assigned, stages finish and eligible resources change. Each order retains its configuration revision; changing the global ontology does not rewrite completed work.
6. Review submitted evidence. Approve correct, complete work; reject with a clear reason when correction is needed. Approval and required scrap declarations gate progression. To demonstrate rerouting safely, mark an unused/idle compatible resource unavailable; do not claim stopped physical equipment solely because a dashboard toggle changed.

To withdraw a pending order, open its order details and select **Cancel order**. Enter a reason, acknowledge that cancellation does not stop physical equipment, then confirm. The cancelled order remains visible with its completed work and evidence; completed orders cannot be cancelled. If an observed operation has already started, cancellation instead pauses it and retains the operator/equipment reservation. Follow the approved physical safe-stop procedure, then use the administrator's **Release paused resources** confirmation only after the equipment has actually stopped. An idle/online reading is not a stop acknowledgement. Cancellation prevents further starts or submissions; workers see a cancellation warning rather than a new instruction.

## Customer workflow

1. Open `http://<website-host>:8082/#/shop` without logging in.
2. Choose a configured lab product and its permitted parts. The catalog interpreter can help propose a supported configuration; it does not invent unavailable parts or instructions.
3. Review the product, selected parts and bill of materials, enter a customer name and explicitly confirm the order.
4. Give the resulting order identifier to the administrator. The executable order graph is generated from the confirmed configuration rather than a manually picked operator route.

## Operator workflow

1. Sign in on a phone or laptop with an individual worker account. Compatible work is assigned automatically according to skill requirements, dependencies and availability.
   For close-up guidance, select **Focus view** to hide account controls and emphasize the current instruction and part reference. Rotate the phone to landscape when useful; orientation lock is not required. **Exit focus view** or Escape returns to the normal view. Browser-level fullscreen is optional/best effort, so devices that do not support it retain the in-app focus layout.
2. Follow the displayed instruction and configured part/bin guidance. At kitting, collect the specified quantities and keep finished and unprocessed parts separate. Photograph the kit when requested and wait for the required review.
3. At the assigned CNC stage, complete the preparation instructions and select **Begin monitored operation** to open the current observation window before the process begins. In the local demo, the independent publisher now simulates the configured cycle. In the real lab, verify the trolley/RFID permissive indication and correct approved program using the provided guidance; the physical operator operates the machine controls, including **CYCLE START**. The platform does not remotely energize the CNC. Follow the machine's approved safety procedure; never bypass a red indication or guard.
4. Process the configured parts, return them to the finished tray area and inspect the result. Submit the configured photo evidence and operator completion confirmation; do not treat a raw telemetry `Online` status as completion.
5. Follow subsequent pressing/assembly and final-assembly guidance as jobs become eligible. Declare scrap when configured, including zero when none occurred, and correct rejected submissions with fresh evidence.
6. Completed work releases the next dependencies automatically. Another compatible operator receives the next job when appropriate; workers do not manually choose routes or identities.

This is a demonstration workflow, not authorization for industrial machine commissioning. Validate real telemetry semantics, program names, permissions, physical safety and network connectivity with lab staff before operating equipment.
