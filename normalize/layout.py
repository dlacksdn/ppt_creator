#!/usr/bin/env python
# 사용법:
#   /home/dlacksdn/ppt_creator/.venv/bin/python normalize/layout.py IN.json --mode b1 -o OUT.json \
#       [--golden FULL.json --report] [--row-tol N] [--col-tol N] [--size-tol F] [--grid N] \
#       [--visual-tol N] [--move-tol N]
#
#   - IN.json     : 정규화할 IR (ir/schema.md v0.1, 등방 좌표계: 장축 0~1000 정수)
#   - --mode      : b1(스냅+행/열 클러스터 정렬+role·크기 클러스터 크기통일) | b2(8‰ 격자 스냅만)
#   - -o OUT.json : 정규화 결과 저장. 파일이 이미 있으면 덮어쓰지 않고 -1, -2 … suffix 자동 부여
#   - --golden FULL.json --report : 전체 골든 IR(intent_row/intent_col/size_class 라벨 포함) 대비
#       미교정/과교정 카운트를 JSON으로 stdout에 출력 (count_corrections)
"""
IR 레이아웃 정규화 프로토타입 (M0b — 계획 §4, B1/B2 A/B의 B측 구현).

공개 API
--------
- normalize(ir, mode="b1", params=None) -> dict
    원본 불변(깊은 복사), bbox만 조정.
    · mode "b2": 8‰ 격자 스냅만 (nodes·containers·annotations 전부).
    · mode "b1": ① 8‰ 격자 스냅 → ② 행/열 클러스터 정렬 → ③ role·크기 클러스터 기반
      크기통일 → ④ 컨테이너 자식 포함 보정.
      - 클러스터 그룹은 **스냅 전 원본 중심** 기준으로 결정한다 (스냅이 tol보다 굵은 8‰
        격자라 스냅 후 좌표로 묶으면 경계에서 그룹이 인위적으로 쪼개지는 것을 방지).
      - 행/열 정렬 목표 중심 = 그룹 원본 중심들의 중앙값을 격자에 스냅한 값.
      - 크기통일 = 같은 role이면서 w·h가 **상호(모든 쌍)** size_unify_tol(기본 10%) 이내인
        클러스터를 중앙값 (w,h)로 통일 (중심 고정 재배치 → 정렬 결과 보존).
      - 노드와 컨테이너는 **별도 모집단**으로 각각 클러스터링한다 (크기 스케일이 달라
        y/x중심 우연 일치 시 서로 끌어당기는 오염 방지). annotations는 스냅만.
      - 교차 모집단 화해: 컨테이너 '싱글턴' 그룹은 원본 중심 기준 min(tol, grid_step)
        이내의 노드 정렬선(크기 ≥2 노드 그룹의 스냅 타깃)이 있으면 그 타깃으로 스냅
        — 노드만 움직이는 별도 모집단 정렬이 원래 맞던 노드↔컨테이너 정렬을
        격자폭만큼 깨뜨리는 회귀 방지. 이동량 ≤ grid(8‰) 유계.
    · params 기본값: row_align_tol = col_align_tol = max(6‰, 0.30×노드 높이 중앙값),
      size_unify_tol = 0.10, grid_step = 8. params dict의 동명 키로 개별 재정의 가능.
    · 컨테이너 bbox는 정규화 후에도 직속 자식(children)을 포함하도록 최소 확장한다
      (깊은 컨테이너부터 후위 처리 → 부모가 확장된 자식을 반영).

- cluster_rows_cols(boxes, row_tol, col_tol) -> (row_groups, col_groups)
    boxes = [(id, [x,y,w,h]), ...]. 1D 클러스터링: y중심(행)/x중심(열)을 정렬한 뒤
    인접 값 차이 > tol이면 분할. 반환은 id 리스트의 리스트(싱글턴 포함).
    noise_sweep 유틸이 이 함수를 import한다.

- count_corrections(golden_full_ir, normalized_ir, visual_tol=6, move_tol=12) -> dict
    **intent 라벨 기준** 판정 (임계값 상대 정의 아님) — 정규화가 아무것도 안 건드렸어도
    의도 정렬이 어긋나 있으면 미교정으로 잡힌다.
    · 미교정: 골든에서 같은 intent_row(또는 intent_col) 라벨을 가진 원소 쌍인데,
      정규화 결과에서 y중심(행)/x중심(열) 편차 > visual_tol(‰)인 쌍 수.
    · 과교정: intent 그룹이 아닌데 골든 원좌표 대비 move_tol(‰) 초과 이동한 박스
      수 + id 목록. 축별 판정: intent_row 없음(=행 정렬 의도 없음)인데 |Δy중심| > move_tol,
      또는 intent_col 없음인데 |Δx중심| > move_tol 이면 과교정. (행 그룹 소속 박스의
      세로 이동은 의도된 교정이므로 면책, 무의도 축의 큰 이동만 벌점.)
    · size_report(보조 지표): 같은 size_class인데 정규화 후 |Δw| 또는 |Δh| > visual_tol인
      쌍 수, size_class 없음(null)인데 골든 대비 크기가 move_tol 초과 변한 박스 id.
    · 매칭은 id 기준 (양쪽에 모두 존재하는 nodes·containers만 평가).

    반환 dict 구조:
    {
      "params": {"visual_tol":…, "move_tol":…},
      "uncorrected": {"row_pairs":n, "col_pairs":n, "total_pairs":n,
                      "pairs":[{"axis","group","ids":[a,b],"dev":‰}, …]},
      "overcorrected": {"count":n, "ids":[…],
                        "boxes":[{"id","dcx","dcy","axes":["x"|"y",…]}, …]},
      "size_report": {"uncorrected_pairs":n,
                      "pairs":[{"group","ids":[a,b],"dw","dh"}, …],
                      "overcorrected_count":n, "overcorrected_ids":[…]}
    }

좌표 규약: ir/schema.md의 등방 정규화 정수(장축 0~1000, 1‰ = 두 축 동일 물리 길이).
모든 편차·이동·tol은 ‰ 단위이며 x·y가 단일 척도라 2D 비교가 유효하다.
"""

