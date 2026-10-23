from collections import defaultdict
from threading import Lock

_lock = Lock()
_counters: dict[str, int] = defaultdict(int)
_match_sum = 0.0
_match_count = 0


def increment(name: str, amount: int = 1) -> None:
    with _lock:
        _counters[name] += amount


def observe_match_score(score: float) -> None:
    global _match_sum, _match_count
    with _lock:
        _match_sum += score
        _match_count += 1


def render_metrics() -> str:
    with _lock:
        lines = [
            "# TYPE jobs_discovered_total counter",
            f"jobs_discovered_total {_counters['jobs_discovered_total']}",
            "# TYPE jobs_matched_total counter",
            f"jobs_matched_total {_counters['jobs_matched_total']}",
            "# TYPE applications_started_total counter",
            f"applications_started_total {_counters['applications_started_total']}",
            "# TYPE applications_submitted_total counter",
            f"applications_submitted_total {_counters['applications_submitted_total']}",
            "# TYPE applications_failed_total counter",
            f"applications_failed_total {_counters['applications_failed_total']}",
            "# TYPE manual_actions_total counter",
            f"manual_actions_total {_counters['manual_actions_total']}",
            "# TYPE connector_errors_total counter",
            f"connector_errors_total {_counters['connector_errors_total']}",
            "# TYPE worker_failures_total counter",
            f"worker_failures_total {_counters['worker_failures_total']}",
            "# TYPE http_requests_total counter",
            f"http_requests_total {_counters['http_requests_total']}",
            "# TYPE average_match_score gauge",
            f"average_match_score {_match_sum / _match_count if _match_count else 0:.2f}",
        ]
        return "\n".join(lines) + "\n"
