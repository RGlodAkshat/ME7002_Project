#!/usr/bin/env python3
"""Owned local demo stack, real PostgreSQL intake and independent publishers."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import quote
import zipfile

import httpx
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "backend/.venv/bin/python"
STOP = False


def shutdown(*_):
    global STOP
    STOP = True


def private_json(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def free_port(preferred, excluded=()):
    for port in range(preferred, min(preferred + 100, 65536)):
        if port in excluded:
            continue
        with socket.socket() as sock:
            try:
                sock.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No unused port available in the requested range")


def postgres_binaries(directory):
    candidates = [Path(os.environ["POSTGRES_BIN"])] if os.environ.get("POSTGRES_BIN") else []
    bundled = directory / "runtime/pgserver/pginstall/bin"
    if (directory / "postgres/PG_VERSION").exists():
        candidates.append(bundled)  # Preserve the runtime version used by this cluster.
    if shutil.which("initdb"):
        candidates.append(Path(shutil.which("initdb")).parent)
    for base in (Path("/opt/homebrew/opt"), Path("/usr/local/opt")):
        candidates.extend(base.glob("postgresql*/bin"))
    candidates.append(bundled)
    for candidate in candidates:
        if all((candidate / executable).is_file() for executable in ("initdb", "pg_ctl")):
            return candidate
    machine = platform.machine().lower()
    targets = {("Darwin", "arm64"): "macosx_11_0_arm64", ("Darwin", "x86_64"): "macosx_11_0_x86_64",
               ("Linux", "x86_64"): "manylinux_2_17_x86_64"}
    target = targets.get((platform.system(), machine))
    if not target:
        raise RuntimeError("Install PostgreSQL and set POSTGRES_BIN to its bin directory for this platform")
    wheels = directory / "runtime/wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    print("Installing isolated PostgreSQL binaries (pgserver 0.1.4); no Docker or system service required.", flush=True)
    subprocess.run([str(PYTHON), "-m", "pip", "download", "--disable-pip-version-check", "--no-deps", "--only-binary=:all:",
                    "--python-version", "312", "--implementation", "cp", "--abi", "cp312", "--platform", target,
                    "pgserver==0.1.4", "-d", str(wheels)], check=True)
    wheel = next(wheels.glob("pgserver-0.1.4-*.whl"))
    metadata = httpx.get("https://pypi.org/pypi/pgserver/0.1.4/json", timeout=30)
    metadata.raise_for_status()
    published = next(item for item in metadata.json()["urls"] if item["filename"] == wheel.name)
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != published["digests"]["sha256"]:
        raise RuntimeError("The PostgreSQL runtime wheel does not match its official PyPI SHA-256")
    runtime = directory / "runtime"
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            if not member.filename.startswith("pgserver/"):
                continue
            destination = (runtime / member.filename).resolve()
            if not destination.is_relative_to(runtime.resolve()):
                raise RuntimeError("Invalid PostgreSQL runtime archive entry")
            archive.extract(member, runtime)
            if not member.is_dir():
                destination.chmod((member.external_attr >> 16) & 0o777 or 0o644)
    return bundled


def bootstrap_database(directory, binaries, private, port):
    cluster = directory / "postgres"
    password_file = directory / "postgres-owner-password"
    descriptor = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(private["owner_password"] + "\n")
    if not (cluster / "PG_VERSION").exists():
        subprocess.run([str(binaries / "initdb"), "-D", str(cluster), "-U", "demo_owner", "-A", "scram-sha-256",
                        "--pwfile", str(password_file), "--encoding=UTF8", "--locale=C"], check=True,
                       stdout=subprocess.DEVNULL)
    subprocess.run([str(binaries / "pg_ctl"), "-D", str(cluster), "-l", str(directory / "postgres.log"),
                    "-o", f"-h 127.0.0.1 -p {port} -c unix_socket_directories=", "-w", "start"], check=True,
                   stdout=subprocess.DEVNULL)
    owner = f"postgresql://demo_owner:{quote(private['owner_password'])}@127.0.0.1:{port}/postgres"
    with psycopg.connect(owner, autocommit=True) as connection:
        if not connection.execute("SELECT 1 FROM pg_database WHERE datname = 'smart_database'").fetchone():
            connection.execute('CREATE DATABASE "smart_database"')
        for role, key in (("demo_writer", "writer_password"), ("demo_reader", "reader_password")):
            if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                connection.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(private[key])))
    with psycopg.connect(owner.replace("/postgres", "/smart_database"), autocommit=True) as connection:
        connection.execute((ROOT / "infra/telemetry-schema.sql").read_text(), prepare=False)
        connection.execute("GRANT CONNECT ON DATABASE smart_database TO demo_reader, demo_writer")
        connection.execute("GRANT USAGE ON SCHEMA public TO demo_reader, demo_writer")
        connection.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO demo_reader")
        connection.execute("GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO demo_writer")
        connection.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO demo_writer")
    private["writer_url"] = f"postgresql://demo_writer:{quote(private['writer_password'])}@127.0.0.1:{port}/smart_database"
    private["reader_url"] = f"postgresql+psycopg://demo_reader:{quote(private['reader_password'])}@127.0.0.1:{port}/smart_database"
    private_json(directory / "private.json", private)


def wait_ready(url, processes):
    for _ in range(90):
        if STOP or any(process.poll() is not None for process in processes):
            raise RuntimeError("A demo service stopped during startup; check the private demo logs")
        try:
            if httpx.get(url, timeout=1).is_success:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError("A demo service did not become ready; check the private demo logs")


def import_configuration(api, credentials, specification):
    administrator = next(account for account in json.loads(credentials.read_text())["accounts"]
                         if account.get("role") == "admin" and account.get("password"))
    with httpx.Client(base_url=api, timeout=30) as client:
        response = client.post("/api/auth/login", json={key: administrator[key] for key in ("email", "password")})
        response.raise_for_status()
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        response = client.get("/api/configuration")
        response.raise_for_status()
        current = response.json()
        if current["specification"] is None:
            response = client.put("/api/configuration", json={"expected_revision": current["revision"], "specification": specification})
            response.raise_for_status()
            print("Imported the laboratory configuration through the ordinary validated API.", flush=True)
        else:
            print("Preserved the existing demo configuration, users and orders.", flush=True)


def lan_addresses():
    values = set()
    if platform.system() == "Darwin":
        for interface in ("en0", "en1"):
            result = subprocess.run(["ipconfig", "getifaddr", interface], capture_output=True, text=True)
            if result.returncode == 0:
                values.add(result.stdout.strip())
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.168.0.1", 1))  # Route lookup only; no packet is sent.
            values.add(sock.getsockname()[0])
    except OSError:
        pass
    return sorted(value for value in values if value and value != "127.0.0.1")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(os.environ.get("DEMO_STATE_DIR", ROOT / ".run/demo")))
    parser.add_argument("--website-port", type=int, default=int(os.environ.get("FRONTEND_PORT", "8082")))
    parser.add_argument("--api-port", type=int, default=int(os.environ.get("API_PORT", "8083")))
    parser.add_argument("--postgres-port", type=int, default=15432)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_relative_to(ROOT / ".run"):
        parser.error("Demo data must be under the ignored project .run directory")
    if any(port < 1024 or port > 65400 for port in (args.website_port, args.api_port, args.postgres_port)):
        parser.error("Ports must be between 1024 and 65400")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "launcher.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("This demo directory is already running; use its website or a separate --directory")
        private_file = directory / "private.json"
        private = json.loads(private_file.read_text()) if private_file.exists() else {
            key: secrets.token_urlsafe(24) for key in ("owner_password", "writer_password", "reader_password")}
        private_json(private_file, private)
        binaries = postgres_binaries(directory)
        website = free_port(args.website_port)
        api = free_port(args.api_port, (website,))
        postgres_port = free_port(args.postgres_port, (website, api))
        processes, logs = [], []
        database_started = False
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        def start(name, command, cwd, environment):
            logfile = (directory / f"{name}.log").open("a")
            logs.append(logfile)
            process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=logfile, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            processes.append(process)
            return process

        try:
            database_started = True
            bootstrap_database(directory, binaries, private, postgres_port)
            operational_url = f"sqlite:///{directory / 'platform.db'}"
            credentials = directory / "credentials.json"
            subprocess.run([str(PYTHON), str(ROOT / "infra/provision-lab-accounts.py"), "--database-url", operational_url,
                            "--credentials", str(credentials)], cwd=ROOT, check=True)
            environment = {**os.environ, "DATABASE_URL": operational_url, "EVIDENCE_DIR": str(directory / "evidence"),
                           "TELEMETRY_DATABASE_URL": private["reader_url"], "TELEMETRY_TIMEZONE": "Asia/Kolkata",
                           "SESSION_SECURE": "false",
                           "CORS_ORIGINS": f"http://localhost:{website},http://127.0.0.1:{website}"}
            start("backend", [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(api)], ROOT / "backend", environment)
            api_url = f"http://127.0.0.1:{api}"
            wait_ready(api_url + "/health", processes)
            import_configuration(api_url, credentials, json.loads((ROOT / "configs/examples/lab-smart-factory.json").read_text()))
            start("publishers", [str(PYTHON), str(ROOT / "infra/telemetry-simulator.py"), "--api", api_url,
                                 "--secrets", str(private_file), "--credentials", str(credentials)], ROOT, environment)
            start("frontend", ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", str(website), "--strictPort"],
                  ROOT / "frontend", {**environment, "API_PROXY_TARGET": api_url})
            wait_ready(f"http://127.0.0.1:{website}", processes)
            private_json(directory / "addresses.json", {"website_port": website, "api_port": api,
                                                       "postgres_port": postgres_port, "lan_addresses": lan_addresses()})
            print(f"\nDemo website: http://localhost:{website}", flush=True)
            for address in lan_addresses():
                print(f"Phone / other PC: http://{address}:{website}", flush=True)
            print(f"Public customer store: http://localhost:{website}/#/shop", flush=True)
            print(f"Admin and worker usernames/passwords: {credentials}", flush=True)
            print(f"Private logs and durable demo data: {directory}", flush=True)
            print("No customer login. Machine publishers use real PostgreSQL; evidence approval still requires an administrator.", flush=True)
            print("Press Ctrl+C to stop only this owned demo stack; data is retained.\n", flush=True)
            while not STOP:
                if any(process.poll() is not None for process in processes):
                    raise RuntimeError("A demo service stopped; check the private demo logs")
                time.sleep(0.5)
        finally:
            for process in reversed(processes):
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            for process in processes:
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            if database_started:
                subprocess.run([str(binaries / "pg_ctl"), "-D", str(directory / "postgres"), "-m", "fast", "-w", "stop"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for logfile in logs:
                logfile.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Demo startup failed; inspect .run/demo logs. No credentials are printed. PostgreSQL may require POSTGRES_BIN on unsupported platforms.") from None