import argparse
import copy
import json
import os
import sys
from collections import defaultdict
from statistics import median

# ---------------------------------------------------------------- 내부 유틸


def _snap_val(v, step):
    """값 v를 step 배수 격자에 스냅 (가장 가까운 배수, 정수 반환)."""
    return int(round(v / step)) * step


def _snap_bbox(bbox, step):
    """bbox [x,y,w,h]를 격자 스냅. w·h는 최소 step 보장(0 붕괴 방지)."""
    x, y, w, h = bbox
    return [
        _snap_val(x, step),
        _snap_val(y, step),
        max(step, _snap_val(w, step)),
        max(step, _snap_val(h, step)),
    ]


def _center(bbox):
    """bbox 중심 (cx, cy) — float."""
    x, y, w, h = bbox
    return (x + w / 2.0, y + h / 2.0)


def _cluster_1d(id_vals, tol):
    """1D 클러스터링: (id, 값) 목록을 값 순 정렬 후 인접 차이 > tol이면 분할.

    반환: id 리스트의 리스트 (싱글턴 포함). tol은 '인접 값 간격' 기준이므로
    그룹 내 최원거리 쌍은 tol을 넘을 수 있다(체인 연결) — 프로토타입 단순화.
    """
    if not id_vals:
        return []
    s = sorted(id_vals, key=lambda t: (t[1], t[0]))
    groups = [[s[0][0]]]
    prev = s[0][1]
    for bid, v in s[1:]:
        if v - prev > tol:
            groups.append([bid])
        else:
            groups[-1].append(bid)
        prev = v
    return groups


