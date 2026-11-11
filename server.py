#!/usr/bin/env python3
"""Privacy-minded ACDI aggregate API using PostgreSQL and Python."""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
# Render sets PORT; bind all interfaces there so its port scan can reach the app.
HOST = os.environ.get("ACDI_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
PORT = int(os.environ.get("PORT", os.environ.get("ACDI_PORT", "8000")))
MIN_GROUP_SIZE = max(5, int(os.environ.get("ACDI_MIN_GROUP_SIZE", "5")))
COMPONENTS = ("ID", "CPD", "JD", "IPL")


def connect_db() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    # Avoid server-side prepared statements for compatibility with pooled Neon URLs.
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10,
        row_factory=dict_row,
        prepare_threshold=None,
    )


def init_db() -> None:
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_aggregates (
                day DATE PRIMARY KEY,
                n BIGINT NOT NULL DEFAULT 0,
                sum_acdi DOUBLE PRECISION NOT NULL DEFAULT 0,
                sum_scenario DOUBLE PRECISION NOT NULL DEFAULT 0,
                sum_id DOUBLE PRECISION NOT NULL DEFAULT 0,
                sum_cpd DOUBLE PRECISION NOT NULL DEFAULT 0,
                sum_jd DOUBLE PRECISION NOT NULL DEFAULT 0,
                sum_ipl DOUBLE PRECISION NOT NULL DEFAULT 0,
                level_1 BIGINT NOT NULL DEFAULT 0,
                level_2 BIGINT NOT NULL DEFAULT 0,
                level_3 BIGINT NOT NULL DEFAULT 0,
                level_4 BIGINT NOT NULL DEFAULT 0
            )
        """)


def valid_number(value: object, low: float, high: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and low <= value <= high
    )


def get_stats() -> dict[str, object]:
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_aggregates ORDER BY day DESC"
        ).fetchall()

    total = sum(row["n"] for row in rows)
    if total < MIN_GROUP_SIZE:
        return {
            "available": False,
            "minGroupSize": MIN_GROUP_SIZE,
            "message": f"Thống kê sẽ hiển thị khi có ít nhất {MIN_GROUP_SIZE} lượt tham gia.",
        }

    sums = {
        key: sum(row[f"sum_{key.lower()}"] for row in rows)
        for key in COMPONENTS
    }
    levels = [sum(row[f"level_{i}"] for row in rows) for i in range(1, 5)]
    safe_levels = [count if count >= MIN_GROUP_SIZE else None for count in levels]
    overall = {
        "count": total,
        "averageAcdi": round(sum(row["sum_acdi"] for row in rows) / total, 2),
        "averageScenario": round(sum(row["sum_scenario"] for row in rows) / total, 2),
        "components": {key: round(sums[key] / total, 2) for key in COMPONENTS},
        "levels": safe_levels,
    }

    series = []
    for row in reversed(rows):
        if row["n"] < MIN_GROUP_SIZE:
            continue
        n = row["n"]
        series.append({
            "day": row["day"].isoformat(),
            "count": n,
            "averageAcdi": round(row["sum_acdi"] / n, 2),
            "averageScenario": round(row["sum_scenario"] / n, 2),
            "components": {
                key: round(row[f"sum_{key.lower()}"] / n, 2)
                for key in COMPONENTS
            },
        })
    return {
        "available": True,
        "minGroupSize": MIN_GROUP_SIZE,
        "overall": overall,
        "series": series,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "ACDI-Check/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        # Intentionally suppress request and client IP logs.
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

    def send_json(self, status: int, value: dict[str, object]) -> None:
        self.send_bytes(
            status,
            json.dumps(value, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            # Keep health checks independent of Neon to avoid waking an idle DB.
            self.send_json(200, {"status": "ok"})
        elif path == "/api/stats":
            try:
                self.send_json(200, get_stats())
            except (psycopg.Error, RuntimeError):
                self.send_json(503, {"error": "Tạm thời không tải được thống kê."})
        elif path in ("/", "/index.html"):
            self.serve_file(STATIC / "index.html")
        elif path == "/dashboard":
            self.serve_file(STATIC / "dashboard.html")
        else:
            self.send_json(404, {"error": "Không tìm thấy đường dẫn."})

    def serve_file(self, path: Path) -> None:
        try:
            self.send_bytes(200, path.read_bytes(), "text/html; charset=utf-8")
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
            expected = {"consent", "acdi", "components", "scenario", "level"}
            if set(payload) != expected:
                raise ValueError("Dữ liệu chứa trường không được hỗ trợ.")
            comp = payload["components"]
            if not isinstance(comp, dict) or set(comp) != set(COMPONENTS):
                raise ValueError("Thiếu điểm thành phần.")
            if not all(valid_number(comp[k], 1, 5) for k in COMPONENTS):
                raise ValueError("Điểm thành phần không hợp lệ.")
            if not valid_number(payload.get("acdi"), 1, 5):
                raise ValueError("Điểm ACDI không hợp lệ.")
            if not valid_number(payload.get("scenario"), 1, 4):
                raise ValueError("Điểm tình huống không hợp lệ.")
            level = payload.get("level")
            if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 4:
                raise ValueError("Mức điểm không hợp lệ.")
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc) or "Dữ liệu không hợp lệ."})
            return

        day = datetime.now(timezone.utc).date()
        values = [
            day,
            float(payload["acdi"]),
            float(payload["scenario"]),
            *(float(comp[k]) for k in COMPONENTS),
            *(1 if level == i else 0 for i in range(1, 5)),
        ]
        try:
            with connect_db() as conn:
                conn.execute("""
                    INSERT INTO daily_aggregates
                      (day, n, sum_acdi, sum_scenario, sum_id, sum_cpd,
                       sum_jd, sum_ipl, level_1, level_2, level_3, level_4)
                    VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (day) DO UPDATE SET
                      n = daily_aggregates.n + EXCLUDED.n,
                      sum_acdi = daily_aggregates.sum_acdi + EXCLUDED.sum_acdi,
                      sum_scenario = daily_aggregates.sum_scenario + EXCLUDED.sum_scenario,
                      sum_id = daily_aggregates.sum_id + EXCLUDED.sum_id,
                      sum_cpd = daily_aggregates.sum_cpd + EXCLUDED.sum_cpd,
                      sum_jd = daily_aggregates.sum_jd + EXCLUDED.sum_jd,
                      sum_ipl = daily_aggregates.sum_ipl + EXCLUDED.sum_ipl,
                      level_1 = daily_aggregates.level_1 + EXCLUDED.level_1,
                      level_2 = daily_aggregates.level_2 + EXCLUDED.level_2,
                      level_3 = daily_aggregates.level_3 + EXCLUDED.level_3,
                      level_4 = daily_aggregates.level_4 + EXCLUDED.level_4
                """, values)
        except (psycopg.Error, RuntimeError):
            self.send_json(503, {"error": "Tạm thời không lưu được dữ liệu."})
            return

        self.send_json(201, {
            "saved": True,
            "message": "Cảm ơn bạn đã chia sẻ điểm tổng hợp ẩn danh.",
        })


def main() -> None:
    try:
        init_db()
    except (psycopg.Error, RuntimeError):
        # Do not print connection details or database credentials to logs.
        print("Database startup check failed; verify the DATABASE_URL setting.", file=sys.stderr)
        raise SystemExit(1)

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"ACDI Check backend ready: http://{HOST}:{PORT}")
    print(f"Dashboard: http://{HOST}:{PORT}/dashboard")
    print("Database: PostgreSQL (connection details hidden)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐang dừng máy chủ...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
