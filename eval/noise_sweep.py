#!/usr/bin/env python
# 사용법:
#   /home/dlacksdn/ppt_creator/.venv/bin/python eval/noise_sweep.py \
#       tests/fixtures/example-01.golden.ir.json \
#       tests/fixtures/example-02.golden.ir.json \
#       [-o eval_out/noise-sweep.json] [--sigma-max 30] [--reps 20] [--seed 42] \
#       [--f1-thresh 0.9] [--tol-factor 0.7] [--x-factor 0.5]
#
#   - 입력: intent_row/intent_col 라벨이 붙은 전체 골든 IR 1개 이상
#   - 출력: σ별 pair-level F1 곡선 + 붕괴 σ + 도출 tol·X (JSON, 기존 파일은 -1,-2 증분)
"""행/열 클러스터링 붕괴 오차 측정 (M0b 노이즈 스윕 — 계획 §4).

무엇을 재는가
-------------
전체 골든의 박스 중심에 가우시안 위치 노이즈를 주입한 뒤
normalize.layout.cluster_rows_cols 로 행/열 구조를 복원했을 때,
intent_row/intent_col 라벨 대비 pair-level F1이 σ=1..30‰ 구간에서
언제 무너지는지를 잰다. **F1 < 0.9 로 처음 떨어지는 σ = 붕괴 오차.**

절차 (자기참조 회피 — 도출 순서 고정)
------------------------------------
1. 붕괴 오차 측정: 스윕 중 클러스터링 tol은 normalize의 **형태 기반 기본값**
   max(6‰, 0.30×노드 높이 중앙값)을 쓴다. 이 값은 붕괴 오차와 무관하게
   골든의 박스 크기에서만 나오므로, 도출 대상(붕괴 기반 tol)을 참조하지 않는다.
2. row/col_align_tol = 붕괴 오차 × 0.7 로 고정.
3. 좌표 허용치 X = tol × 0.5.  →  X < tol < 붕괴 오차 위계 보장.

측정 규약
---------
- 노이즈: 박스(노드+컨테이너) 중심 (cx, cy)에 각각 N(0, σ²) 독립 주입,
  w·h 불변. seed 고정(기본 42) → 재현 가능. σ당 반복 기본 20회.
  컨테이너도 intent 라벨을 갖는 골든(ex01)이 있어 노드와 함께 교란한다.
- 클러스터링: normalize와 동일하게 **노드/컨테이너 별도 모집단**으로
  cluster_rows_cols를 호출하고 그룹을 합친다.
- pair-level F1 (축별): 해당 축 intent 라벨이 있는 원소들만 대상으로,
    정답 쌍  = 같은 intent 라벨 && 같은 모집단인 쌍
    예측 쌍  = 복원 클러스터에서 같은 그룹에 든 쌍 (라벨 보유 원소끼리만)
    F1 = 2TP / (2TP + FP + FN)
  · 라벨 없는 원소는 우연 정렬(비의도) 소음이므로 모집단에서 제외 —
    스윕이 재려는 것은 "의도된 구조의 복원력"이다.
  · 모집단이 다른 동일 라벨 쌍(예: 노드와 컨테이너가 같은 intent_col)은
    별도 모집단 클러스터링으로는 원리적으로 예측 불가라 정답 쌍에서 제외.
- 붕괴 판정: σ별 반복 평균의 **행+열 합산(micro) F1**이 threshold(0.9)
  미만이 되는 최초 σ. 스윕 범위 안에서 안 무너지면 null (tol 도출 불가 표기).

출력 JSON 구조
--------------
{
  "params": {...},
  "per_golden": {
    "<경로>": {
      "cluster_tol_used": t, "curve": [{"sigma":s, "f1_row":r, "f1_col":c,
                                        "f1_combined":f}, ...],
      "collapse_sigma": s|null,
      "derived": {"row_col_align_tol": 0.7s, "coord_tol_X": 0.35s} | null
    }, ...
  },
  "recommended": {  # 보수적 채택: 골든들 중 최소 붕괴 σ 기준
    "collapse_sigma": s, "row_col_align_tol": t, "coord_tol_X": x }
}
"""

import argparse
import json
import os
import random
import sys
from statistics import median

# 프로젝트 루트를 sys.path에 추가 (어느 cwd에서 실행해도 normalize import 가능)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from normalize.layout import cluster_rows_cols  # noqa: E402


def _populations(ir):
    """(노드 목록, 컨테이너 목록) — 각 원소는 원본 dict."""
    return ir.get("nodes", []), ir.get("containers", [])


def _default_cluster_tol(ir):
    """normalize와 동일한 형태 기반 기본 tol (자기참조 없는 스윕용 고정값)."""
    nodes, containers = _populations(ir)
    heights = [n["bbox"][3] for n in nodes] or [c["bbox"][3] for c in containers]
    return max(6.0, 0.30 * median(heights)) if heights else 6.0


def _gold_pairs(ir, field):
    """축 field(intent_row|intent_col)의 정답 쌍 집합 + 라벨 보유 id 집합.

    같은 모집단(노드끼리/컨테이너끼리) && 같은 라벨인 쌍만 정답.
    """
    nodes, containers = _populations(ir)
    labeled = set()
    pairs = set()
    for population in (nodes, containers):
        by_label = {}
        for el in population:
            v = el.get(field)
            if v is not None:
                labeled.add(el["id"])
                by_label.setdefault(v, []).append(el["id"])
        for ids in by_label.values():
            ids = sorted(ids)
            for a in range(len(ids)):
                for b in range(a + 1, len(ids)):
                    pairs.add((ids[a], ids[b]))
    return pairs, labeled


