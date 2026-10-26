# -*- coding: utf-8 -*-
"""📚 갤러리 견본 — 엑셀·CSV 정리. 원본은 건드리지 않고 '<이름>_정리.csv' 를 옆에 만든다."""
import csv
import glob
import os
import time

META = {
    "name": "엑셀·CSV 정리",
    "icon": "🧹",
    "desc": "폴더의 CSV·엑셀 파일에서 칸 앞뒤 빈칸·빈 줄·똑같은 줄을 지워 '<이름>_정리.csv' 로 저장한다(원본은 그대로).",
    "keywords": ["엑셀", "csv", "xlsx", "정리", "빈칸", "빈 줄", "중복", "똑같은"],  # 만들기 칸에 적은 말과 맞춰 비슷한 견본으로 띄운다(말 줄기 — 조사·어미가 붙어도 맞게)
    "steps": ["폴더에서 최근 파일 찾기 (pattern · days)", "칸 앞뒤 빈칸·빈 줄 지우기", "똑같은 줄 지우기 (dedupe)", "옆에 _정리.csv 로 저장 → 알림"],
    "kind": "ctx",
    "target": "desktop",
    "motion": "write",
    "params": {"folder": "%USERPROFILE%\\Downloads", "pattern": "*.csv;*.xlsx", "days": 1, "dedupe": "yes"},
    "hint": "folder 에 정리할 폴더를 넣으세요. 🧪 시험은 무엇을 정리할지 세기만 하고 저장하지 않아요. 엑셀(.xlsx)은 openpyxl 이 깔려 있을 때만 읽어요",
    "triggers": [],
    "timeout": 300,
}

SUFFIX = "_정리"


def read_rows(path):
    """파일 → 줄 목록(칸은 글자). CSV 는 UTF-8 → CP949 순서로 읽고, .xlsx 는 openpyxl 로 첫 시트를 읽는다."""
    if path.lower().endswith(".xlsx"):
        try:
            import openpyxl
        except ImportError:
            raise RuntimeError("엑셀 파일을 읽으려면 openpyxl 이 필요합니다 — 엑셀에서 CSV 로 저장하거나 pip install openpyxl")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            return [["" if v is None else str(v) for v in row] for row in wb.worksheets[0].iter_rows(values_only=True)]
        finally:
            wb.close()
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.reader(f))
        except UnicodeDecodeError:
            continue
    raise RuntimeError("글자 인코딩을 알 수 없습니다: %s" % os.path.basename(path))


def tidy(rows, dedupe=True):
    """(정리한 줄, 지운 빈 줄 수, 지운 같은 줄 수)."""
    out, seen, empty, dup = [], set(), 0, 0
    for row in rows:
        row = [c.strip() for c in row]
        while row and not row[-1]:
            row.pop()
        if not any(row):
            empty += 1
            continue
        key = tuple(row)
        if dedupe and key in seen:
            dup += 1
            continue
        seen.add(key)
        out.append(row)
    return out, empty, dup


def targets(folder, pattern, days, now=None):
    now = now or time.time()
    files = set()
    for pat in [p.strip() for p in str(pattern).split(";") if p.strip()]:
        files.update(glob.glob(os.path.join(folder, pat)))
    keep = []
    for p in sorted(files):
        stem = os.path.splitext(os.path.basename(p))[0]
        if stem.endswith(SUFFIX) or os.path.basename(p).startswith("~$"):
            continue
        if days and now - os.path.getmtime(p) > float(days) * 86400:
            continue
        keep.append(p)
    return keep


def run(ctx):
    folder = os.path.expandvars(os.path.expanduser(ctx.param("folder")))
    if not os.path.isdir(folder):
        raise RuntimeError("폴더가 없습니다: %s" % folder)
    try:
        days = float(ctx.params.get("days") or 0)
    except (TypeError, ValueError):
        days = 0
    dedupe = ctx.param("dedupe", "yes").strip().lower() not in ("no", "n", "0", "false", "off", "아니오")
    files = targets(folder, ctx.param("pattern") or "*.csv", days)
    if not files:
        ctx.log("정리할 파일이 없습니다 (%s · %s · 최근 %s일)" % (folder, ctx.param("pattern"), days or "전체"))
        return
    done = []
    for p in files:
        rows, empty, dup = tidy(read_rows(p), dedupe)
        dest = os.path.join(os.path.dirname(p), os.path.splitext(os.path.basename(p))[0] + SUFFIX + ".csv")
        ctx.log("%s — %d줄 남김 · 빈 줄 %d · 같은 줄 %d" % (os.path.basename(p), len(rows), empty, dup))
        if ctx.for_real("%s 저장" % os.path.basename(dest)):
            with open(dest, "w", encoding="utf-8-sig", newline="") as f:      # utf-8-sig — 엑셀이 한글을 바로 읽는다
                csv.writer(f).writerows(rows)
            done.append(os.path.basename(dest))
    if done:
        ctx.notify("🧹 정리 끝", "%d개 — %s" % (len(done), ", ".join(done[:3]) + (" …" if len(done) > 3 else "")))