def _rel_close(a, b, tol):
    """상대 크기 근접 판정: |a-b| <= tol × max(a,b) (대칭·보수적)."""
    return abs(a - b) <= tol * max(a, b)


def _size_clusters(items, tol):
    """같은 role 내 (id, w, h) 목록을 '상호 tol 이내' 클러스터로 묶는다.

    그리디: 면적·id 순으로 순회하며, 기존 클러스터의 **모든** 멤버와 w·h가
    상호 tol 이내일 때만 편입(쌍별 상호 조건 충족). 아니면 새 클러스터.
    정렬 선행으로 결정론적.
    """
    clusters = []
    for bid, w, h in sorted(items, key=lambda t: (t[1] * t[2], t[0])):
        placed = False
        for cl in clusters:
            if all(
                _rel_close(w, w2, tol) and _rel_close(h, h2, tol)
                for _, w2, h2 in cl
            ):
                cl.append((bid, w, h))
                placed = True
                break
        if not placed:
            clusters.append([(bid, w, h)])
    return clusters


def _container_postorder(containers):
    """컨테이너를 자식→부모(후위) 순으로 나열. 순환·미존재 id는 방어적으로 무시."""
    by_id = {c["id"]: c for c in containers}
    order, done, in_stack = [], set(), set()

    def visit(cid):
        if cid in done or cid in in_stack:
            return
        in_stack.add(cid)
        for ch in by_id[cid].get("children", []):
            if ch in by_id:
                visit(ch)
        in_stack.discard(cid)
        done.add(cid)
        order.append(by_id[cid])

    for c in containers:
        visit(c["id"])
    return order


def _expand_containers(ir):
    """각 컨테이너 bbox를 직속 자식들을 포함하도록 최소 확장 (제자리 수정).

    깊은 컨테이너부터 후위 처리해 부모가 확장된 자식 bbox를 반영한다.
    자식이 이동/확대되어 삐져나온 만큼만 늘리며, 여백 추가는 없다(최소 확장).
    """
    containers = ir.get("containers", [])
    if not containers:
        return
    bbox_of = {n["id"]: n["bbox"] for n in ir.get("nodes", [])}
    bbox_of.update({c["id"]: c["bbox"] for c in containers})
    for c in _container_postorder(containers):
        x, y, w, h = c["bbox"]
        x2, y2 = x + w, y + h
        for ch in c.get("children", []):
            cb = bbox_of.get(ch)
            if cb is None:
                continue
            x, y = min(x, cb[0]), min(y, cb[1])
            x2, y2 = max(x2, cb[0] + cb[2]), max(y2, cb[1] + cb[3])
        c["bbox"] = [int(x), int(y), int(x2 - x), int(y2 - y)]
        bbox_of[c["id"]] = c["bbox"]


# ---------------------------------------------------------------- 공개 API


def cluster_rows_cols(boxes, row_tol, col_tol):
    """행/열 1D 클러스터링.

    Args:
        boxes: [(id, [x,y,w,h]), ...]
        row_tol: y중심 인접 차이 분할 임계 (‰)
        col_tol: x중심 인접 차이 분할 임계 (‰)
    Returns:
        (row_groups, col_groups) — 각각 id 리스트의 리스트 (싱글턴 포함).
    """
    rows = _cluster_1d([(bid, _center(bb)[1]) for bid, bb in boxes], row_tol)
    cols = _cluster_1d([(bid, _center(bb)[0]) for bid, bb in boxes], col_tol)
    return rows, cols


