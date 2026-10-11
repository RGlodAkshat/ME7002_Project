# Smart Operator Guidance

Greenfield proof of concept for catalog-driven fan ordering, adaptive manufacturing workflows, operator guidance, and evidence-based verification. The legacy `codes/` directory is reference material only: no application code is imported or copied from it. Selected photographs may be used as demo verification references.

## What the demo proves

- A customer selects a fan colour, validates the corresponding product variant, confirms, and places an order.
- The backend snapshots the configuration, creates a dependency-aware workflow, and assigns ready tasks by skill and availability.
- Operators use a phone-friendly task queue to start work, follow instructions, submit evidence, and hand work off.
- A supervisor can change operator and machine availability, review uncertain evidence, and configure the one lab machine-gateway PC.
- Failure handling reassigns or reroutes eligible work without deleting workflow state.
- Verification and machine integration sit behind replaceable provider/adapter boundaries.

## Architecture

```text
Customer / Operator / Supervisor browser
                 │ HTTP + WebSocket
                 ▼
       React UI + same-origin proxy :8082
                 │
                 ▼
          FastAPI application :8083 ───── PostgreSQL :5432
              │          │
              │          └── OpenAI or mock verification provider
              ▼
       MachineGateway adapter ── in-process mock (default)
              │ HTTP/JSON (backend only)
              ▼
       One lab gateway PC :9002 ── physical machines/readers

Reference transport available for a later adapter: MQTT :1883 / WebSocket :9001
```

The API owns workflow state transitions. Browsers never address machines directly. The gateway URL is runtime configuration, so moving from the Compose mock to the lab gateway does not alter workflow or UI code. See [architecture](docs/architecture.md) and [API contract](docs/api-contract.md).

## Run locally

### One-command local development (no Docker)

The launcher installs the Python and Node dependencies, starts the SQLite-backed API, frontend, and mock gateway, and checks that each service is healthy:

```bash
cd smart-operator
./start-local.sh
```

Open <http://localhost:8082>. The API documentation is at <http://localhost:8083/docs>. Press `Ctrl+C` in the launcher terminal to stop every service. Logs are written under `.run/`.

To install dependencies without starting the services:

```bash
./start-local.sh --install-only
```

### Responsive UI audit

With the local services running, a repeatable Chrome audit captures every customer, operator, and supervisor screen at six laptop, tablet, and phone sizes. It also reports page overflow and interactive controls smaller than 44 px:

```bash
cd frontend
npm run audit:responsive -- local-check
```

Screenshots and `report.json` are written to `.run/responsive-audit/local-check/`. The script uses Google Chrome on macOS by default; set `CHROME_PATH=/path/to/chrome` when Chrome is installed elsewhere.

### Docker Compose

Requirements: Docker with Compose v2. No local Python, Node, PostgreSQL, or MQTT installation is needed.

```bash
cd smart-operator
cp .env.example .env
# Optionally add OPENAI_API_KEY and set VERIFICATION_PROVIDER=openai.
docker compose up --build
```

Open:

- Application: <http://localhost:8082>
- API documentation: <http://localhost:8083/docs>
- API health: <http://localhost:8083/health>
- Mock gateway health: <http://localhost:9002/health>

Useful commands:

```bash
make up
make logs
make ps
make test
make down
```

State is retained in named Docker volumes. `make down` and `make clean` do not delete it. To deliberately reset demo state, run `docker compose down --volumes` after confirming that the local demo data can be discarded.

## LAN access

All demo devices must be on the same reachable network. Find the host computer's LAN address, then open `http://<host-ip>:8082` on phones and laptops. Port `8082` must be allowed through the host firewall; allow `8083` only when API docs/direct development access is needed. The UI uses a same-origin proxy, so browser API and WebSocket traffic works without embedding the host IP.

The backend alone talks to the machine gateway. In the supervisor settings, enter the gateway PC's reachable host/IP and port; for example, `192.168.1.50` and `9002`. Do not enter individual machine addresses. `Use mock gateway` selects a deterministic in-process adapter and does not contact the stored host/port. To exercise the real HTTP boundary against the bundled gateway, turn that option off and use host `mock-devices`, port `9002`. For the lab, keep it off and enter the gateway PC address. MQTT ports `1883` and `9001` need only be opened when testing an MQTT adapter.

