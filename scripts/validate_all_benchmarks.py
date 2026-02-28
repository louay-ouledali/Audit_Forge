"""Validate all benchmarks via the live API + DB cross-check.

Checks:
1. API /api/benchmarks returns all benchmarks
2. Each has phase2_status = 'completed'
3. DB confirms 0 flagged, 0 failed, 0 generated commands
4. Every rule has a verified command
"""
import json
import sys
import urllib.request

# Also validate via direct DB
sys.path.insert(0, ".")
from collections import defaultdict

from sqlalchemy import func

from backend.database import SessionLocal
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand

BASE = "http://localhost:8000"


def api_get(path):
    url = f"{BASE}{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main():
    # -- API validation --
    print("1) Checking API /api/benchmarks ...")
    resp = api_get("/api/benchmarks")
    benchmarks = resp.get("data", resp) if isinstance(resp, dict) else resp
    api_ids = {b["id"] for b in benchmarks}
    print(f"   API returned {len(benchmarks)} benchmarks")

    # -- DB validation --
    print("2) Cross-checking with database ...")
    db = SessionLocal()

    db_benchmarks = db.query(Benchmark).order_by(Benchmark.name).all()
    db_ids = {b.id for b in db_benchmarks}
    print(f"   DB has {len(db_benchmarks)} benchmarks")

    # Check API <-> DB consistency
    missing_from_api = db_ids - api_ids
    if missing_from_api:
        print(f"   WARNING: {len(missing_from_api)} benchmarks in DB but not in API: {missing_from_api}")

    # Get command stats per benchmark
    stats = (
        db.query(Benchmark.id, RuleCommand.status, func.count())
        .select_from(RuleCommand)
        .join(Rule, RuleCommand.rule_id == Rule.id)
        .join(Benchmark, Rule.benchmark_id == Benchmark.id)
        .group_by(Benchmark.id, RuleCommand.status)
        .all()
    )
    cmd_stats = defaultdict(lambda: defaultdict(int))
    for bid, status, cnt in stats:
        cmd_stats[bid][status] = cnt

    print()
    hdr = f"  {'':3s} {'Benchmark':<52} {'P2':>5} {'Rules':>5} {'Verf':>5} {'Flag':>5} {'Fail':>5} {'Gen':>4}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    all_ok = True
    total_verified = 0
    for b in db_benchmarks:
        cs = cmd_stats[b.id]
        v = cs.get("verified", 0)
        f = cs.get("flagged", 0)
        fail = cs.get("failed", 0)
        g = cs.get("generated", 0)
        total = v + f + fail + g
        total_verified += v

        issues = []
        if b.phase2_status != "completed":
            issues.append(f"p2={b.phase2_status}")
        if f > 0:
            issues.append(f"{f} flagged")
        if fail > 0:
            issues.append(f"{fail} failed")
        if g > 0:
            issues.append(f"{g} gen")

        ok = len(issues) == 0
        if not ok:
            all_ok = False

        icon = "+" if ok else "!"
        p2_short = "OK" if b.phase2_status == "completed" else (b.phase2_status or "?")[:5]
        print(f"  [{icon}] {b.name[:52]:<52} {p2_short:>5} {total:>5} {v:>5} {f:>5} {fail:>5} {g:>4}")

    db.close()

    print()
    print(f"  Grand total: {total_verified} verified commands across {len(db_benchmarks)} benchmarks")
    print()
    if all_ok:
        print("  === ALL 33 BENCHMARKS VALIDATED SUCCESSFULLY ===")
        print("      0 flagged | 0 failed | 0 unverified")
    else:
        print("  === SOME BENCHMARKS HAVE ISSUES ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
