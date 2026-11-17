"""loopback Transport의 조회만 최대 60초 관측한다. 상태/본문을 변경하는 호출은 없다."""
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--large-map-samples", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if (parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
            or not 1 <= args.seconds <= 60 or args.interval < 0.5
            or not 0 <= args.large_map_samples <= 3):
        parser.error("loopback origin, 1~60초, 간격>=0.5초, 지도 0~3회만 허용합니다")
    samples = []
    def sample(path):
        started = monotonic()
        record = {"at": datetime.now(UTC).isoformat(), "route": urlsplit(path).path}
        try:
            with urlopen(args.base_url.rstrip("/")+path, timeout=5) as response:
                body = response.read()
                record.update(status=response.status, bytes=len(body),
                              server_timing=response.headers.get("Server-Timing"))
        except HTTPError as exc:
            record["status"] = exc.code
        except (URLError, TimeoutError):
            record["status"] = "timeout_or_connection_error"
        record["seconds"] = monotonic()-started
        samples.append(record)
    started_at = datetime.now(UTC).isoformat()
    deadline = monotonic()+args.seconds
    while monotonic() < deadline:
        for path in ("/health", "/v1/airports"):
            if monotonic() < deadline:
                sample(path)
        sleep(min(args.interval, max(0, deadline-monotonic())))
    for _ in range(args.large_map_samples):
        sample("/v1/transport/features/places?limit=5000")
    summary = {}
    for route in {row["route"] for row in samples}:
        values = sorted(row["seconds"] for row in samples if row["route"] == route)
        summary[route] = {"samples": len(values), "p95_seconds": values[max(0, int(len(values)*0.95+0.9999)-1)]}
    result = {"started_at": started_at, "finished_at": datetime.now(UTC).isoformat(),
              "samples": samples, "summary": summary,
              "parking_rebuild_interval": "별도 운영 로그의 시작/끝과 대조해야 함"}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
