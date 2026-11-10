#!/usr/bin/env python3
"""Minimal, privacy-minded backend for ACDI Check (Python standard library only)."""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = Path(os.environ.get("ACDI_DB_PATH", str(ROOT / "data" / "acdi.sqlite3")))
HOST = os.environ.get("ACDI_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", os.environ.get("ACDI_PORT", "8000")))
MIN_GROUP_SIZE = max(5, int(os.environ.get("ACDI_MIN_GROUP_SIZE", "5")))
COMPONENTS = ("ID", "CPD", "JD", "IPL")


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_aggregates (
                day TEXT PRIMARY KEY,
                n INTEGER NOT NULL DEFAULT 0,
                sum_acdi REAL NOT NULL DEFAULT 0,
                sum_scenario REAL NOT NULL DEFAULT 0,
                sum_id REAL NOT NULL DEFAULT 0,
                sum_cpd REAL NOT NULL DEFAULT 0,
                sum_jd REAL NOT NULL DEFAULT 0,
                sum_ipl REAL NOT NULL DEFAULT 0,
                level_1 INTEGER NOT NULL DEFAULT 0,
                level_2 INTEGER NOT NULL DEFAULT 0,
                level_3 INTEGER NOT NULL DEFAULT 0,
                level_4 INTEGER NOT NULL DEFAULT 0
            )
        """)


def valid_number(value: object, low: float, high: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high


def get_stats() -> dict:
    with connect_db() as conn:
        rows = conn.execute("SELECT * FROM daily_aggregates ORDER BY day DESC").fetchall()
    total = sum(row["n"] for row in rows)
    if total < MIN_GROUP_SIZE:
        return {
            "available": False,
            "minGroupSize": MIN_GROUP_SIZE,
            "message": f"Thống kê sẽ hiển thị khi có ít nhất {MIN_GROUP_SIZE} lượt tham gia.",
        }

    sums = {key: sum(row[f"sum_{key.lower()}"] for row in rows) for key in COMPONENTS}
    levels = [sum(row[f"level_{i}"] for row in rows) for i in range(1, 5)]
    # Hide any category with fewer than the configured cohort threshold.
    safe_levels = [count if count >= MIN_GROUP_SIZE else None for count in levels]
    overall = {
        "count": total,
        "averageAcdi": round(sum(row["sum_acdi"] for row in rows) / total, 2),
        "averageScenario": round(sum(row["sum_scenario"] for row in rows) / total, 2),
        "components": {key: round(sums[key] / total, 2) for key in COMPONENTS},
        "levels": safe_levels,
    }
    # A day is returned only when it independently reaches the minimum cohort size.
    series = []
    for row in reversed(rows):
        if row["n"] < MIN_GROUP_SIZE:
            continue
        n = row["n"]
        series.append({
            "day": row["day"],
            "count": n,
            "averageAcdi": round(row["sum_acdi"] / n, 2),
            "averageScenario": round(row["sum_scenario"] / n, 2),
            "components": {key: round(row[f"sum_{key.lower()}"] / n, 2) for key in COMPONENTS},
        })
    return {"available": True, "minGroupSize": MIN_GROUP_SIZE, "overall": overall, "series": series}


class Handler(BaseHTTPRequestHandler):
    server_version = "ACDI-Check/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        # Do not write request/IP details to application logs.
        return

    def send_bytes(self, status: int, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status: int, value: dict) -> None:
        self.send_bytes(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/stats":
            self.send_json(200, get_stats())
        elif path == "/health":
            self.send_json(200, {"status": "ok"})
        elif path in ("/", "/index.html"):
            self.serve_file(STATIC / "index.html", "text/html; charset=utf-8")
        elif path == "/dashboard":
            self.serve_file(STATIC / "dashboard.html", "text/html; charset=utf-8")
        else:
            self.send_json(404, {"error": "Không tìm thấy đường dẫn."})

    def serve_file(self, path: Path, content_type: str) -> None:
        try:
            self.send_bytes(200, path.read_bytes(), content_type)
        except FileNotFoundError:
            self.send_json(404, {"error": "Tệp giao diện chưa được cài đặt."})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/submit":
            self.send_json(404, {"error": "Không tìm thấy đường dẫn."})
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "Yêu cầu phải là JSON."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 4096:
                raise ValueError("Kích thước dữ liệu không hợp lệ.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or payload.get("consent") is not True:
                raise ValueError("Cần có sự đồng ý tham gia.")
            comp = payload["components"]
            if not isinstance(comp, dict) or set(comp) != set(COMPONENTS):
                raise ValueError("Thiếu điểm thành phần.")
            if not all(valid_number(comp[k], 1, 5) for k in COMPONENTS):
                raise ValueError("Điểm thành phần không hợp lệ.")
            if not valid_number(payload.get("acdi"), 1, 5) or not valid_number(payload.get("scenario"), 1, 4):
                raise ValueError("Điểm tổng hợp không hợp lệ.")
            level = payload.get("level")
            if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 4:
                raise ValueError("Mức điểm không hợp lệ.")
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc) or "Dữ liệu không hợp lệ."})
            return

        day = datetime.now(timezone.utc).date().isoformat()
        values = [day, float(payload["acdi"]), float(payload["scenario"]),
                  *(float(comp[k]) for k in COMPONENTS),
                  *(1 if level == i else 0 for i in range(1, 5))]
        with connect_db() as conn:
            conn.execute("""
                INSERT INTO daily_aggregates
                  (day, n, sum_acdi, sum_scenario, sum_id, sum_cpd, sum_jd, sum_ipl, level_1, level_2, level_3, level_4)
                VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                  n=n+1, sum_acdi=sum_acdi+excluded.sum_acdi,
                  sum_scenario=sum_scenario+excluded.sum_scenario,
                  sum_id=sum_id+excluded.sum_id, sum_cpd=sum_cpd+excluded.sum_cpd,
                  sum_jd=sum_jd+excluded.sum_jd, sum_ipl=sum_ipl+excluded.sum_ipl,
                  level_1=level_1+excluded.level_1, level_2=level_2+excluded.level_2,
                  level_3=level_3+excluded.level_3, level_4=level_4+excluded.level_4
            """, values)
        self.send_json(201, {"saved": True, "message": "Cảm ơn bạn đã chia sẻ điểm tổng hợp ẩn danh."})


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"ACDI Check backend ready: http://{HOST}:{PORT}")
    print(f"Dashboard: http://{HOST}:{PORT}/dashboard")
    print(f"Database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐang dừng máy chủ...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
