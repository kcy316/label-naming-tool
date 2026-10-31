"""
라벨 작업용 이미지 이름 변경 도구.

분할 이미지 폴더(기본 output/splits)의 이미지를 `{class_name}_{번호}.png` 로 바꾸고, 클래스별 번호와 이력을 관리한다.

파일 구성 (모두 이 폴더 안):
    classes.csv  클래스 장부. 한글명, class_name, keyword, start(다음 번호), limit
    history.csv  작업 이력. 한 줄 = 한 번 작업 x 한 클래스 (보충 / 되돌림)
    status.csv   --status 로 만드는 클래스별 현황 (관리표 업데이트용)
    logs/        작업별 파일 매핑 {작업ID}.csv (되돌리기용)

classes.csv 열:
    keyword : 원본 파일명(프롬프트)에 들어 있는 문자열. 비어 있으면 그 클래스는 건너뜀
    start   : 다음에 붙일 번호. --apply 후 자동으로 (마지막 번호 + 1) 로 갱신
    limit   : 최대 변경 장수 (비우면 전부). 초과분은 이름을 바꾸지 않고 남겨 둠

번호 순서: 그리드 생성 시각(--grid-dir 원본 기준) -> 그리드 번호 -> 행 -> 열

사용법:
    python rename.py                       # 미리보기
    python rename.py --apply               # 적용
    python rename.py --status              # 클래스별 현황 + status.csv
    python rename.py --undo 20261030_100012           # 되돌리기 미리보기
    python rename.py --undo 20261030_100012 --apply   # 되돌리기
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
SPLIT_DIR = Path("output/splits")  # 기본값. 실행 위치 기준
GRID_DIR = Path("output/grids")

CLASSES_CSV = TOOL_DIR / "classes.csv"
HISTORY_CSV = TOOL_DIR / "history.csv"
STATUS_CSV = TOOL_DIR / "status.csv"
LOG_DIR = TOOL_DIR / "logs"

HISTORY_FIELDS = ["작업ID", "날짜", "작업유형", "한글명", "class_name", "시작번호", "끝번호", "장수", "다음번호", "비고"]
IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
DIGITS = 4
_SPLIT_RE = re.compile(r"^(?P<grid>.+_grid_(?P<num>\d+))_r(?P<row>\d+)_c(?P<col>\d+)$")
_UNDO_RE = re.compile(r"되돌림: (\d{8}_\d{6})")


# ---------------------------------------------------------------- csv helpers

def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    if not path.exists():
        return [], []
    with open(path, encoding="utf-8-sig", newline="") as f:  # utf-8-sig: 엑셀 저장 BOM 처리
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def append_history(rows: list[dict]) -> None:
    _, old = read_csv(HISTORY_CSV)
    write_csv(HISTORY_CSV, HISTORY_FIELDS, old + rows)


def fmt(cls: str, no: int) -> str:
    return f"{cls}_{no:0{DIGITS}d}"


# ---------------------------------------------------------------- rename

def load_rules(rows: list[dict]) -> list[dict]:
    rules = []
    for row in rows:
        keyword = (row.get("keyword") or "").strip()
        if not keyword or keyword.startswith("#"):
            continue
        limit = (row.get("limit") or "").strip()
        rules.append({
            "row": row,
            "keyword": keyword,
            "class_name": row["class_name"].strip(),
            "ko": row.get("한글명", ""),
            "start": int(row["start"]),
            "limit": int(limit) if limit else None,
        })
    return rules


def sort_key(path: Path, grid_dir: Path):
    m = _SPLIT_RE.match(path.stem)
    if not m:
        return (float("inf"), path.name, 0, 0)
    grid_file = grid_dir / f"{m.group('grid')}{path.suffix}"
    created = (grid_file if grid_file.exists() else path).stat().st_mtime
    return (created, int(m.group("num")), int(m.group("row")), int(m.group("col")))


def build_plan(split_dir: Path, grid_dir: Path, rules: list[dict]):
    """Returns (plan, leftovers, problems, unmatched). plan = [(old_path, new_path, rule)]"""
    matched = defaultdict(list)
    problems = []
    unmatched = defaultdict(int)  # 어떤 keyword 에도 안 걸린 원본 분할 파일 (프롬프트별 개수)

    for path in split_dir.iterdir():
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        hits = [r for r in rules if r["keyword"] in path.name]
        if len(hits) == 1:
            matched[id(hits[0])].append(path)
        elif len(hits) > 1:
            names = ", ".join(f"'{r['keyword']}'" for r in hits)
            problems.append(f"여러 keyword 에 매칭됨 ({names}): {path.name}")
        elif m := _SPLIT_RE.match(path.stem):
            unmatched[m.group("grid").rsplit("_grid_", 1)[0]] += 1

    plan, leftovers = [], []
    for rule in rules:
        files = sorted(matched.get(id(rule), []), key=lambda p: sort_key(p, grid_dir))
        take = files if rule["limit"] is None else files[: rule["limit"]]
        leftovers += [(p, rule) for p in files[len(take):]]
        for offset, path in enumerate(take):
            plan.append((path, path.with_name(fmt(rule["class_name"], rule["start"] + offset) + path.suffix.lower()), rule))
        rule["found"] = len(files)
        rule["renamed"] = len(take)

    targets = defaultdict(list)
    for old, new, _ in plan:
        targets[new.name].append(old)
        if new.exists() and new != old:
            problems.append(f"대상 파일이 이미 존재: {new.name}")
    problems += [f"같은 이름으로 중복 변경: {name}" for name, olds in targets.items() if len(olds) > 1]
    return plan, leftovers, problems, unmatched


def print_plan(rules, leftovers, unmatched) -> None:
    print(f"{'한글명':10s}{'class_name':22s}{'found':>6s}{'rename':>8s}{'left':>6s}  range")
    for r in rules:
        if not r["found"]:
            continue
        rng = f"{fmt(r['class_name'], r['start'])} ~ {fmt(r['class_name'], r['start'] + r['renamed'] - 1)}" if r["renamed"] else "-"
        print(f"{r['ko']:10s}{r['class_name']:22s}{r['found']:6d}{r['renamed']:8d}{r['found'] - r['renamed']:6d}  {rng}")
    print(f"{'TOTAL':32s}{sum(r['found'] for r in rules):6d}{sum(r['renamed'] for r in rules):8d}{len(leftovers):6d}")

    if leftovers:
        print("\n[LEFT] limit 초과로 이름을 바꾸지 않는 파일 (그리드 단위):")
        by_grid = defaultdict(int)
        for p, r in leftovers:
            m = _SPLIT_RE.match(p.stem)
            by_grid[(r["class_name"], f"grid_{m.group('num')}" if m else p.name)] += 1
        for (cls, grid), n in by_grid.items():
            print(f"  {cls}: {grid} ({n}장)")

    if unmatched:
        print(f"\n[WARN] keyword 가 없어 건너뛰는 파일 {sum(unmatched.values())}장 — classes.csv 에 keyword 를 추가하세요:")
        for prompt, n in sorted(unmatched.items()):
            print(f"  {n:5d}장  {prompt[:100]}")


def cmd_rename(split_dir: Path, grid_dir: Path, apply: bool) -> None:
    if not split_dir.is_dir():
        sys.exit(f"[ERROR] 폴더가 없습니다: {split_dir}  (--dir 로 지정하세요)")
    fieldnames, rows = read_csv(CLASSES_CSV)
    rules = load_rules(rows)
    plan, leftovers, problems, unmatched = build_plan(split_dir, grid_dir, rules)
    print_plan(rules, leftovers, unmatched)

    if problems:
        print(f"\n[ERROR] 문제 {len(problems)}건 — classes.csv 의 keyword 를 고친 뒤 다시 실행하세요:")
        for p in problems[:20]:
            print(f"  {p}")
        sys.exit(1)
    if not plan:
        print("\n이름을 바꿀 파일이 없습니다.")
        return
    if not apply:
        print("\n미리보기입니다. 실제로 변경하려면 --apply 를 붙이세요.")
        return

    now = datetime.now()
    job = f"{now:%Y%m%d_%H%M%S}"
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{job}.csv"
    write_csv(log_path, ["class_name", "old_name", "new_name"],  # 변경 전에 로그부터 저장
              [{"class_name": r["class_name"], "old_name": o.name, "new_name": n.name} for o, n, r in plan])
    for old, new, _ in plan:
        old.rename(new)

    history = []
    for r in rules:
        if not r["renamed"]:
            continue
        first, last = r["start"], r["start"] + r["renamed"] - 1
        r["row"]["start"] = str(last + 1)
        history.append({"작업ID": job, "날짜": f"{now:%Y-%m-%d}", "작업유형": "보충", "한글명": r["ko"],
                        "class_name": r["class_name"], "시작번호": first, "끝번호": last,
                        "장수": r["renamed"], "다음번호": last + 1, "비고": ""})
    write_csv(CLASSES_CSV, fieldnames, rows)
    append_history(history)

    print(f"\n[DONE] {len(plan)}장 이름 변경. 작업ID: {job}")
    print("  classes.csv start 갱신, history.csv 기록, logs/ 저장 완료")
    print(f"  되돌리기: python rename.py --undo {job} --apply")


# ---------------------------------------------------------------- undo

def cmd_undo(job: str, split_dir: Path, apply: bool) -> None:
    log_path = LOG_DIR / f"{job}.csv"
    if not log_path.exists():
        sys.exit(f"[ERROR] 로그가 없습니다: {log_path}")
    _, history = read_csv(HISTORY_CSV)
    if any(_UNDO_RE.search(h["비고"]) and _UNDO_RE.search(h["비고"]).group(1) == job for h in history):
        sys.exit(f"[ERROR] 작업 {job} 은 이미 되돌렸습니다.")

    _, log = read_csv(log_path)
    todo = [r for r in log if (split_dir / r["new_name"]).exists()]
    if len(todo) < len(log):
        print(f"[WARN] {len(log) - len(todo)}장은 폴더에 없어 건너뜀 (S3로 옮겼거나 이미 이동됨)")

    # 클래스별 이 작업의 번호 범위
    ranges = {}
    for r in todo:
        no = int(r["new_name"].rsplit("_", 1)[1].split(".")[0])
        lo, hi, n = ranges.get(r["class_name"], (no, no, 0))
        ranges[r["class_name"]] = (min(lo, no), max(hi, no), n + 1)

    fieldnames, rows = read_csv(CLASSES_CSV)
    by_cls = {row["class_name"]: row for row in rows}
    print(f"[UNDO] 작업 {job}: {len(todo)}장을 원래 이름으로 되돌립니다.")
    restore = {}
    for cls, (lo, hi, n) in ranges.items():
        cur = int(by_cls[cls]["start"])
        if cur == hi + 1:
            restore[cls] = lo
            print(f"  {cls:22s} {n:4d}장  장부 start {cur} -> {lo}")
        else:
            print(f"  {cls:22s} {n:4d}장  장부 start {cur} 유지 (이후 다른 작업이 있어 자동으로 되돌리지 않음)")

    if not apply:
        print("미리보기입니다. 실제로 되돌리려면 --apply 를 붙이세요.")
        return

    for r in todo:
        (split_dir / r["new_name"]).rename(split_dir / r["old_name"])
    for cls, lo in restore.items():
        by_cls[cls]["start"] = str(lo)
    write_csv(CLASSES_CSV, fieldnames, rows)

    now = datetime.now()
    append_history([{"작업ID": f"{now:%Y%m%d_%H%M%S}", "날짜": f"{now:%Y-%m-%d}", "작업유형": "되돌림",
                     "한글명": by_cls[cls].get("한글명", ""), "class_name": cls, "시작번호": lo, "끝번호": hi,
                     "장수": n, "다음번호": by_cls[cls]["start"], "비고": f"되돌림: {job}"}
                    for cls, (lo, hi, n) in ranges.items()])
    print("[DONE] 되돌리기 완료 (history.csv 에 기록)")


# ---------------------------------------------------------------- status

def cmd_status() -> None:
    _, classes = read_csv(CLASSES_CSV)
    _, history = read_csv(HISTORY_CSV)
    undone = {m.group(1) for h in history if (m := _UNDO_RE.search(h["비고"]))}

    agg = {}
    for h in history:
        if h["작업유형"] != "보충" or h["작업ID"] in undone:
            continue
        a = agg.setdefault(h["class_name"], {"first": int(h["시작번호"]), "total": 0, "jobs": 0, "last_date": ""})
        a["first"] = min(a["first"], int(h["시작번호"]))
        a["total"] += int(h["장수"])
        a["jobs"] += 1
        a["last_date"] = max(a["last_date"], h["날짜"])

    out = []
    for c in classes:
        a = agg.get(c["class_name"])
        if not a:
            continue
        nxt = int(c["start"])
        ok = a["first"] + a["total"] == nxt
        out.append({"한글명": c["한글명"], "class_name": c["class_name"], "첫 보충 시작번호": a["first"],
                    "누적 보충 장수": a["total"], "다음 시작번호": nxt, "보충 횟수": a["jobs"],
                    "마지막 보충일": a["last_date"], "관리표 표기": f"{a['total']}장 보충 완료",
                    "확인": "" if ok else "⚠ 번호 불일치"})
    write_csv(STATUS_CSV, list(out[0].keys()) if out else ["한글명"], out)

    print(f"{'한글명':10s}{'class_name':22s}{'첫 시작':>7s}{'누적':>6s}{'다음':>7s}{'횟수':>5s}  마지막 보충일")
    for o in out:
        print(f"{o['한글명']:10s}{o['class_name']:22s}{o['첫 보충 시작번호']:7d}{o['누적 보충 장수']:6d}"
              f"{o['다음 시작번호']:7d}{o['보충 횟수']:5d}  {o['마지막 보충일']}  {o['확인']}")
    print(f"\n보충한 클래스 {len(out)}개, 누적 {sum(o['누적 보충 장수'] for o in out)}장. 저장: {STATUS_CSV.name}")


def main():
    parser = argparse.ArgumentParser(description="라벨 작업용 이미지 이름 변경 + 번호/이력 관리")
    parser.add_argument("--apply", action="store_true", help="실제로 변경 (없으면 미리보기)")
    parser.add_argument("--undo", metavar="작업ID", help="해당 작업 되돌리기 (예: 20261030_100012)")
    parser.add_argument("--status", action="store_true", help="클래스별 누적 현황 출력 + status.csv 저장")
    parser.add_argument("--dir", type=Path, default=SPLIT_DIR, help="대상 폴더 (기본: output/splits)")
    parser.add_argument("--grid-dir", type=Path, default=GRID_DIR, help="분할 전 그리드 원본 폴더, 번호 순서용 (기본: output/grids)")
    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.undo:
        cmd_undo(args.undo, args.dir, args.apply)
    else:
        cmd_rename(args.dir, args.grid_dir, args.apply)


if __name__ == "__main__":
    main()