def normalize(ir, mode="b1", params=None):
    """IR 레이아웃 정규화 (원본 불변 — 깊은 복사 후 bbox만 조정).

    Args:
        ir: IR dict (ir/schema.md v0.1)
        mode: "b1"(스냅+클러스터 정렬+크기통일) | "b2"(8‰ 격자 스냅만)
        params: {"row_align_tol", "col_align_tol", "size_unify_tol", "grid_step"} 재정의
    Returns:
        정규화된 IR dict (새 객체). bbox 외 필드는 그대로 보존.
    """
    if mode not in ("b1", "b2"):
        raise ValueError(f"mode는 'b1' 또는 'b2'여야 함: {mode!r}")
    out = copy.deepcopy(ir)
    p = dict(params or {})
    grid = int(p.get("grid_step", 8))

    nodes = out.get("nodes", [])
    containers = out.get("containers", [])
    annotations = [a for a in out.get("annotations", []) if "bbox" in a]

    # tol 기본값: 노드 높이 중앙값 기준 (노드 없으면 컨테이너, 둘 다 없으면 6‰)
    heights = [n["bbox"][3] for n in nodes] or [c["bbox"][3] for c in containers]
    default_tol = max(6.0, 0.30 * median(heights)) if heights else 6.0
    row_tol = float(p.get("row_align_tol", default_tol))
    col_tol = float(p.get("col_align_tol", default_tol))
    size_tol = float(p.get("size_unify_tol", 0.10))

    # 클러스터링·크기통일 그룹 결정은 스냅 '전' 원본 좌표 기준 (docstring 참조)
    orig = {el["id"]: list(el["bbox"]) for el in nodes + containers}

    # ① 격자 스냅 (b1·b2 공통)
    for el in nodes + containers + annotations:
        el["bbox"] = _snap_bbox(el["bbox"], grid)

    if mode == "b1":
        # 노드/컨테이너 별도 모집단으로 ②정렬 ③크기통일.
        # 교차 모집단 화해(reconciliation): 노드를 먼저 처리해 노드 그룹(≥2)의
        # 정렬선(원본 중앙값, 스냅 타깃)을 기록하고, 컨테이너 '싱글턴' 그룹이
        # 원본 중심 기준 min(tol, grid) 이내에 노드 정렬선을 두면 그 타깃으로
        # 스냅한다. 근거: 별도 모집단 정렬은 노드만 움직여 "원래 맞던"
        # 노드↔컨테이너 열/행 정렬을 격자폭만큼 깨뜨릴 수 있다 (ex01 ph 열에서
        # 원본 편차 ≤4.5‰ → 정규화 후 8‰ 관측). 화해 이동량은 ≤ grid(8‰)로
        # 유계라 무의도 축 과교정(move_tol=12‰) 신설이 불가능하고, 컨테이너
        # ≥2 그룹(자체 정렬 보유)과 노드 정렬에는 일절 개입하지 않는다.
        node_lines = {1: [], 0: []}  # 축(cidx) → [(원본 중앙값, 스냅 타깃), ...]
        for population, is_container in ((nodes, False), (containers, True)):
            if not population:
                continue
            by_id = {el["id"]: el for el in population}
            boxes = [(el["id"], orig[el["id"]]) for el in population]
            row_groups, col_groups = cluster_rows_cols(boxes, row_tol, col_tol)

            # ② 행/열 정렬: 그룹 목표 중심 = 원본 중심 중앙값의 격자 스냅값
            for cidx, groups, tol in ((1, row_groups, row_tol),
                                      (0, col_groups, col_tol)):
                recon_tol = min(tol, grid)
                for g in groups:
                    med = median(_center(orig[i])[cidx] for i in g)
                    target = _snap_val(med, grid) if len(g) >= 2 else None
                    if is_container and len(g) == 1:
                        near = [(abs(med - m), t) for m, t in node_lines[cidx]
                                if abs(med - m) <= recon_tol]
                        if near:
                            target = min(near)[1]  # 최근접 노드 정렬선으로 화해
                    elif not is_container and target is not None:
                        node_lines[cidx].append((med, target))
                    if target is None:
                        continue
                    for i in g:
                        x, y, w, h = by_id[i]["bbox"]
                        if cidx == 1:
                            by_id[i]["bbox"] = [x, int(round(target - h / 2.0)), w, h]
                        else:
                            by_id[i]["bbox"] = [int(round(target - w / 2.0)), y, w, h]

            # ③ role별 크기통일: 상호 size_tol 이내 클러스터 → 중앙값 (w,h), 중심 고정
            by_role = defaultdict(list)
            for el in population:
                by_role[el.get("role", "unknown")].append(el["id"])
            for ids in by_role.values():
                items = [(i, orig[i][2], orig[i][3]) for i in ids]
                for cl in _size_clusters(items, size_tol):
                    if len(cl) < 2:
                        continue
                    tw = int(round(median(w for _, w, _ in cl)))
                    th = int(round(median(h for _, _, h in cl)))
                    for bid, _, _ in cl:
                        cx, cy = _center(by_id[bid]["bbox"])
                        by_id[bid]["bbox"] = [
                            int(round(cx - tw / 2.0)),
                            int(round(cy - th / 2.0)),
                            tw,
                            th,
                        ]

    # ④ 컨테이너 자식 포함 보정 (b2도 스냅으로 어긋날 수 있으므로 공통 적용)
    _expand_containers(out)
    return out


