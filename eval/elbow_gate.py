#!/usr/bin/env python
# 사용법:
#   /home/dlacksdn/ppt_creator/.venv/bin/python eval/elbow_gate.py \
#       outputs/ex01-golden-b1.routes.json tests/fixtures/example-01.golden.ir.json \
#       [--normalize b1|b2] [-o eval_out/elbow-gate-ex01-golden-b1.json] \
#       [--pen-thresh 0.10] [--cross-thresh 0.15] [--cross-limit 3]
#
#   - ROUTES.json : cli.py render --route-report가 저장한 계획 elbow 폴리라인(‰)
#   - IR.json     : 렌더에 쓴 원본 IR. --normalize를 렌더 때와 동일하게 주면
#                   normalize.layout.normalize(기본 params)를 재적용해 bbox를
#                   라우트 계산 시점과 일치시킨다 (normalize는 결정론적).
"""elbow 라우팅 게이트 (R13) — 박스 관통 · 과다 교차 계측.

판정 대상 (계획 §4 M0b 게이트):
  - 박스 관통 비율 = (끝점 박스가 아닌 노드 bbox '내부'를 지나는 세그먼트를
    1개 이상 가진 엣지 수) / 전체 엣지 수  ≤ pen_thresh(기본 10%)
  - 과다 교차 비율 = (다른 커넥터와 3회 이상 교차하는 커넥터 수) / 전체
    커넥터 수  ≤ cross_thresh(기본 15%)

측정 규약:
  - 장애물 = **노드 bbox만**. 컨테이너는 배경이라 커넥터가 정당하게 위를
    지나가고(관통 아님), 자기 엣지의 from/to 도형은 제외한다 (커넥터 끝점이
    그 도형 경계에 붙어 있으므로).
  - 관통 판정: 계획 폴리라인은 전부 축평행 세그먼트다. 세그먼트가 bbox
    내부(경계 제외, eps=1e-6)와 양(+) 길이로 겹치면 관통. 경계를 스치기만
    하는 접촉(겹침 길이 0)은 관통이 아니다.
  - 교차 판정: 서로 다른 커넥터의 수직↔수평 세그먼트 쌍이 양쪽 모두
    '내부에서'(끝점 제외, strict) 가로지르면 교차 1회. 같은 연결 사이트를
    공유해 끝점이 닿거나 평행 세그먼트가 겹쳐 달리는 경우는 교차로 세지
    않는다 (시각적 겹침이지만 transversal 교차가 아님 — 스텁 근사의 한계로
    docstring에 명시).
  - 계획 폴리라인은 render/connectors.plan_edge의 직교 근사이며 실제
    PowerPoint elbow 재계산 경로와 다를 수 있다 (route-report의 note 참조).

출력 JSON:
{
  "routes_path", "ir_path", "normalize_mode",
  "params": {"pen_thresh", "cross_thresh", "cross_limit"},
  "edges_total": n,
  "penetration": {"edge_count": n, "ratio": r, "pass": bool,
                  "edges": [{"edge_id", "hit_nodes": [...]}, ...]},
  "crossings": {"excessive_count": n, "ratio": r, "pass": bool,
                "per_edge": {edge_id: 교차수, ...},
                "crossing_pairs": [[e_a, e_b, 교차수], ...]},
  "pass": bool  # 두 게이트 AND
}
"""

import argparse
import json
import os
import sys
from collections import defaultdict

# 프로젝트 루트를 sys.path에 추가 (어느 cwd에서 실행해도 normalize import 가능)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

EPS = 1e-6


def _segments(points):
    """폴리라인 [(x,y)...] → 길이 양수인 세그먼트 [((x1,y1),(x2,y2)), ...]."""
    segs = []
    for a, b in zip(points, points[1:]):
        if abs(a[0] - b[0]) > EPS or abs(a[1] - b[1]) > EPS:
            segs.append((tuple(a), tuple(b)))
    return segs


def _seg_hits_box_interior(a, b, bbox):
    """축평행 세그먼트 a→b가 bbox 내부와 양(+) 길이로 겹치는가."""
    bx, by, bw, bh = bbox
    x1, x2 = sorted((a[0], b[0]))
    y1, y2 = sorted((a[1], b[1]))
    if abs(a[1] - b[1]) <= EPS:  # 수평 세그먼트
        cy = a[1]
        if not (by + EPS < cy < by + bh - EPS):
            return False
        return min(x2, bx + bw) - max(x1, bx) > EPS
    if abs(a[0] - b[0]) <= EPS:  # 수직 세그먼트
        cx = a[0]
        if not (bx + EPS < cx < bx + bw - EPS):
            return False
        return min(y2, by + bh) - max(y1, by) > EPS
    return False  # 사선은 계획 폴리라인에 없음 (방어)


