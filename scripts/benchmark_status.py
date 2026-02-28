"""Show verification status summary for all benchmarks."""
from collections import defaultdict
from backend.database import SessionLocal
from backend.models.rule_command import RuleCommand
from backend.models.rule import Rule
from backend.models.benchmark import Benchmark
from sqlalchemy import func

db = SessionLocal()
rows = (db.query(Benchmark.name, RuleCommand.status, func.count())
    .select_from(RuleCommand).join(Rule, RuleCommand.rule_id == Rule.id).join(Benchmark, Rule.benchmark_id == Benchmark.id)
    .group_by(Benchmark.name, RuleCommand.status)
    .order_by(Benchmark.name, RuleCommand.status)
    .all())

data = defaultdict(dict)
for name, status, cnt in rows:
    data[name][status] = cnt

header = f"{'Benchmark':<55} {'verified':>8} {'generated':>10} {'flagged':>8} {'failed':>7}"
print(header)
print("-" * len(header))
for name in sorted(data.keys()):
    d = data[name]
    v = d.get("verified", 0)
    g = d.get("generated", 0)
    f = d.get("flagged", 0)
    fail = d.get("failed", 0)
    print(f"{name[:55]:<55} {v:>8} {g:>10} {f:>8} {fail:>7}")

print()
total_v = sum(d.get("verified", 0) for d in data.values())
total_g = sum(d.get("generated", 0) for d in data.values())
total_f = sum(d.get("flagged", 0) for d in data.values())
total_fail = sum(d.get("failed", 0) for d in data.values())
print(f"{'TOTAL':<55} {total_v:>8} {total_g:>10} {total_f:>8} {total_fail:>7}")
db.close()