def count_corrections(golden_full_ir, normalized_ir, visual_tol=6, move_tol=12):
    """intent 라벨 기준 미교정/과교정 카운트 (모듈 docstring의 반환 구조 참조).

    핵심: 판정은 intent_row/intent_col/size_class **라벨** 대비이지 정규화 동작
    대비가 아니다 — 정규화가 안 건드린 박스라도 의도 정렬이 visual_tol을 넘게
    어긋나 있으면 미교정으로 잡힌다.
    """

    def elements(ir):
        return {
            el["id"]: el
            for el in ir.get("nodes", []) + ir.get("containers", [])
        }

    gold = elements(golden_full_ir)
    norm = elements(normalized_ir)
    common = [i for i in gold if i in norm]  # id 매칭 (양쪽 존재만 평가)

    # --- 미교정: 같은 intent 그룹 쌍의 정규화 후 정렬 편차 > visual_tol
    unc_pairs = []
    for axis, field, cidx in (("row", "intent_row", 1), ("col", "intent_col", 0)):
        groups = defaultdict(list)
        for i in common:
            label = gold[i].get(field)
            if label is not None:
                groups[label].append(i)
        for label, ids in sorted(groups.items()):
            ids = sorted(ids)
            for a in range(len(ids)):
                for b in range(a + 1, len(ids)):
                    dev = abs(
                        _center(norm[ids[a]]["bbox"])[cidx]
                        - _center(norm[ids[b]]["bbox"])[cidx]
                    )
                    if dev > visual_tol:
                        unc_pairs.append(
                            {
                                "axis": axis,
                                "group": label,
                                "ids": [ids[a], ids[b]],
                                "dev": round(dev, 2),
                            }
                        )
    row_pairs = sum(1 for q in unc_pairs if q["axis"] == "row")
    col_pairs = len(unc_pairs) - row_pairs

    # --- 과교정: 무의도 축에서 골든 원좌표 대비 move_tol 초과 이동
    over_boxes = []
    for i in sorted(common):
        gcx, gcy = _center(gold[i]["bbox"])
        ncx, ncy = _center(norm[i]["bbox"])
        axes = []
        if gold[i].get("intent_col") is None and abs(ncx - gcx) > move_tol:
            axes.append("x")
        if gold[i].get("intent_row") is None and abs(ncy - gcy) > move_tol:
            axes.append("y")
        if axes:
            over_boxes.append(
                {
                    "id": i,
                    "dcx": round(ncx - gcx, 2),
                    "dcy": round(ncy - gcy, 2),
                    "axes": axes,
                }
            )

    # --- size_report (보조): size_class 그룹 크기 불일치 / 무라벨 크기 변형
    size_groups = defaultdict(list)
    for i in common:
        label = gold[i].get("size_class")
        if label is not None:
            size_groups[label].append(i)
    size_pairs = []
    for label, ids in sorted(size_groups.items()):
        ids = sorted(ids)
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                dw = abs(norm[ids[a]]["bbox"][2] - norm[ids[b]]["bbox"][2])
                dh = abs(norm[ids[a]]["bbox"][3] - norm[ids[b]]["bbox"][3])
                if dw > visual_tol or dh > visual_tol:
                    size_pairs.append(
                        {"group": label, "ids": [ids[a], ids[b]], "dw": dw, "dh": dh}
                    )
    size_over_ids = [
        i
        for i in sorted(common)
        if gold[i].get("size_class") is None
        and (
            abs(norm[i]["bbox"][2] - gold[i]["bbox"][2]) > move_tol
            or abs(norm[i]["bbox"][3] - gold[i]["bbox"][3]) > move_tol
        )
    ]

    return {
        "params": {"visual_tol": visual_tol, "move_tol": move_tol},
        "uncorrected": {
            "row_pairs": row_pairs,
            "col_pairs": col_pairs,
            "total_pairs": len(unc_pairs),
            "pairs": unc_pairs,
        },
        "overcorrected": {
            "count": len(over_boxes),
            "ids": [b["id"] for b in over_boxes],
            "boxes": over_boxes,
        },
        "size_report": {
            "uncorrected_pairs": len(size_pairs),
            "pairs": size_pairs,
            "overcorrected_count": len(size_over_ids),
            "overcorrected_ids": size_over_ids,
        },
    }


