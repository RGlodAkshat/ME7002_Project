# ForgeGuide manufacturing platform

A configuration-driven manufacturing platform with separate customer shopping, administrator management and authenticated operator guidance. Products, part variants, equipment, feasible paths, guidance, verification and scrap policy come from one server-managed ontology and knowledge graph. The laboratory fan is a prepared configuration, not built-in application behavior. Legacy `codes/` sources are reference material only; selected photographs are reference assets.

## Run locally

For a ready-to-use lab demo with imported ontology, individual qualified worker logins and independent publishers writing to a real local PostgreSQL intake, run `./start-demo.sh`. Credentials are stored privately in `.run/demo/credentials.json`; the launcher prints laptop/phone URLs and preserves the ordinary installation. See [demo setup and role workflows](docs/lab-demo.md). No Docker or customer login is required.

Install Python 3.12+ and Node.js 20+, then:

```bash
cd smart-operator
./start-local.sh
```

The launcher installs dependencies and starts the website on **8082**, API on **8083**, and a separate machine gateway simulator on **9002**. It generates persistent machine-event and MCP integration secrets in ignored `backend/.env`, preserving existing nonempty settings. There are no default account credentials. Press `Ctrl+C` to stop the services; logs are in `.run/`.

Open <http://localhost:8082> and create the first administrator. After initial setup, this address is the central login. Operators go directly to their own guidance screen after login. The public store is a separate entry point at <http://localhost:8082/#/shop>. API documentation is at <http://localhost:8083/docs>.

The local database is `backend/manufacturing_platform.db`. The previous `backend/smart_operator.db` is preserved and is not used by the redesigned platform. Existing fan-only orders cannot safely be interpreted as graph-driven orders. To use a separate development database, set `DATABASE_URL` before launching; for example, `DATABASE_URL=sqlite:///../.run/qa.db ./start-local.sh`. To install dependencies only, run `./start-local.sh --install-only`.

## Configure and operate an environment

For the current laboratory demonstration, use [lab-smart-factory.json](configs/examples/lab-smart-factory.json), derived from the supplied Turtle ontology. Follow [lab setup and role-by-role demonstration](docs/lab-demo.md) for opt-in account provisioning, database-only telemetry intake, ontology/order graphs and physical operator guidance. Customers still use the public store without login. The source photographs inform guidance, not executable routing or program selection.

1. Sign in as the administrator and import a specification through Configuration. Prepared examples are [lab-smart-factory.json](configs/examples/lab-smart-factory.json), the earlier independent-part [lab-fan.json](configs/examples/lab-fan.json), and unrelated [storage-workshop.json](configs/examples/storage-workshop.json). Import uses the ordinary validated configuration service; nothing is automatically loaded on startup.
2. Review and edit products, part variants, machine capabilities, routes, instructions, verification and scrap requirements. Structured controls and advanced graph editing update the same active server-side revision. Export the current specification for backup or transfer. Re-importing requires the current revision and leaves operational history intact.
3. Create operator accounts with individual credentials and availability, selecting compatible skills from the configured process requirements rather than typing arbitrary labels. These skills can be distributed across people. For opt-in generated lab accounts run `backend/.venv/bin/python infra/provision-lab-accounts.py`; passwords are saved only in ignored `.run/lab-accounts.json`, and existing users are preserved. Accounts are operational access settings and are not included in portable manufacturing exports.
4. For the current lab configuration, set the central database reader in ignored `backend/.env` and check **Operations → Central process data**. Publishers write `smart_database`; phones never contact industrial devices or the database. For gateway-based examples only, review the gateway host/IP and port and test its connection (`127.0.0.1:9002` locally; `gateway:9002` in Compose).
5. Open the separate store, choose a product and compatible parts, review the selection, and confirm the order. A blue base with a yellow propeller is valid in the fan example. The storage example demonstrates a different product and matching-size constraints without source-code changes. Its 3D preview is assembled from configured generic primitives and selected variant colours.
6. Operators sign in on their own devices. Eligible work is assigned automatically; no identity selector, task acceptance, routing selection or manual handoff is required. Follow the current instruction. Lab stages separate preparation from physical work: select **Begin monitored operation** before the first physical cycle, then use approved machine controls. This never sends a machine command. Other gateway-based configurations retain **Start equipment**. Machine assignment never starts equipment by itself.
7. At stages requiring verification, capture/upload evidence and submit the work. The examples use human verification, so the administrator reviews and approves or rejects evidence. Rejection permits corrected evidence and resubmission. OpenAI verification is an optional per-stage protocol when a key is configured; missing service access falls back to review rather than approving unexamined evidence. Record scrap declarations when configured, including a zero quantity when nothing was scrapped.
8. Inspect the actual order route from the administrative order view. Operator or equipment unavailability triggers compatible reassignment while preserving completed work and evidence. Route visibility belongs to operations; guidance shows operators their next physical action.

The examples contain assumed process capabilities and a prepared yellow-propeller bin `Y-PROP`; validate these against the lab before issuing physical work. Red/green/blue/white part codes and bin identifiers are transcribed from the supplied photograph. Reference photos show assembled products, so they are orientation examples rather than proof that every mixed-colour order is correct.

## Configuration and integrations

See [configuration specification](docs/configuration.md), [architecture](docs/architecture.md) and [HTTP API contract](docs/api-contract.md). The platform starts with an empty manufacturing environment. Each imported specification declares its ontology entity types and relationship endpoint types, then supplies entities, relationships and compatibility rules. The engine uses these records for the catalog, bills of materials, feasible paths, dependency graphs, resource requirements and guidance templates.

