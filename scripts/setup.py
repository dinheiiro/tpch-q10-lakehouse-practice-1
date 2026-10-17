"""Prepare private runtime config and register three Lakekeeper warehouses."""

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("LAKEHOUSE_RUNTIME", "D:/lakehouse-tpch-q10-runtime"))
ENV_FILE = RUNTIME / "runtime.env"
PORTS = {
    "MINIO_API_PORT": 9000,
    "MINIO_CONSOLE_PORT": 9001,
    "POSTGRES_PORT": 5432,
    "LAKEKEEPER_PORT": 8181,
    "TRINO_PORT": 8080,
    "SUPERSET_PORT": 8088,
}


def free_port(preferred: int) -> int:
    for port in [preferred, *range(20000, 40000)]:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free TCP port found")


def read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        raise SystemExit(f"Run prepare first: {ENV_FILE}")
    return dict(line.split("=", 1) for line in ENV_FILE.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#"))


def prepare() -> None:
    if ENV_FILE.exists():
        print(f"Existing private runtime preserved: {RUNTIME}")
        return
    RUNTIME.mkdir(parents=True, exist_ok=True)
    for directory in ("postgres", "catalog", "superset"):
        (RUNTIME / directory).mkdir(exist_ok=True)
    used = set()
    values = {"LAKEHOUSE_RUNTIME": RUNTIME.as_posix(), "MINIO_USER": "labadmin"}
    for key, preferred in PORTS.items():
        port = free_port(preferred)
        while port in used:
            port = free_port(port + 1)
        values[key] = str(port)
        used.add(port)
    for key in ("MINIO_PASSWORD", "POSTGRES_PASSWORD", "LAKEKEEPER_KEY", "SUPERSET_SECRET_KEY", "SUPERSET_ADMIN_PASSWORD"):
        values[key] = secrets.token_urlsafe(36)
    ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n", encoding="utf-8")
    for layer in ("bronze", "silver", "gold"):
        props = f"""connector.name=iceberg
iceberg.catalog.type=rest
iceberg.rest-catalog.uri=http://lakekeeper:8181/catalog
iceberg.rest-catalog.warehouse={layer}
iceberg.rest-catalog.nested-namespace-enabled=true
iceberg.unique-table-location=true
fs.native-s3.enabled=true
s3.endpoint=http://s3:9000
s3.path-style-access=true
s3.region=us-east-1
s3.aws-access-key={values['MINIO_USER']}
s3.aws-secret-key={values['MINIO_PASSWORD']}
"""
        (RUNTIME / "catalog" / f"{layer}.properties").write_text(props, encoding="utf-8")
    (RUNTIME / "catalog" / "tpch.properties").write_text("connector.name=tpch\n", encoding="utf-8")
    print(f"Private runtime prepared at {RUNTIME}; ports: " + ", ".join(f"{k}={values[k]}" for k in PORTS))


def request(method: str, url: str, payload: dict | None = None) -> tuple[int, str]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=15) as response:
            return response.status, response.read().decode()
    except HTTPError as exc:
        return exc.code, exc.read().decode()


def bootstrap(accept_terms: bool) -> None:
    if not accept_terms:
        raise SystemExit("Lakekeeper terms must be accepted explicitly with --accept-lakekeeper-terms")
    values = read_env()
    base = f"http://127.0.0.1:{values['LAKEKEEPER_PORT']}"
    for _ in range(60):
        try:
            code, _ = request("GET", base + "/health")
            if code == 200:
                break
        except (URLError, TimeoutError):
            time.sleep(2)
    else:
        raise SystemExit("Lakekeeper is not healthy")
    code, body = request("POST", base + "/management/v1/bootstrap", {"accept-terms-of-use": True})
    if code not in (200, 201, 204, 400, 409):
        raise RuntimeError(f"Lakekeeper bootstrap failed ({code}): {body}")
    for layer in ("bronze", "silver", "gold"):
        payload = {
            "warehouse-name": layer,
            "project-id": "00000000-0000-0000-0000-000000000000",
            "storage-profile": {
                "type": "s3", "bucket": layer, "key-prefix": "", "endpoint": "http://s3:9000",
                "region": "us-east-1", "path-style-access": True, "flavor": "s3-compat", "sts-enabled": False,
            },
            "storage-credential": {
                "type": "s3", "credential-type": "access-key", "access-key-id": values["MINIO_USER"],
                "secret-access-key": values["MINIO_PASSWORD"],
            },
        }
        code, body = request("POST", base + "/management/v1/warehouse", payload)
        if code not in (200, 201, 409):
            raise RuntimeError(f"Warehouse {layer} failed ({code}): {body}")
        print(f"Warehouse {layer}: HTTP {code}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "bootstrap"))
    parser.add_argument("--accept-lakekeeper-terms", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        bootstrap(args.accept_lakekeeper_terms)