# ---------------------------------------------------------------- CLI


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
    ap = argparse.ArgumentParser(
        description="IR 레이아웃 정규화 (b1=클러스터링, b2=격자 스냅만)"
    )
    ap.add_argument("input", help="입력 IR JSON 경로")
    ap.add_argument("--mode", default="b1", choices=["b1", "b2"])
    ap.add_argument("-o", "--output", help="정규화 IR 저장 경로 (기존 파일은 증분 suffix)")
    ap.add_argument("--golden", help="intent 라벨 포함 전체 골든 IR 경로")
    ap.add_argument(
        "--report", action="store_true", help="--golden 대비 미교정/과교정 JSON을 stdout 출력"
    )
    ap.add_argument("--row-tol", type=float, help="row_align_tol 재정의 (‰)")
    ap.add_argument("--col-tol", type=float, help="col_align_tol 재정의 (‰)")
    ap.add_argument("--size-tol", type=float, help="size_unify_tol 재정의 (비율, 기본 0.10)")
    ap.add_argument("--grid", type=int, help="격자 간격 재정의 (‰, 기본 8)")
    ap.add_argument("--visual-tol", type=float, default=6, help="미교정 편차 임계 (‰, 기본 6)")
    ap.add_argument("--move-tol", type=float, default=12, help="과교정 이동 임계 (‰, 기본 12)")
    args = ap.parse_args(argv)

    if args.report and not args.golden:
        ap.error("--report에는 --golden이 필요합니다")

    with open(args.input, encoding="utf-8") as f:
        ir = json.load(f)

    params = {}
    if args.row_tol is not None:
        params["row_align_tol"] = args.row_tol
    if args.col_tol is not None:
        params["col_align_tol"] = args.col_tol
    if args.size_tol is not None:
        params["size_unify_tol"] = args.size_tol
    if args.grid is not None:
        params["grid_step"] = args.grid

    normalized = normalize(ir, mode=args.mode, params=params or None)

    if args.output:
        out_path = _unique_path(args.output)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
        print(f"[normalize] 저장: {out_path}", file=sys.stderr)

    if args.report:
        with open(args.golden, encoding="utf-8") as f:
            golden = json.load(f)
        report = count_corrections(
            golden, normalized, visual_tol=args.visual_tol, move_tol=args.move_tol
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
