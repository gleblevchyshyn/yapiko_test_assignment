"""Evaluate the /parse service on data/dev_set.json.

Two ways to run:

  # 1. Against a service that is already running (model = whatever it was started with)
  uv run python eval.py --base-url http://127.0.0.1:8000 --label gemini-2.5-flash

  # 2. Compare several models: eval starts the service once per model
  #    (LLM_MODEL / LLM_MODE are overridden via env), runs the dev set, stops it
  uv run python eval.py --models eval_models.json

Results are printed and saved to eval_results/<label>.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).parent
DEFAULT_DEV_SET = ROOT / "data" / "dev_set.json"
DEFAULT_MENU = ROOT / "data" / "menu.csv"
RESULTS_DIR = ROOT / "eval_results"
APP = "yapiko_test_assignment.main:app"


# ---------------------------------------------------------------- normalization


def norm(text: str | None) -> str:
    """Lowercase, drop punctuation, collapse spaces: 'Науки 47, подъезд 2' == 'науки 47 подъезд 2'."""
    if not text:
        return ""
    text = re.sub(r"[^\w\s]", " ", text.casefold())
    return " ".join(text.split())


def texts_match(a: str, b: str) -> bool:
    """Lenient match for free-text spans: equal after norm, or one contains the other."""
    a, b = norm(a), norm(b)
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def load_menu_skus(path: Path) -> set[str]:
    with open(path, encoding="utf-8-sig", newline="") as file:
        return {row["sku"] for row in csv.DictReader(file)}


# ---------------------------------------------------------------- running cases


@dataclass
class CaseResult:
    id: str
    message: str
    expected: dict[str, Any]
    got: dict[str, Any] | None
    latency_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    fallback: bool = False
    error: str | None = None
    mismatches: dict[str, Any] = field(default_factory=dict)


def _int_header(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    return int(value) if value is not None else None


def run_one(client: httpx.Client, case: dict[str, Any]) -> CaseResult:
    start = time.perf_counter()
    try:
        resp = client.post("/parse", json={"message": case["message"]})
        latency = time.perf_counter() - start
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        latency = time.perf_counter() - start
        print(f"  {case['id']}: ERROR {exc}", flush=True)
        return CaseResult(
            case["id"], case["message"], case["expected"], None, latency, error=str(exc)
        )

    cost = resp.headers.get("X-Cost-USD")
    result = CaseResult(
        id=case["id"],
        message=case["message"],
        expected=case["expected"],
        got=resp.json(),
        latency_s=latency,
        prompt_tokens=_int_header(resp.headers, "X-Prompt-Tokens"),
        completion_tokens=_int_header(resp.headers, "X-Completion-Tokens"),
        cost_usd=float(cost) if cost is not None else None,
        fallback=resp.headers.get("X-LLM-Fallback") == "true",
    )
    print(
        f"  {case['id']}: {latency:.2f}s" + (" FALLBACK" if result.fallback else ""),
        flush=True,
    )
    return result


def run_cases(
    base_url: str, cases: list[dict[str, Any]], concurrency: int = 1
) -> list[CaseResult]:
    # concurrency=1 gives clean per-request latency; higher values finish faster,
    # but latency then includes waiting under load and provider rate limits may kick in.
    with httpx.Client(base_url=base_url, timeout=120) as client:
        if concurrency <= 1:
            return [run_one(client, case) for case in cases]
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            return list(
                pool.map(lambda case: run_one(client, case), cases)
            )  # map keeps input order


# ---------------------------------------------------------------- scoring one case


def unit_counter(items: list[dict[str, Any]], detailed: bool) -> Counter:
    """Count ordered units.

    detailed=False -> key is SKU only (two lines of 1 == one line of 2).
    detailed=True  -> key also includes options and normalized comment.
    """
    counter: Counter = Counter()
    for item in items:
        if detailed:
            key = (
                item["sku"],
                tuple(sorted(item.get("options", {}).items())),
                norm(item.get("comment")),
            )
        else:
            key = item["sku"]
        counter[key] += item["qty"]
    return counter


def overlap(a: Counter, b: Counter) -> int:
    return sum((a & b).values())


def ambiguous_key(entry: dict[str, Any]) -> tuple:
    # Text span is free-form ("филадельфии" vs "две филадельфии"), so compare by what matters:
    # which dishes are offered and how many.
    return (frozenset(entry["candidates"]), entry["qty"])


def not_found_match(expected: list[str], got: list[str]) -> bool:
    if len(expected) != len(got):
        return False
    remaining = list(got)
    for text in expected:
        hit = next((g for g in remaining if texts_match(text, g)), None)
        if hit is None:
            return False
        remaining.remove(hit)
    return True


def score_case(result: CaseResult, menu_skus: set[str]) -> dict[str, Any]:
    exp = result.expected
    got = result.got
    if got is None:
        return {"ok": False}

    exp_units = unit_counter(exp["items"], detailed=False)
    got_units = unit_counter(got["items"], detailed=False)
    exp_detailed = unit_counter(exp["items"], detailed=True)
    got_detailed = unit_counter(got["items"], detailed=True)

    all_skus = (
        [i["sku"] for i in got["items"]]
        + [s for a in got["ambiguous"] for s in a["candidates"]]
        + list(got["unavailable"])
    )
    invented = [s for s in all_skus if s not in menu_skus]

    checks = {
        "items_exact": exp_units == got_units,
        "details_exact": exp_detailed == got_detailed,
        "ambiguous": Counter(map(ambiguous_key, exp["ambiguous"]))
        == Counter(map(ambiguous_key, got["ambiguous"])),
        "unavailable": sorted(exp["unavailable"]) == sorted(got["unavailable"]),
        "not_found": not_found_match(exp["not_found"], got["not_found"]),
        "delivery_type": exp["delivery"]["type"] == got["delivery"]["type"],
        "address": norm(exp["delivery"]["address"]) == norm(got["delivery"]["address"]),
        "time": exp["delivery"]["time"] == got["delivery"]["time"],
        "payment": exp["payment"] == got["payment"],
        "persons": exp["persons"] == got["persons"],
        "total_uah": exp["total_uah"] == got["total_uah"],
        "needs_clarification": exp["needs_clarification"] == got["needs_clarification"],
    }

    field_values = {
        "items_exact": (dict(exp_units), dict(got_units)),
        "details_exact": (exp["items"], got["items"]),
        "ambiguous": (exp["ambiguous"], got["ambiguous"]),
        "unavailable": (exp["unavailable"], got["unavailable"]),
        "not_found": (exp["not_found"], got["not_found"]),
        "delivery_type": (exp["delivery"]["type"], got["delivery"]["type"]),
        "address": (exp["delivery"]["address"], got["delivery"]["address"]),
        "time": (exp["delivery"]["time"], got["delivery"]["time"]),
        "payment": (exp["payment"], got["payment"]),
        "persons": (exp["persons"], got["persons"]),
        "total_uah": (exp["total_uah"], got["total_uah"]),
        "needs_clarification": (exp["needs_clarification"], got["needs_clarification"]),
    }
    if result.fallback:
        # The model did not answer; a fallback response can coincidentally equal an
        # "empty order" expectation, so it must never count as a correct parse.
        checks = dict.fromkeys(checks, False)

    result.mismatches = {
        name: {"expected": field_values[name][0], "got": field_values[name][1]}
        for name, passed in checks.items()
        if not passed
    }

    return {
        "ok": True,
        "checks": checks,
        "units_tp": 0 if result.fallback else overlap(exp_units, got_units),
        "units_pred": sum(got_units.values()),
        "units_exp": sum(exp_units.values()),
        "details_tp": 0 if result.fallback else overlap(exp_detailed, got_detailed),
        "invented_skus": invented,
        # The costly error: service says "no operator needed" while the order actually needs one.
        "unsafe_auto_confirm": exp["needs_clarification"]
        and not got["needs_clarification"],
        # The cheap error: order goes to an operator although it was fine.
        "unneeded_clarification": not exp["needs_clarification"]
        and got["needs_clarification"],
    }


# ---------------------------------------------------------------- aggregate


def summarize(
    results: list[CaseResult],
    menu_skus: set[str],
    price_in: float | None,
    price_out: float | None,
) -> dict[str, Any]:
    scores = [score_case(r, menu_skus) for r in results]
    answered = [s for s in scores if s["ok"]]
    n = len(results)

    def rate(check: str) -> float:
        # Unanswered cases (HTTP errors) count as failures.
        return sum(s["checks"][check] for s in answered) / n if n else 0.0

    tp = sum(s["units_tp"] for s in answered)
    pred = sum(s["units_pred"] for s in answered)
    exp = sum(s["units_exp"] for s in answered) + sum(
        sum(i["qty"] for i in r.expected["items"])
        for r, s in zip(results, scores)
        if not s["ok"]
    )
    precision = tp / pred if pred else 0.0
    recall = tp / exp if exp else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    details_tp = sum(s["details_tp"] for s in answered)

    latencies = [r.latency_s for r in results if r.got is not None]
    prompt_tokens = [r.prompt_tokens for r in results if r.prompt_tokens is not None]
    completion_tokens = [
        r.completion_tokens for r in results if r.completion_tokens is not None
    ]

    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    if costs:
        avg_cost, cost_source = statistics.mean(costs), "provider (X-Cost-USD)"
    elif prompt_tokens and price_in is not None and price_out is not None:
        avg_cost = (
            statistics.mean(prompt_tokens) * price_in
            + statistics.mean(completion_tokens) * price_out
        ) / 1e6
        cost_source = "estimated from token prices"
    else:
        avg_cost, cost_source = None, "unknown"

    def pct(values: list[float], q: float) -> float:
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))]

    return {
        "cases": n,
        "http_errors": n - len(answered),
        "llm_fallbacks": sum(r.fallback for r in results),
        "items_precision": precision,
        "items_recall": recall,
        "items_f1": f1,
        "items_exact_rate": rate("items_exact"),
        "options_comment_accuracy": details_tp / tp if tp else 0.0,
        "invented_skus": sum(len(s["invented_skus"]) for s in answered),
        "ambiguous_accuracy": rate("ambiguous"),
        "unavailable_accuracy": rate("unavailable"),
        "not_found_accuracy": rate("not_found"),
        "needs_clarification_accuracy": rate("needs_clarification"),
        "unsafe_auto_confirms": sum(s["unsafe_auto_confirm"] for s in answered),
        "unneeded_clarifications": sum(s["unneeded_clarification"] for s in answered),
        "delivery_type_accuracy": rate("delivery_type"),
        "address_accuracy": rate("address"),
        "time_accuracy": rate("time"),
        "payment_accuracy": rate("payment"),
        "persons_accuracy": rate("persons"),
        "total_uah_accuracy": rate("total_uah"),
        "fully_correct_cases": sum(
            s["ok"] and all(s["checks"].values()) for s in scores
        ),
        "latency_avg_s": statistics.mean(latencies) if latencies else None,
        "latency_p90_s": pct(latencies, 0.9) if latencies else None,
        "latency_max_s": max(latencies) if latencies else None,
        "prompt_tokens_avg": statistics.mean(prompt_tokens) if prompt_tokens else None,
        "completion_tokens_avg": statistics.mean(completion_tokens)
        if completion_tokens
        else None,
        "cost_per_request_usd": avg_cost,
        "cost_source": cost_source,
    }


# ---------------------------------------------------------------- printing


def fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def print_summary(label: str, summary: dict[str, Any]) -> None:
    print(f"\n=== {label} ===")
    width = max(map(len, summary))
    for key, value in summary.items():
        if key.endswith("accuracy") or key.startswith("items_"):
            shown = f"{value:.1%}" if isinstance(value, float) else fmt(value)
        elif key == "cost_per_request_usd" and value is not None:
            shown = f"${value:.5f}  (${value * 1000:.2f} per 1000 orders)"
        else:
            shown = fmt(value)
        print(f"  {key:<{width}}  {shown}")


def print_errors(results: list[CaseResult]) -> None:
    print("\n--- Error analysis ---")
    for r in results:
        if r.error:
            print(f"\n{r.id}: HTTP ERROR {r.error}\n  message: {r.message}")
            continue
        if not r.mismatches:
            continue
        print(f"\n{r.id}: {r.message}" + ("  [LLM FALLBACK]" if r.fallback else ""))
        for name, values in r.mismatches.items():
            if name == "details_exact" and "items_exact" in r.mismatches:
                continue  # same root cause, avoid noise
            print(f"  {name}:")
            print(f"    expected: {json.dumps(values['expected'], ensure_ascii=False)}")
            print(f"    got:      {json.dumps(values['got'], ensure_ascii=False)}")


COMPARE_KEYS = [
    ("items_f1", "Items F1", "pct"),
    ("options_comment_accuracy", "Opt+comment", "pct"),
    ("invented_skus", "Invented SKU", "int"),
    ("needs_clarification_accuracy", "Clarif. acc", "pct"),
    ("unsafe_auto_confirms", "Unsafe auto-OK", "int"),
    ("delivery_type_accuracy", "Deliv. type", "pct"),
    ("address_accuracy", "Address", "pct"),
    ("total_uah_accuracy", "Total", "pct"),
    ("fully_correct_cases", "Fully correct", "int"),
    ("llm_fallbacks", "Fallbacks", "int"),
    ("latency_avg_s", "Latency avg", "sec"),
    ("cost_per_request_usd", "$/1000 req", "cost"),
]


def print_comparison(rows: list[tuple[str, dict[str, Any]]]) -> None:
    print("\n=== Model comparison ===")
    headers = ["Model"] + [title for _, title, _ in COMPARE_KEYS]
    table = []
    for label, s in rows:
        row = [label]
        for key, _, kind in COMPARE_KEYS:
            v = s.get(key)
            if v is None:
                row.append("—")
            elif kind == "pct":
                row.append(f"{v:.0%}")
            elif kind == "sec":
                row.append(f"{v:.2f}s")
            elif kind == "cost":
                row.append(f"${v * 1000:.2f}")
            elif kind == "int" and key == "fully_correct_cases":
                row.append(f"{v}/{s['cases']}")
            else:
                row.append(str(v))
        table.append(row)
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *table)]
    line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-+-".join("-" * w for w in widths))
    for row in table:
        print(" | ".join(str(x).ljust(w) for x, w in zip(row, widths)))


# ---------------------------------------------------------------- service management


def wait_healthy(base_url: str, timeout: float, proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("service exited during startup (see server log)")
        try:
            if httpx.get(f"{base_url}/health", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"service did not become healthy in {timeout}s")


def run_with_spawned_service(
    model_cfg: dict[str, Any], port: int, cases, menu_skus, concurrency: int
) -> dict[str, Any] | None:
    label = model_cfg.get("label") or model_cfg["model"]
    env = os.environ.copy()
    env["LLM_MODEL"] = model_cfg[
        "model"
    ]  # env vars take priority over .env in pydantic-settings
    if model_cfg.get("mode"):
        env["LLM_MODE"] = model_cfg["mode"]

    RESULTS_DIR.mkdir(exist_ok=True)
    log_path = RESULTS_DIR / f"{safe_name(label)}.server.log"
    base_url = f"http://127.0.0.1:{port}"
    print(
        f"\n### {label}  (mode={env.get('LLM_MODE', 'from .env')})  server log: {log_path}"
    )

    with open(log_path, "w") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                APP,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_healthy(base_url, timeout=30, proc=proc)
            results = run_cases(base_url, cases, concurrency)
        except RuntimeError as exc:
            print(f"  SKIPPED: {exc}")
            return None
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    return finish(
        label,
        results,
        menu_skus,
        model_cfg.get("price_in"),
        model_cfg.get("price_out"),
        model_cfg,
    )


def safe_name(label: str) -> str:
    return re.sub(r"[^\w.-]+", "_", label)


def finish(label, results, menu_skus, price_in, price_out, meta=None) -> dict[str, Any]:
    summary = summarize(results, menu_skus, price_in, price_out)
    print_summary(label, summary)
    print_errors(results)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{safe_name(label)}.json"
    out.write_text(
        json.dumps(
            {
                "label": label,
                "meta": meta or {},
                "summary": summary,
                "cases": [asdict(r) for r in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved: {out}")
    return summary


# ---------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="running service (single-run mode)",
    )
    parser.add_argument(
        "--label", default="current", help="name for results in single-run mode"
    )
    parser.add_argument(
        "--models",
        type=Path,
        help="JSON list of models to compare; spawns the service per model",
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="port for spawned services"
    )
    parser.add_argument("--dev-set", type=Path, default=DEFAULT_DEV_SET)
    parser.add_argument("--menu", type=Path, default=DEFAULT_MENU)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="parallel requests (1 = clean latency, higher = faster run)",
    )
    parser.add_argument(
        "--ids", help="comma-separated case ids to run, e.g. dev_04,dev_09"
    )
    parser.add_argument(
        "--price-in",
        type=float,
        help="USD per 1M input tokens (fallback cost estimate)",
    )
    parser.add_argument(
        "--price-out",
        type=float,
        help="USD per 1M output tokens (fallback cost estimate)",
    )
    args = parser.parse_args()

    cases = json.loads(args.dev_set.read_text(encoding="utf-8"))
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    menu_skus = load_menu_skus(args.menu)

    if args.models:
        models = json.loads(args.models.read_text(encoding="utf-8"))
        rows = []
        for cfg in models:
            summary = run_with_spawned_service(
                cfg, args.port, cases, menu_skus, args.concurrency
            )
            if summary is not None:
                rows.append((cfg.get("label") or cfg["model"], summary))
        if rows:
            print_comparison(rows)
    else:
        print(f"Running {len(cases)} cases against {args.base_url}")
        results = run_cases(args.base_url, cases, args.concurrency)
        finish(args.label, results, menu_skus, args.price_in, args.price_out)


if __name__ == "__main__":
    main()
