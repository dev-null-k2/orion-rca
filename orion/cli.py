"""Command line: `orion scenarios | investigate | eval | serve | mcp`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DIM, BOLD, CYAN, GREEN, YELLOW, RED, RESET = "\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"


def _color(enabled: bool):
    if not enabled:
        global DIM, BOLD, CYAN, GREEN, YELLOW, RED, RESET
        DIM = BOLD = CYAN = GREEN = YELLOW = RED = RESET = ""


def live_printer(event) -> None:
    d = event.data
    if event.kind == "start":
        print(f"{BOLD}Orion{RESET} investigating {CYAN}{d['ticket']}{RESET} with the {d['policy']} policy")
    elif event.kind == "step":
        extra = {k: v for k, v in d.items() if k != "name"}
        print(f"\n{BOLD}▸ {d['name'].replace('_', ' ')}{RESET} {DIM}{json.dumps(extra) if extra else ''}{RESET}")
    elif event.kind == "walk":
        print(f"\n{BOLD}▸ walk back{RESET} failure shows in {YELLOW}{d['failure_point']}{RESET} ({d['reason']})")
        print(f"  {DIM}order: {' → '.join(d['order'])}{RESET}")
    elif event.kind == "tool_end":
        eid = f"{GREEN}{d['evidence_id']}{RESET} " if d.get("evidence_id") else ""
        print(f"  {eid}{DIM}{d['tool']:<22}{RESET} {d['summary'][:96]} {DIM}{d['ms']}ms{RESET}")
    elif event.kind == "ask_default":
        print(f"  {YELLOW}?{RESET} {d['question']}: no engineer attached, took {BOLD}{d['answer']}{RESET}")
    elif event.kind == "verified":
        color = GREEN if not d["problems"] else RED
        print(f"\n{BOLD}▸ verify{RESET} {color}{len(d['problems'])} problem(s){RESET}, critic {d['verdict']}, "
              f"confidence {d['confidence']}/5")


def ask_terminal(kind: str, payload: dict):
    if kind != "flow":
        return None
    print(f"\n{BOLD}? Which business flow should I check?{RESET} {DIM}{payload['message']}{RESET}")
    for i, opt in enumerate(payload["options"], 1):
        print(f"  {i}. {opt['name']} {DIM}— {'; '.join(opt['why'][:2])}{RESET}")
    raw = input("  pick a number, or Enter for my pick: ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(payload["options"]):
        return payload["options"][int(raw) - 1]["id"]
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orion", description="Evidence-first root-cause analysis agent.")
    ap.add_argument("--no-color", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scenarios", help="list the demo incidents")
    inv = sub.add_parser("investigate", help="investigate one incident")
    inv.add_argument("scenario")
    inv.add_argument("--policy", default="reference", help="reference | llm | no-walk-back | error-owner | loudest-error")
    inv.add_argument("--interactive", action="store_true", help="answer the flow question yourself")
    inv.add_argument("--seed", type=int, default=7)
    inv.add_argument("--noise", type=float, default=1.0)
    inv.add_argument("--out", help="write the Markdown RCA here")
    inv.add_argument("--json", action="store_true", help="print the structured answer")
    ev = sub.add_parser("eval", help="run the eval suite and the release gate")
    ev.add_argument("-k", type=int, default=3)
    ev.add_argument("--policies", default="reference,no-walk-back,error-owner,loudest-error")
    ev.add_argument("--out", default="results")
    sv = sub.add_parser("serve", help="web UI and API")
    sv.add_argument("--port", type=int, default=8123)
    sub.add_parser("mcp", help="run as an MCP server over stdio")
    args = ap.parse_args(argv)
    _color(not args.no_color and sys.stdout.isatty())

    if args.cmd == "scenarios":
        from .estate.builder import list_scenarios, load_scenario
        for s in list_scenarios():
            sc = load_scenario(s)
            print(f"{s:<24} {sc['ticket']['key']:<9} {sc['title']}")
        return 0
    if args.cmd == "investigate":
        from .report import to_markdown
        from .runner import investigate
        r = investigate(args.scenario, args.policy, ask=ask_terminal if args.interactive else None,
                        seed=args.seed, noise=args.noise, listeners=[] if args.json else [live_printer])
        if args.json:
            print(r.answer.model_dump_json(indent=2))
        else:
            a = r.answer
            print(f"\n{BOLD}Root cause{RESET} ({a.root_cause.status}): {a.root_cause.statement}")
            if a.fix:
                print(f"{BOLD}Fix{RESET}: {a.fix.change}")
            print(f"{DIM}{r.tool_calls} tool calls · {len(r.harness.ledger.records)} evidence records · "
                  f"{r.seconds:.2f}s{RESET}")
        if args.out:
            Path(args.out).write_text(to_markdown(r))
        return 0
    if args.cmd == "eval":
        from .evals.run import run_all
        report = run_all(tuple(args.policies.split(",")), k=args.k, out_dir=Path(args.out))
        print((Path(args.out) / "eval-report.md").read_text())
        return 1 if report["gate_failures"] else 0
    if args.cmd == "serve":
        import uvicorn

        from .server import app
        uvicorn.run(app, host="127.0.0.1", port=args.port)
        return 0
    if args.cmd == "mcp":
        from .mcp import serve_stdio
        serve_stdio()
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
