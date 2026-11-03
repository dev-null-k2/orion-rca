"""Evals: end-to-end RCA accuracy (with repeated noisy trials), retrieval quality, flow identification,
and a release gate. `orion eval` writes a JSON and Markdown report under ./results.
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import yaml

from ..estate.builder import KB_DIR, list_scenarios, load_scenario
from ..flows import Catalog
from ..retrieval import HashEmbedder, KnowledgeBase
from ..runner import investigate

SETS = Path(__file__).parent / "sets"
NOISE_LEVELS = [1.0, 2.0, 3.0]  # trial k uses seed k and a louder background


def score_case(scenario_id: str, answer) -> dict:
    truth = load_scenario(scenario_id)["truth"]
    rc = answer.root_cause
    text = answer.text()
    blamed = "\n".join([answer.summary, rc.statement] + [c.statement for c in answer.causal_chain])
    facts = [f for f in truth["facts"] if f.lower() in text.lower()]
    forbidden = [f for f in truth.get("forbidden", []) if f.lower() in blamed.lower()]
    ok_service = rc.service == truth["root_service"]
    ok_file = rc.file in truth["root_files"]
    fact_recall = len(facts) / len(truth["facts"])
    return {"service_ok": ok_service, "file_ok": ok_file, "fact_recall": round(fact_recall, 2),
            "forbidden": forbidden, "verified": answer.verdict == "verified", "confidence": answer.confidence,
            "passed": ok_service and ok_file and fact_recall >= 0.75 and not forbidden}


def rca_eval(policy: str, k: int = 3) -> dict:
    cases = []
    for sid in list_scenarios():
        trials = []
        for trial in range(k):
            r = investigate(sid, policy, seed=trial + 1, noise=NOISE_LEVELS[trial % len(NOISE_LEVELS)])
            s = score_case(sid, r.answer) | {"tool_calls": r.tool_calls, "seconds": round(r.seconds, 3),
                                              "evidence": len(r.harness.ledger.records)}
            trials.append(s)
        cases.append({"scenario": sid, "trials": trials, "pass_all": all(t["passed"] for t in trials)})
    flat = [t for c in cases for t in c["trials"]]
    passed = [t for t in flat if t["passed"]]
    wrong_conf = [t["confidence"] for t in flat if not t["passed"]]
    return {
        "policy": policy, "k": k, "scenarios": len(cases),
        "pass_at_1": round(len(passed) / len(flat), 3),
        "pass_hat_k": round(sum(c["pass_all"] for c in cases) / len(cases), 3),
        "root_service_acc": round(statistics.mean(t["service_ok"] for t in flat), 3),
        "root_file_acc": round(statistics.mean(t["file_ok"] for t in flat), 3),
        "fact_recall": round(statistics.mean(t["fact_recall"] for t in flat), 3),
        "forbidden_claims": sum(len(t["forbidden"]) for t in flat),
        "verified_rate": round(statistics.mean(t["verified"] for t in flat), 3),
        "mean_confidence_when_right": round(statistics.mean([t["confidence"] for t in passed]), 2) if passed else None,
        "mean_confidence_when_wrong": round(statistics.mean(wrong_conf), 2) if wrong_conf else None,
        "median_tool_calls": statistics.median(t["tool_calls"] for t in flat),
        "median_seconds": round(statistics.median(t["seconds"] for t in flat), 3),
        "cases": cases,
    }


def retrieval_eval() -> dict:
    items = yaml.safe_load((SETS / "retrieval.yaml").read_text())
    out = {}
    for label, weights in {"bm25": (1.0, 0.0), "dense": (0.0, 1.0), "hybrid": (1.0, 1.0)}.items():
        kb = KnowledgeBase(KB_DIR, embedder=HashEmbedder(), bm25_weight=weights[0], dense_weight=weights[1])
        ranks = []
        for it in items:
            pages = kb.pages(it["q"], k=10)
            ranks.append(pages.index(it["page"]) + 1 if it["page"] in pages else None)
        out[label] = {"recall_at_1": round(sum(r == 1 for r in ranks) / len(ranks), 3),
                      "recall_at_3": round(sum(bool(r and r <= 3) for r in ranks) / len(ranks), 3),
                      "mrr": round(sum(1 / r for r in ranks if r) / len(ranks), 3)}
    out["queries"] = len(items)
    return out


def flow_eval() -> dict:
    items = yaml.safe_load((SETS / "flows.yaml").read_text())
    cat, kb = Catalog(), KnowledgeBase(KB_DIR)
    top1 = top3 = asked = 0
    for it in items:
        a = cat.rank_flows(it["t"], kb)
        ids = [r.flow_id for r in a.ranked]
        top1 += bool(ids and ids[0] == it["flow"])
        top3 += it["flow"] in ids[:3]
        asked += a.pick is None
    n = len(items)
    return {"tickets": n, "top1": round(top1 / n, 3), "top3": round(top3 / n, 3), "asks_engineer": round(asked / n, 3)}


GATE = {"pass_at_1": 0.85, "pass_hat_k": 0.85, "forbidden_claims": 0, "verified_rate": 0.85,
        "retrieval_recall_at_3": 0.85, "flow_top3": 0.85}


def gate(report: dict) -> list[str]:
    rca = report["rca"]["reference"]
    checks = {
        "pass_at_1": rca["pass_at_1"] >= GATE["pass_at_1"],
        "pass_hat_k": rca["pass_hat_k"] >= GATE["pass_hat_k"],
        "forbidden_claims": rca["forbidden_claims"] <= GATE["forbidden_claims"],
        "verified_rate": rca["verified_rate"] >= GATE["verified_rate"],
        "retrieval_recall_at_3": report["retrieval"]["hybrid"]["recall_at_3"] >= GATE["retrieval_recall_at_3"],
        "flow_top3": report["flows"]["top3"] >= GATE["flow_top3"],
    }
    for name in ("loudest-error", "error-owner", "no-walk-back"):
        if name in report["rca"]:
            checks[f"beats_{name}"] = rca["pass_at_1"] > report["rca"][name]["pass_at_1"]
    return [k for k, ok in checks.items() if not ok]


def run_all(policies=("reference", "no-walk-back", "error-owner", "loudest-error"), k: int = 3,
            out_dir: Path = Path("results")) -> dict:
    t0 = time.monotonic()
    report = {"rca": {p: rca_eval(p, k) for p in policies}, "retrieval": retrieval_eval(), "flows": flow_eval()}
    report["gate_failures"] = gate(report)
    report["seconds"] = round(time.monotonic() - t0, 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eval-report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "eval-report.md").write_text(to_markdown(report))
    return report


def to_markdown(r: dict) -> str:
    lines = ["# Orion eval report", "", "## End-to-end RCA", "",
             "| Policy | pass@1 | pass^k | Root service | Root file | Fact recall | Forbidden | Verified | Median tool calls |",
             "|---|---|---|---|---|---|---|---|---|"]
    for p, x in r["rca"].items():
        lines.append(f"| {p} | {x['pass_at_1']:.0%} | {x['pass_hat_k']:.0%} | {x['root_service_acc']:.0%} | "
                     f"{x['root_file_acc']:.0%} | {x['fact_recall']:.0%} | {x['forbidden_claims']} | "
                     f"{x['verified_rate']:.0%} | {x['median_tool_calls']} |")
    lines += ["", f"## Retrieval (KB, {r['retrieval']['queries']} queries)", "", "| Mode | recall@1 | recall@3 | MRR |",
              "|---|---|---|---|"]
    for m in ("bm25", "dense", "hybrid"):
        x = r["retrieval"][m]
        lines.append(f"| {m} | {x['recall_at_1']:.0%} | {x['recall_at_3']:.0%} | {x['mrr']:.2f} |")
    f = r["flows"]
    lines += ["", f"## Flow identification ({f['tickets']} tickets)", "",
              f"top-1 {f['top1']:.0%}, top-3 {f['top3']:.0%}, asks the engineer on {f['asks_engineer']:.0%}", "",
              "## Gate", "", "PASS" if not r["gate_failures"] else "FAIL: " + ", ".join(r["gate_failures"])]
    return "\n".join(lines) + "\n"