def _segs_cross(s1, s2):
    """수평↔수직 세그먼트의 strict transversal 교차 여부 (끝점 접촉 제외)."""
    (a1, a2), (b1, b2) = s1, s2
    h1 = abs(a1[1] - a2[1]) <= EPS  # s1 수평?
    h2 = abs(b1[1] - b2[1]) <= EPS
    if h1 == h2:  # 평행(둘 다 수평/수직) — transversal 교차 없음
        return False
    if not h1:  # s1을 수평으로 정규화
        s1, s2 = s2, s1
        (a1, a2), (b1, b2) = s1, s2
    hy = a1[1]
    hx1, hx2 = sorted((a1[0], a2[0]))
    vx = b1[0]
    vy1, vy2 = sorted((b1[1], b2[1]))
    return (hx1 + EPS < vx < hx2 - EPS) and (vy1 + EPS < hy < vy2 - EPS)


def evaluate_routes(routes, node_bboxes, pen_thresh=0.10, cross_thresh=0.15,
                    cross_limit=3):
    """라우트 목록 vs 노드 bbox로 관통/과다교차 게이트 계산 (JSON 직렬화 dict)."""
    edges_total = len(routes)

    # --- 박스 관통
    pen_edges = []
    for r in routes:
        exclude = {r.get("from"), r.get("to")}
        hits = []
        for nid, bbox in node_bboxes.items():
            if nid in exclude:
                continue
            if any(_seg_hits_box_interior(a, b, bbox)
                   for a, b in _segments(r["points"])):
                hits.append(nid)
        if hits:
            pen_edges.append({"edge_id": r.get("id"), "hit_nodes": sorted(hits)})
    pen_ratio = len(pen_edges) / edges_total if edges_total else 0.0

    # --- 커넥터 쌍별 교차 수
    seg_cache = [(r.get("id"), _segments(r["points"])) for r in routes]
    cross_count = defaultdict(int)   # edge_id → 총 교차 수
    pair_counts = {}
    for i in range(len(seg_cache)):
        for j in range(i + 1, len(seg_cache)):
            n = sum(1 for s1 in seg_cache[i][1] for s2 in seg_cache[j][1]
                    if _segs_cross(s1, s2))
            if n:
                ea, eb = seg_cache[i][0], seg_cache[j][0]
                cross_count[ea] += n
                cross_count[eb] += n
                pair_counts[(ea, eb)] = n
    excessive = sorted(e for e, n in cross_count.items() if n >= cross_limit)
    cross_ratio = len(excessive) / edges_total if edges_total else 0.0

    pen_pass = pen_ratio <= pen_thresh
    cross_pass = cross_ratio <= cross_thresh
    return {
        "params": {"pen_thresh": pen_thresh, "cross_thresh": cross_thresh,
                   "cross_limit": cross_limit},
        "edges_total": edges_total,
        "penetration": {
            "edge_count": len(pen_edges),
            "ratio": round(pen_ratio, 4),
            "pass": pen_pass,
            "edges": pen_edges,
        },
        "crossings": {
            "excessive_count": len(excessive),
            "excessive_ids": excessive,
            "ratio": round(cross_ratio, 4),
            "pass": cross_pass,
            "per_edge": dict(sorted(cross_count.items())),
            "crossing_pairs": [[a, b, n] for (a, b), n in sorted(pair_counts.items())],
        },
        "pass": pen_pass and cross_pass,
    }


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
    ap = argparse.ArgumentParser(description="elbow 라우팅 게이트 — 박스 관통·과다 교차")
    ap.add_argument("routes", help="route-report JSON 경로")
    ap.add_argument("ir", help="렌더에 쓴 IR JSON 경로")
    ap.add_argument("--normalize", choices=["b1", "b2"], default=None,
                    help="렌더 때와 동일한 정규화 모드 (기본 params 재적용)")
    ap.add_argument("-o", "--output", default=None,
                    help="게이트 결과 JSON 저장 경로 (기존 파일은 증분 suffix)")
    ap.add_argument("--pen-thresh", type=float, default=0.10)
    ap.add_argument("--cross-thresh", type=float, default=0.15)
    ap.add_argument("--cross-limit", type=int, default=3)
    args = ap.parse_args(argv)

    with open(args.routes, encoding="utf-8") as f:
        routes = json.load(f)["edges"]
    with open(args.ir, encoding="utf-8") as f:
        ir = json.load(f)
    if args.normalize:
        from normalize.layout import normalize
        ir = normalize(ir, mode=args.normalize)

    node_bboxes = {n["id"]: n["bbox"] for n in ir.get("nodes", [])}
    result = evaluate_routes(routes, node_bboxes,
                             pen_thresh=args.pen_thresh,
                             cross_thresh=args.cross_thresh,
                             cross_limit=args.cross_limit)
    result = {"routes_path": args.routes, "ir_path": args.ir,
              "normalize_mode": args.normalize, **result}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        out_path = _unique_path(args.output)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[elbow_gate] 저장: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