def _predicted_pairs(groups, labeled):
    """복원 클러스터 그룹 → 라벨 보유 원소끼리의 예측 쌍 집합."""
    pairs = set()
    for g in groups:
        ids = sorted(i for i in g if i in labeled)
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                pairs.add((ids[a], ids[b]))
    return pairs


def _f1_counts(pred, gold):
    """(TP, FP, FN)."""
    tp = len(pred & gold)
    return tp, len(pred) - tp, len(gold) - tp


def sweep_golden(ir, sigmas, reps, rng, f1_thresh):
    """골든 1개에 대한 σ 스윕. (곡선 목록, 붕괴 σ, 사용한 cluster tol) 반환."""
    nodes, containers = _populations(ir)
    tol = _default_cluster_tol(ir)
    gold_row, labeled_row = _gold_pairs(ir, "intent_row")
    gold_col, labeled_col = _gold_pairs(ir, "intent_col")

    curve = []
    collapse = None
    for sigma in sigmas:
        acc = {"row": [0, 0, 0], "col": [0, 0, 0]}  # [TP, FP, FN] 누적
        for _ in range(reps):
            row_groups, col_groups = [], []
            for population in (nodes, containers):
                if not population:
                    continue
                noisy = []
                for el in population:
                    x, y, w, h = el["bbox"]
                    dx = rng.gauss(0.0, sigma)
                    dy = rng.gauss(0.0, sigma)
                    noisy.append((el["id"], [x + dx, y + dy, w, h]))
                rg, cg = cluster_rows_cols(noisy, tol, tol)
                row_groups.extend(rg)
                col_groups.extend(cg)
            for key, groups, gold, labeled in (
                ("row", row_groups, gold_row, labeled_row),
                ("col", col_groups, gold_col, labeled_col),
            ):
                tp, fp, fn = _f1_counts(_predicted_pairs(groups, labeled), gold)
                acc[key][0] += tp
                acc[key][1] += fp
                acc[key][2] += fn

        def f1_of(tp, fp, fn):
            return 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else None

        f1_row = f1_of(*acc["row"])
        f1_col = f1_of(*acc["col"])
        tp = acc["row"][0] + acc["col"][0]
        fp = acc["row"][1] + acc["col"][1]
        fn = acc["row"][2] + acc["col"][2]
        f1_comb = f1_of(tp, fp, fn)
        curve.append({
            "sigma": sigma,
            "f1_row": round(f1_row, 4) if f1_row is not None else None,
            "f1_col": round(f1_col, 4) if f1_col is not None else None,
            "f1_combined": round(f1_comb, 4) if f1_comb is not None else None,
        })
        if collapse is None and f1_comb is not None and f1_comb < f1_thresh:
            collapse = sigma
    return curve, collapse, tol


def _unique_path(path):
    """이미 존재하는 경로면 -1, -2 … suffix로 증분 (산출물 덮어쓰기 금지 규칙)."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base}-{i}{ext}"):
        i += 1
    return f"{base}-{i}{ext}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="행/열 클러스터링 붕괴 오차 노이즈 스윕")
    ap.add_argument("goldens", nargs="+", help="intent 라벨 포함 전체 골든 IR 경로들")
    ap.add_argument("-o", "--output", default=os.path.join(ROOT, "eval_out", "noise-sweep.json"))
    ap.add_argument("--sigma-max", type=int, default=30)
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--f1-thresh", type=float, default=0.9)
    ap.add_argument("--tol-factor", type=float, default=0.7, help="tol = 붕괴σ × 이 값")
    ap.add_argument("--x-factor", type=float, default=0.5, help="X = tol × 이 값")
    args = ap.parse_args(argv)

    sigmas = list(range(1, args.sigma_max + 1))
    result = {
        "params": {
            "sigma_range": [1, args.sigma_max], "reps": args.reps,
            "seed": args.seed, "f1_thresh": args.f1_thresh,
            "tol_factor": args.tol_factor, "x_factor": args.x_factor,
            "unit": "permille (등방, 장축 0~1000)",
        },
        "per_golden": {},
    }

    collapses = []
    for path in args.goldens:
        with open(path, encoding="utf-8") as f:
            ir = json.load(f)
        rng = random.Random(args.seed)  # 골든마다 동일 시드 → 파일 추가에 불변
        curve, collapse, tol = sweep_golden(ir, sigmas, args.reps, rng, args.f1_thresh)
        derived = None
        if collapse is not None:
            t = collapse * args.tol_factor
            derived = {"row_col_align_tol": round(t, 2),
                       "coord_tol_X": round(t * args.x_factor, 2)}
            collapses.append(collapse)
        result["per_golden"][path] = {
            "cluster_tol_used": round(tol, 2),
            "curve": curve,
            "collapse_sigma": collapse,
            "derived": derived,
        }

    if collapses:
        c = min(collapses)  # 보수적 채택 (가장 먼저 무너지는 골든 기준)
        t = c * args.tol_factor
        result["recommended"] = {
            "collapse_sigma": c,
            "row_col_align_tol": round(t, 2),
            "coord_tol_X": round(t * args.x_factor, 2),
            "hierarchy_note": "X < tol < 붕괴σ",
        }
    else:
        result["recommended"] = None

    out_path = _unique_path(args.output)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[noise_sweep] 저장: {out_path}", file=sys.stderr)

    # 사람용 요약
    for path, r in result["per_golden"].items():
        print(f"{path}: cluster_tol={r['cluster_tol_used']}  "
              f"collapse_sigma={r['collapse_sigma']}  derived={r['derived']}")
    print(f"recommended: {result['recommended']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
