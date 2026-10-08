"""Build the run trees of a round under rounds/round<N>/ (one copy of the working tree per run) and check them.

    .venv/bin/python scripts/round6_setup.py --round 7                   # build and check the round's trees
    .venv/bin/python scripts/round6_setup.py --round 7 --only r1_rules   # one tree
    .venv/bin/python scripts/round6_setup.py --round 7 --check-only      # re-run the checks on existing trees
    .venv/bin/python scripts/round6_setup.py --round 7 --quick           # skip the slow checks (pool load, rule self-check)
    .venv/bin/python scripts/round6_setup.py --round 7 --smoke r7_rules_drafted   # after the checks: a smoke training run

Round six (report/round_six_results.md): r1_rules, r2_data, r3_rules_data. Round seven (report/round_seven_results.md):
r1_rules (round six's recipe, rerun) and r7_rules_drafted (the same plus data/drafted_train7.csv, staged at
rounds/round7/drafted_train7.csv). Every tree pins the grid to C = 0.3, rule weight 1.0; data/cache and data/raw are
relative symlinks to the live folders (the cache is shared; runs must be sequential). Nothing in the live tree is modified.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "backup_round4"
PY = Path(sys.executable)
RULES_DIFF = ROOT / "report" / "round_five_rules.diff"
CHECK_DIFF = ROOT / "report" / "round_five_check_rules.diff"

# original training rows the loaders gave the last run on each data version (report/train_log*.txt, "original")
POOL_ROWS = {"round4": 6965 + 6192, "round5": 8557 + 6894}
DRAFTED7 = ROOT / "rounds" / "round7" / "drafted_train7.csv"
TREES_BY_ROUND = {
    6: {
        "r1_rules": {"rules": True, "data": "round4", "extra_files": {}},
        "r2_data": {"rules": False, "data": "round5", "extra_files": {}},
        "r3_rules_data": {"rules": True, "data": "round5", "extra_files": {}},
    },
    7: {
        "r1_rules": {"rules": True, "data": "round4", "extra_files": {}},
        "r7_rules_drafted": {"rules": True, "data": "round4", "extra_files": {"data/drafted_train7.csv": DRAFTED7}},
    },
}
ROOT_EXCLUDES = {".git", ".venv", "backup_round3", "backup_round4", "rounds", "notebooks", ".claude", "report"}
REL_EXCLUDES = {Path("data/cache"), Path("data/raw"), Path("src/models/candidates")}
ANY_EXCLUDES = {"__pycache__", ".ipynb_checkpoints"}
PIN = [("for c in (0.3, 1)]", "for c in (0.3,)]"),
       ("RULE_WEIGHTS = (0.5, 1.0, 2.0)", "RULE_WEIGHTS = (1.0,)")]
PINNED_GRID = [{"svc__kernel": "linear", "svc__C": 0.3, "features__rules__weight__weight": 1.0}]
RECORDED = ["src/train.py", "src/rules.py", "scripts/check_rules.py", "data/new_train.csv", "data/new_test.csv"]

RUNS = None   # set by main(): ROOT / "rounds" / f"round{N}"


def md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def expected_diff(spec):
    files = {"src/train.py"}
    if spec["rules"]:
        files |= {"src/rules.py", "scripts/check_rules.py"}
    if spec["data"] == "round4":
        files |= {"data/new_train.csv", "data/new_test.csv"}
    return files | set(spec["extra_files"])


def expected_pool(spec):
    import csv
    extra = 0
    for rel, source in spec["extra_files"].items():
        if rel.startswith("data/") and source.exists():
            with open(source, encoding="utf-8", newline="") as handle:
                extra += sum(1 for _ in csv.DictReader(handle))      # rows, not lines: texts may hold newlines
    return POOL_ROWS[spec["data"]] + extra


def ignore(directory, names):
    rel = Path(directory).relative_to(ROOT)
    at_root = str(rel) == "."
    skip = set()
    for name in names:
        path = Path(name) if at_root else rel / name
        if at_root and name in ROOT_EXCLUDES:
            skip.add(name)
        elif name in ANY_EXCLUDES or name.endswith(".pyc"):
            skip.add(name)
        elif path in REL_EXCLUDES:
            skip.add(name)
        elif path.parent == Path("src/models") and name.endswith(".pkl"):
            skip.add(name)
    return skip


def without_first_hunk(diff_text):
    """The check-rules diff minus its first hunk (the HELD_OUT line, already in the live file)."""
    lines = diff_text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith("@@ ")]
    assert len(starts) >= 2, "expected at least two hunks"
    return "".join(lines[:starts[0]] + lines[starts[1]:])


def apply_patch(tree, diff_path):
    result = subprocess.run(["patch", "-p1", "-N", "--no-backup-if-mismatch", "-i", str(diff_path)],
                            cwd=tree, text=True, capture_output=True)
    for line in result.stdout.strip().splitlines():
        print(f"      {line}")
    if result.returncode != 0:
        sys.exit(f"patch {diff_path.name} failed in {tree}:\n{result.stdout}\n{result.stderr}")
    leftovers = [p for p in tree.rglob("*") if p.suffix in {".rej", ".orig"} and "data" not in p.parts]
    if leftovers:
        sys.exit(f"patch left {leftovers} in {tree}")


def pin_grid(tree):
    path = tree / "src" / "train.py"
    text = path.read_text(encoding="utf-8")
    for old, new in PIN:
        assert text.count(old) == 1, f"{path}: expected one occurrence of {old!r}, found {text.count(old)}"
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def build(name, spec):
    tree = RUNS / name
    if tree.exists():
        sys.exit(f"{tree} exists; remove it first or use --check-only")
    for source in spec["extra_files"].values():
        if not source.exists():
            sys.exit(f"extra file {source} missing")
    print(f"\n=== building {name} ===")
    RUNS.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(ROOT), str(tree), symlinks=True, ignore=ignore)
    (tree / "report").mkdir()
    for sub in ("cache", "raw"):
        os.symlink(f"../../../../data/{sub}", tree / "data" / sub)
    pin_grid(tree)
    print("  grid pinned to C = 0.3, rule weight 1.0")
    if spec["data"] == "round4":
        for csv in ("new_train.csv", "new_test.csv"):
            shutil.copy2(BACKUP / "data" / csv, tree / "data" / csv)
        print("  data: six-source new_train.csv / new_test.csv from backup_round4/data/")
    else:
        print("  data: nine-source new_train.csv / new_test.csv (live)")
    for rel, source in spec["extra_files"].items():
        shutil.copy2(source, tree / rel)
        print(f"  extra file: {rel} <- {source}")
    if spec["rules"]:
        print(f"  applying {RULES_DIFF.name}")
        apply_patch(tree, RULES_DIFF)
        trimmed = RUNS / "_scratch" / f"{CHECK_DIFF.stem}_no_hunk1.diff"
        trimmed.parent.mkdir(exist_ok=True)
        trimmed.write_text(without_first_hunk(CHECK_DIFF.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"  applying {CHECK_DIFF.name} without its first hunk")
        apply_patch(tree, trimmed)
    else:
        print("  rules: round four (unchanged)")
    write_origin(tree, name, spec)


def write_origin(tree, name, spec):
    git = lambda *args: subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout
    head = git("rev-parse", "HEAD").strip()
    dirty = len(git("status", "--short").splitlines())
    changes = ["grid pinned: SVC_GRID C in (0.3,), RULE_WEIGHTS (1.0,)"]
    changes.append("data: " + ("six-source files from backup_round4/data/" if spec["data"] == "round4"
                               else "nine-source files (live data/)"))
    changes.append("rules: " + ("round four + report/round_five_rules.diff (+ check_rules sentences)" if spec["rules"]
                                else "round four, unchanged"))
    for rel, source in spec["extra_files"].items():
        changes.append(f"extra training file: {rel} (from {source}, md5 {md5(source)})")
    lines = [f"tree {name}", f"created {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
             f"copied from the live working tree at HEAD {head} ({dirty} uncommitted entries in git status)",
             "changes relative to the live tree:"] + [f"  - {c}" for c in changes] + ["md5 (tree / live):"]
    for rel in RECORDED + list(spec["extra_files"]):
        live = ROOT / rel
        lines.append(f"  {rel}: {md5(tree / rel)} / {md5(live) if live.exists() else 'absent'}")
    (tree / "ORIGIN.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def tree_diff(tree):
    """Files in the tree whose bytes differ from the live counterpart (or that the live tree lacks)."""
    differing = set()
    for path in tree.rglob("*"):
        if path.is_symlink() or path.is_dir():
            continue
        rel = path.relative_to(tree)
        if rel.parts[0] in {"report", "ORIGIN.txt"} or rel.parts[0].startswith("DONE_"):
            continue
        if "__pycache__" in rel.parts or rel.suffix == ".pyc":   # created by the in-tree checks and runs
            continue
        live = ROOT / rel
        if not live.exists() or live.read_bytes() != path.read_bytes():
            differing.add(str(rel))
    return differing


def run_in(tree, code, timeout=1800):
    return subprocess.run([str(PY), "-c", code], cwd=tree, capture_output=True, text=True, timeout=timeout)


def check(name, spec, quick):
    tree = RUNS / name
    print(f"\n=== checking {name} ===")
    results = []

    def record(label, ok, detail=""):
        results.append(ok)
        print(f"  [{'OK ' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))

    record("tree exists", tree.is_dir(), str(tree))
    if not tree.is_dir():
        return False
    for sub in ("cache", "raw"):
        link = tree / "data" / sub
        record(f"data/{sub} symlink resolves to the live folder",
               link.is_symlink() and os.path.realpath(link) == os.path.realpath(ROOT / "data" / sub),
               os.readlink(link) if link.is_symlink() else "not a symlink")
    record("live pickle and candidates absent in the tree",
           not (tree / "src" / "models" / "injection_model.pkl").exists()
           and not (tree / "src" / "models" / "candidates").exists())
    report_files = [p.name for p in (tree / "report").iterdir()] if (tree / "report").is_dir() else None
    record("report/ holds no run output yet", report_files is not None and not any(
        n in {"metrics.json", "train_log.txt"} for n in report_files), ", ".join(report_files or []) or "empty")

    result = run_in(tree, "import json; from src.train import param_grid; import src.gate; "
                          "print(json.dumps(param_grid('emb+rules20')))")
    grid_ok = result.returncode == 0 and result.stdout.strip() == json.dumps(PINNED_GRID)
    record("imports and pinned grid", grid_ok, result.stdout.strip() or result.stderr.strip()[-300:])

    rules_text = (tree / "src" / "rules.py").read_text(encoding="utf-8")
    hits = sum(1 for line in rules_text.splitlines() if "MASS_MESSAGE_RE" in line)
    record("rules.py matches the spec", hits == (2 if spec["rules"] else 0), f"{hits} MASS_MESSAGE_RE lines")
    check_text = (tree / "scripts" / "check_rules.py").read_text(encoding="utf-8")
    has_sentences = "truncate the events and metrics tables" in check_text
    record("check_rules.py matches the spec", has_sentences == spec["rules"])

    source = BACKUP if spec["data"] == "round4" else ROOT
    same = all((tree / "data" / c).read_bytes() == (source / "data" / c).read_bytes()
               for c in ("new_train.csv", "new_test.csv"))
    record(f"new_train.csv / new_test.csv equal {source.name}'s", same)
    for rel, src in spec["extra_files"].items():
        record(f"{rel} equals the staged file", (tree / rel).exists() and (tree / rel).read_bytes() == src.read_bytes())

    differing = tree_diff(tree)
    record("file-level diff against the live tree is exactly the intended set",
           differing == expected_diff(spec), ", ".join(sorted(differing)) or "none")

    if not quick:
        started = time.time()
        result = run_in(tree, "from src.dataset import load_pool; p = load_pool(); print('ROWS', len(p)); "
                              "print(p.groupby('source').size().to_string())")
        rows = -1
        if result.returncode == 0:
            rows = int(next(line for line in result.stdout.splitlines() if line.startswith("ROWS ")).split()[1])
        expected = expected_pool(spec)
        record(f"load_pool() rows ({time.time() - started:.0f} s)", result.returncode == 0 and abs(rows - expected) <= 25,
               f"{rows} rows, expected about {expected}" if result.returncode == 0 else result.stderr.strip()[-300:])
        if result.returncode == 0:
            lines = result.stdout.strip().splitlines()
            for line in lines[lines.index(next(l for l in lines if l.startswith("ROWS "))) + 1:]:
                print(f"        {line}")
        started = time.time()
        args = [str(PY), "scripts/check_rules.py"] + ([] if spec["rules"] else ["--examples"])
        result = subprocess.run(args, cwd=tree, capture_output=True, text=True, timeout=1800)
        record(f"scripts/check_rules.py {'full' if spec['rules'] else '--examples'} ({time.time() - started:.0f} s)",
               result.returncode == 0)
        for line in (result.stdout.strip().splitlines() or result.stderr.strip().splitlines())[-8:]:
            print(f"        {line}")

    status = subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True).stdout
    record("git status shows no rounds/ entry", "rounds/" not in status)
    return all(results)


def smoke(name):
    tree = RUNS / name
    log = tree / "report" / "smoke_log.txt"
    print(f"\n=== smoke run in {name} (log: {log}) ===")
    started = time.time()
    with log.open("w") as handle:
        result = subprocess.run([str(PY), "-u", "-m", "src.train", "--smoke"], cwd=tree, stdout=handle,
                                stderr=subprocess.STDOUT, text=True)
    text = log.read_text(encoding="utf-8")
    saved = text.count("saved candidate ")
    ok = result.returncode == 0 and saved == 2
    print(f"  [{'OK ' if ok else 'FAIL'}] rc={result.returncode}, {saved} candidates saved, {time.time() - started:.0f} s")
    for line in text.strip().splitlines()[-6:]:
        print(f"        {line}")
    return ok


def main():
    global RUNS
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--round", type=int, default=7, choices=sorted(TREES_BY_ROUND))
    parser.add_argument("--only", help="comma-separated tree names")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--quick", action="store_true", help="skip load_pool and the rule self-check")
    parser.add_argument("--smoke", help="run `python -m src.train --smoke` in this tree after the checks")
    args = parser.parse_args()
    RUNS = ROOT / "rounds" / f"round{args.round}"
    trees = TREES_BY_ROUND[args.round]
    names = args.only.split(",") if args.only else list(trees)
    for name in names:
        if name not in trees:
            sys.exit(f"unknown tree {name}; choose from {list(trees)}")
    if not RULES_DIFF.exists() or not CHECK_DIFF.exists():
        sys.exit("the round-five rule diffs are missing from report/")
    if not args.check_only:
        for name in names:
            build(name, trees[name])
    ok = all([check(name, trees[name], args.quick) for name in names])
    if args.smoke:
        ok = smoke(args.smoke) and ok
    print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