This is a trusted-network demo configuration. Mosquitto permits anonymous connections and HTTP is unencrypted. Do not expose these services to the public internet.

## Demo script

1. Open the customer view, choose a colour, validate the mapped product variant, confirm it, and place the order.
2. Open an operator view, mark the required operator available, accept the assigned kitting task, and follow its instructions.
3. Upload/capture a kitting photograph and submit verification. The mock provider normally approves any present image; use a filename containing `manual` or `reject` to demonstrate those deterministic branches. With OpenAI enabled, the provider decides from the submitted and reference images.
4. Use the supervisor view to emit the expected mock-machine completion event. Confirm that only the matching in-progress task advances.
5. Mark the assigned operator unavailable. Confirm that a compatible ready task is reassigned and prior workflow history remains visible.
6. Mark the assigned machine unavailable. Confirm rerouting to a compatible resource or that the task returns to `ready` when none is available.
7. Hand an assigned/in-progress assembly task to another qualified operator and show the recorded assignment change.
8. Submit an uncertain assembly photo, resolve it in manual review, and finish the order.
9. Refresh or reconnect an operator browser and confirm that the active assignment and state are restored.

## Configuration

Configuration is in `.env`; defaults are documented in [.env.example](.env.example). Important choices:

| Variable | Purpose |
| --- | --- |
| `VERIFICATION_PROVIDER` | `mock`, `openai`, or `auto` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | AI verification credentials/model; never commit the key |
| `DATABASE_URL` | Backend database connection |
| `CORS_ORIGINS` | Allowed origins for direct API development access |
| `EVIDENCE_DIR` | Evidence storage path behind the storage adapter |

The in-process mock is the simplest deterministic demo mode. The Compose HTTP mock accepts the same versioned HTTP/JSON envelope expected from the eventual lab gateway. It does not pretend to model each machine; it only acknowledges commands and exposes capabilities. Machine state and completion events are simulated through the application supervisor controls.

## Replacing mock adapters

### Machine gateway

1. Implement the versioned contract in [docs/architecture.md](docs/architecture.md#machine-gateway-contract) on the lab gateway, or add another backend `MachineGateway` implementation that translates it.
2. From the supervisor UI, clear `Use mock gateway`, set the gateway PC host/IP and port, and run the connection test.
3. Confirm the connection test succeeds before enabling real commands; validate protocol capabilities separately during adapter integration.
4. Keep stable machine IDs aligned with the product/workflow data.
5. Disable the `mock-devices` Compose service when it is no longer needed. No workflow-engine changes are required.

### Verification

Select `openai` or `mock` with `VERIFICATION_PROVIDER`. A new provider implements the existing structured decision contract (`approved`, `rejected`, or `manual_review`) and is selected at application startup. Provider results are evidence, not workflow transitions: policy in the core application decides whether a task advances.

### MQTT or database telemetry

Mosquitto is included as a reference transport. A real RFID/telemetry adapter should normalize source messages into the internal machine-event contract, assign a stable `external_id`, and submit events to the application. Repeated IDs are deduplicated; reusing an ID for different event content is rejected. Unknown broker IPs, credentials, and device endpoints remain deployment configuration rather than domain logic.

## Repository layout

```text
backend/                 API, domain workflow, adapters, persistence
frontend/                responsive React application
infra/mock-gateway/      HTTP mock for the single lab gateway PC
infra/mosquitto/         optional reference MQTT broker configuration
docs/                    architecture and API contracts
docker-compose.yml       reproducible demo stack
```

## Current assumptions

- One manufactured unit per order.
- Colour is the only configurable attribute: red maps to PR1, green to PR2, blue to PR3, and white to PR4.
- All variants share one fixed BOM and design. Colour-specific source-bin identifiers remain catalog data so real lab mappings can replace demo values without workflow changes.
- One gateway PC fronts all physical machines.
- Phones, laptops, backend host, gateway, and manufacturing devices are mutually reachable on one lab network.
- Machine addresses and protocols not present in the reference archive are represented by hot-swappable mocks.
- The demo may send uploaded photographs to OpenAI.
- Identity/roles are demo-grade rather than production authentication.