Configuration edits use optimistic revision checks. Imports replace configuration atomically, not application data. Active orders retain their original configuration snapshot; removing equipment reserved by unfinished work is rejected. Editing a configuration does not remove users, evidence or historical orders.

The original gateway integration uses HTTP through the configured endpoint. The standalone simulator receives those commands and sends authenticated machine callbacks; fault injection is available only on its infrastructure API. See [gateway simulator](infra/machine-simulator/README.md). This remains available for gateway-based examples, but the current laboratory integration is **database-only**: existing publishers write compatible PostgreSQL `smart_database` tables and the platform reads them through `TELEMETRY_DATABASE_URL`. It does not connect directly to CNC/PLC/WebSocket feeds. See [intake schema](infra/telemetry-schema.sql) and [lab integration guide](docs/lab-demo.md). Raw availability readings are not proof of order completion; the lab configuration requires operator evidence/review unless a validated completion rule is explicitly configured.

Human verification needs no external key. To enable image AI, set `OPENAI_API_KEY` and `OPENAI_MODEL` in `backend/.env` and choose `openai` for the relevant verification entity. Do not commit credentials. Protocol reference images use filenames relative to `backend/data/reference_images`; display image URLs can use `/api/shop/reference/<filename>`.

MCP configuration editing is available at <http://localhost:8083/mcp> and through the same-origin alias <http://localhost:8082/api/mcp>. Authenticate an integration with the generated `ADMIN_INTEGRATION_TOKEN`, or an administrator browser session and CSRF token. Tools read, validate and apply specifications, and upsert/delete graph entities and relationships through the same validated configuration service. See [MCP usage](docs/mcp.md).

## LAN and deployment

Phones and laptops open `http://<website-host-ip>:8082`; the browser uses the same-origin API proxy. For the lab integration, only publishers and the backend need PostgreSQL reachability. For gateway-based configurations, the backend reaches the gateway PC, and that PC must be able to call the backend machine-event endpoint. Set `MACHINE_CALLBACK_URL` to an address reachable **from the gateway** when deploying remotely. Both endpoints must share `MACHINE_EVENT_TOKEN`. Configure the simulator's `PLATFORM_CALLBACK_URL` to the same URL when using it separately. The laptop launcher sets a localhost callback for the bundled local simulator.

Allow inbound TCP 8082 on the website host and the necessary backend callback port; wireless client isolation must permit this connectivity. A shared SSID alone does not guarantee peer access. For externally hosted deployment use TLS, secure cookies, persistent backups and suitable network access controls. The local launcher uses HTTP and is a development setup.

Docker Compose is optional:

```bash
cd smart-operator
make setup
docker compose up --build
```

`make setup` creates ignored `.env` and random deployment secrets. PostgreSQL and evidence use new `platform-*` volumes; old deployment volumes are left intact. After importing, set the gateway host to `gateway` in Configuration. `make down` stops containers and retains data. Docker/Compose itself must already be installed. A fresh PostgreSQL initialization uses the generated password; changing it later also requires updating the database account.

## Verification and repository layout

```bash
cd backend
./.venv/bin/pytest
cd ../frontend
npm run build
cd ..
python3 -m unittest discover -s infra -p test_infrastructure.py -v
```

The infrastructure checks exercise real HTTP commands, duplicate command handling, authenticated commands/callbacks, acknowledged stops, failure injection and persistent secret generation. Browser screenshots and responsive checks are development artifacts in `.run/`; the browser audit requires Google Chrome or `CHROME_PATH` pointing to another Chrome installation.

With services running, capture responsive screenshots using `cd frontend` followed by `npm run audit:responsive -- local-check`. The audit covers login and the separate public store. Set `QA_ADMIN_EMAIL`, `QA_ADMIN_PASSWORD`, `QA_OPERATOR_EMAIL` and `QA_OPERATOR_PASSWORD` in the audit process environment to include authenticated admin and operator screens. It does not seed users or orders; use an isolated QA environment with prepared accounts and work. Without those credentials, protected screens are reported as skipped. Screenshots and the report are written to `.run/responsive-audit/local-check/`.

For the complete browser workflow, start the stack with a **fresh isolated database** through `DATABASE_URL`, then run `node scripts/platform-e2e.mjs` from `frontend/`. This test creates accounts through login/admin screens, completes a gateway-based mixed-part order, then imports the actual Turtle source, edits its ontology through the graph, assigns process qualifications, and completes an eight-stage lab order through observed-operation guidance and specialist approvals. It checks edit/export/reimport behavior and captures phone, tablet and laptop screens under `.run/platform-e2e/`. It requires an empty installation and must not be run against an existing working environment. Optional `FRONTEND_PORT`, `API_PORT` and `GATEWAY_PORT` let the launcher run an isolated QA stack alongside an existing app; set matching `APP_URL` and `QA_GATEWAY_PORT` for the browser test.

```text
backend/                  authenticated API, configuration graph, execution, MCP, providers
frontend/                 separate store, administration and immersive guidance
configs/examples/         portable manufacturing input data; never auto-loaded
infra/machine-simulator/  independent HTTP equipment simulator
infra/prepare-secrets.py  persistent ignored deployment secrets
docs/                     model, API and integration contracts
```

This is a working platform foundation. It does not establish industrial safety certification, a complete inventory/MES implementation, or compatibility with a lab protocol that has not yet been observed. One order currently represents one manufactured unit. The simulator keeps command history in memory; real gateway recovery and physical-machine commissioning require durable command reconciliation and equipment-specific validation.
