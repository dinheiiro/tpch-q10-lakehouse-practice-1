"""Load TPC-H sf1, validate Q10, and measure four Iceberg layouts on this host."""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import statistics
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("LAKEHOUSE_RUNTIME", "D:/lakehouse-tpch-q10-runtime"))
RESULTS = ROOT / "results" / "measurements.json"
TABLES = ("customer", "orders", "lineitem", "nation")
LAYOUTS = (("parquet_zstd", "PARQUET", "ZSTD"), ("parquet_gzip", "PARQUET", "GZIP"),
           ("orc_gzip", "ORC", "GZIP"), ("orc_zstd", "ORC", "ZSTD"))
FIELDS = ("custkey", "name", "revenue", "acctbal", "nation", "address", "phone", "comment")


class Trino:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        self.sessions = {}

    def query(self, sql: str):
        headers = {"X-Trino-User": "student", "X-Trino-Source": "tpch-q10-practice-1"}
        if self.sessions:
            headers["X-Trino-Session"] = ",".join(f"{k}={v}" for k, v in self.sessions.items())
        req = Request(self.base + "/v1/statement", data=sql.encode("utf-8"), headers=headers, method="POST")
        start = time.perf_counter()
        rows, columns = [], []
        while True:
            try:
                with urlopen(req, timeout=600) as response:
                    for item in response.headers.get_all("X-Trino-Set-Session", []):
                        key, value = item.split("=", 1)
                        self.sessions[key] = value
                    for item in response.headers.get_all("X-Trino-Clear-Session", []):
                        self.sessions.pop(item, None)
                    payload = json.load(response)
            except HTTPError as exc:
                raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode()[:1000]}\nSQL: {sql[:300]}") from exc
            if payload.get("error"):
                raise RuntimeError(f"Trino error: {payload['error'].get('message')}\nSQL: {sql[:500]}")
            if payload.get("columns"):
                columns = [c["name"] for c in payload["columns"]]
            rows.extend(payload.get("data", []))
            next_uri = payload.get("nextUri")
            if not next_uri:
                return {"columns": columns, "rows": rows, "elapsed_seconds": time.perf_counter() - start,
                        "query_id": payload.get("id")}
            parts = urlsplit(next_uri)
            base = urlsplit(self.base)
            req = Request(urlunsplit((base.scheme, base.netloc, parts.path, parts.query, parts.fragment)), headers=headers)


def one(db: Trino, sql: str):
    result = db.query(sql)
    if len(result["rows"]) != 1 or len(result["rows"][0]) != 1:
        raise RuntimeError(f"Expected one scalar: {sql}")
    return result["rows"][0][0]


def table_stats(db: Trino, full_name: str):
    catalog, schema, table = full_name.split(".")
    count = int(one(db, f"SELECT count(*) FROM {full_name}"))
    files = db.query(f'SELECT file_format, record_count, file_size_in_bytes FROM {catalog}.{schema}."{table}$files"')["rows"]
    return {"row_count": count, "data_file_count": len(files),
            "data_file_bytes": sum(int(r[2]) for r in files),
            "snapshot_file_rows": sum(int(r[1]) for r in files),
            "formats": sorted(set(str(r[0]) for r in files))}


def q10_for(suffix: str):
    sql = (ROOT / "sql" / "q10_control.sql").read_text(encoding="utf-8").strip().rstrip(";")
    for table in TABLES:
        target = table if suffix == "parquet_zstd" else f"{table}_{suffix}"
        sql = sql.replace(f"tpch.sf1.{table}", f"bronze.lab.{target}")
    return sql


def normalized(row):
    return (int(row[0]), str(row[1]), Decimal(str(row[2])).quantize(Decimal("0.01")),
            Decimal(str(row[3])), str(row[4]), str(row[5]), str(row[6]), str(row[7]))


def compare(reference, actual):
    left = {int(row[0]): normalized(row) for row in reference}
    right = {int(row[0]): normalized(row) for row in actual}
    raw_left = {int(row[0]): Decimal(str(row[2])) for row in reference}
    raw_right = {int(row[0]): Decimal(str(row[2])) for row in actual}
    keys = set(left) | set(right)
    differences = [key for key in sorted(keys) if left.get(key) != right.get(key)]
    raw_max = max((abs(raw_left[k] - raw_right[k]) for k in keys & raw_left.keys() & raw_right.keys()), default=Decimal(0))
    return {"reference_rows": len(reference), "actual_rows": len(actual),
            "different_rows_at_cent_precision": len(differences), "different_custkeys": differences,
            "max_raw_revenue_abs_difference": str(raw_max)}


def save(data):
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def run():
    env_file = RUNTIME / "runtime.env"
    if not env_file.exists():
        raise SystemExit("First run: python scripts/setup.py prepare")
    env = dict(line.split("=", 1) for line in env_file.read_text(encoding="utf-8").splitlines() if line)
    db = Trino(int(env["TRINO_PORT"]))
    data = {"run_started_utc": datetime.now(timezone.utc).isoformat(), "scale": "sf1", "trino_version": "476",
            "measurement_method": "client wall-clock seconds, sequential queries, one warm-up then five runs",
            "size_method": "sum of file_size_in_bytes in each current Iceberg $files metadata table",
            "revenue_comparison": "all non-revenue fields exact; revenue rounded to 0.01; raw max difference also recorded",
            "ports": {key: int(env[key]) for key in env if key.endswith("_PORT")}, "layouts": {}}
    print("Waiting for Trino", flush=True)
    for _ in range(90):
        try:
            data["catalogs"] = [r[0] for r in db.query("SHOW CATALOGS")["rows"]]
            if all(c in data["catalogs"] for c in ("bronze", "silver", "gold", "tpch")):
                break
        except Exception:
            time.sleep(2)
    else:
        raise SystemExit("Trino catalogs did not become ready")
    data["compression_session"] = db.query("SHOW SESSION LIKE 'bronze.compression_codec'")["rows"]
    for layer in ("bronze", "silver", "gold"):
        db.query(f"CREATE SCHEMA IF NOT EXISTS {layer}.lab")
    control_sql = (ROOT / "sql" / "q10_control.sql").read_text(encoding="utf-8")
    control = db.query(control_sql)
    data["control_q10"] = {"rows": control["rows"], "query_id": control["query_id"]}
    save(data)
    for suffix, fmt, codec in LAYOUTS:
        print(f"Writing {suffix}", flush=True)
        db.query(f"SET SESSION bronze.compression_codec = '{codec}'")
        metrics = {"format": fmt, "compression": codec, "tables": {}, "write_seconds": 0.0}
        for table in TABLES:
            target = table if suffix == "parquet_zstd" else f"{table}_{suffix}"
            sql = f"CREATE TABLE bronze.lab.{target} WITH (format = '{fmt}') AS SELECT * FROM tpch.sf1.{table}"
            write = db.query(sql)
            stats = table_stats(db, f"bronze.lab.{target}")
            source_count = int(one(db, f"SELECT count(*) FROM tpch.sf1.{table}"))
            if stats["row_count"] != source_count or stats["snapshot_file_rows"] != source_count or stats["formats"] != [fmt]:
                raise RuntimeError(f"Invalid table {target}: {stats}, source {source_count}")
            stats.update({"source_row_count": source_count, "write_seconds": write["elapsed_seconds"], "write_query_id": write["query_id"]})
            metrics["tables"][target] = stats
            metrics["write_seconds"] += write["elapsed_seconds"]
            data["layouts"][suffix] = metrics
            save(data)
        metrics["total_data_file_bytes"] = sum(t["data_file_bytes"] for t in metrics["tables"].values())
        query = q10_for(suffix)
        warm = db.query(query)
        metrics["warmup_seconds"] = warm["elapsed_seconds"]
        metrics["warmup_query_id"] = warm["query_id"]
        readings = [db.query(query) for _ in range(5)]
        metrics["q10_seconds"] = [r["elapsed_seconds"] for r in readings]
        metrics["q10_query_ids"] = [r["query_id"] for r in readings]
        metrics["median_seconds"] = statistics.median(metrics["q10_seconds"])
        metrics["min_seconds"] = min(metrics["q10_seconds"])
        metrics["max_seconds"] = max(metrics["q10_seconds"])
        metrics["control_comparison"] = compare(control["rows"], readings[-1]["rows"])
        if metrics["control_comparison"]["different_rows_at_cent_precision"]:
            raise RuntimeError(f"Q10 differs for {suffix}")
        save(data)
    print("Building Silver and Gold", flush=True)
    for statement in (ROOT / "sql" / "layers.sql").read_text(encoding="utf-8").split(";"):
        if statement.strip():
            db.query(statement)
    data["layers"] = {name: table_stats(db, name) for name in
                      ("silver.lab.customers_nation", "silver.lab.returned_items_q4_1993", "gold.lab.q10_top20")}
    checks = {}
    for statement in (ROOT / "sql" / "checks.sql").read_text(encoding="utf-8").split(";"):
        if statement.strip():
            result = db.query(statement)
            checks[result["columns"][0]] = int(result["rows"][0][0])
    data["quality_checks"] = checks
    if any(checks.values()):
        raise RuntimeError(f"Quality checks failed: {checks}")
    gold = db.query("SELECT custkey, name, revenue, acctbal, nation, address, phone, comment FROM gold.lab.q10_top20 ORDER BY revenue DESC")
    data["gold_comparison"] = compare(control["rows"], gold["rows"])
    if data["gold_comparison"]["different_rows_at_cent_precision"] or len(gold["rows"]) != 20:
        raise RuntimeError("Gold does not match control Q10")
    save(data)
    print("Demonstrating schema evolution and time travel", flush=True)
    db.query("CREATE TABLE silver.lab.schema_evolution_demo (id bigint, note varchar)")
    db.query("INSERT INTO silver.lab.schema_evolution_demo VALUES (1, 'before change')")
    before = int(one(db, 'SELECT snapshot_id FROM silver.lab."schema_evolution_demo$snapshots" ORDER BY committed_at DESC LIMIT 1'))
    db.query("ALTER TABLE silver.lab.schema_evolution_demo ADD COLUMN source_tag varchar")
    db.query("ALTER TABLE silver.lab.schema_evolution_demo RENAME COLUMN note TO description")
    db.query("INSERT INTO silver.lab.schema_evolution_demo (id, description, source_tag) VALUES (2, 'after change', 'sf1 demo')")
    old = db.query(f"SELECT * FROM silver.lab.schema_evolution_demo FOR VERSION AS OF {before} ORDER BY id")
    current = db.query("SELECT * FROM silver.lab.schema_evolution_demo ORDER BY id")
    data["schema_evolution"] = {"old_snapshot_id": before, "old_columns": old["columns"],
                                "old_rows": old["rows"], "current_columns": current["columns"],
                                "current_rows": current["rows"]}
    if len(old["rows"]) != 1 or len(current["rows"]) != 2:
        raise RuntimeError("Time travel row counts did not match")
    data["run_finished_utc"] = datetime.now(timezone.utc).isoformat()
    save(data)
    print(f"Verified run saved to {RESULTS}", flush=True)


if __name__ == "__main__":
    run()
