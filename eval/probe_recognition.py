#!/usr/bin/env python3
"""M0a 일회용 계측 (노트북 수준) — 세션 인식 IR vs 최소 골든 IR.

계획 §4 M0a / §7 2a 전용. 완성 recognition_eval.py가 아니다 (그건 M0b).
산출: 노드/엣지 recall, bbox centroid 오차(중앙값·p90, ‰), IoU(중앙값, <0.5 개수).

사용: python3 eval/probe_recognition.py <recognized.ir.json> <golden.ir.json>
좌표계: 등방 정규화 정수 (ir/schema.md). ‰ = 장축의 1/1000, 두 축 동일 물리 척도.
"""
import json
import math
import sys
from difflib import SequenceMatcher


def norm_text(s):
    return "".join(ch for ch in s.lower() if ch.isalnum())


def text_sim(a, b):
    a, b = norm_text(a), norm_text(b)
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def centroid(b):
    return (b[0] + b[2] / 2.0, b[1] + b[3] / 2.0)


def centroid_dist(b1, b2):
    (x1, y1), (x2, y2) = centroid(b1), centroid(b2)
    return math.hypot(x1 - x2, y1 - y2)


def iou(b1, b2):
    ax1, ay1, ax2, ay2 = b1[0], b1[1], b1[0] + b1[2], b1[1] + b1[3]
    bx1, by1, bx2, by2 = b2[0], b2[1], b2[0] + b2[2], b2[1] + b2[3]
    iw = max(0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = b1[2] * b1[3] + b2[2] * b2[3] - inter
    return inter / union if union > 0 else 0.0


def boxes_of(ir):
    """노드 + 컨테이너를 (id, text, bbox) 목록으로 (둘 다 '박스'로 취급해 매칭)."""
    out = []
    for n in ir.get("nodes", []):
        out.append((n["id"], n.get("text", ""), n["bbox"]))
    for c in ir.get("containers", []):
        out.append((c["id"], c.get("title", ""), c["bbox"]))
    return out


def match(rec, gold):
    """골든 기준 greedy 매칭: 텍스트 유사도 우선, 동률은 centroid 거리."""
    used = set()
    pairs = []  # (gold_idx, rec_idx)
    # 1차: 텍스트 매칭 (sim >= 0.6)
    for gi, (gid, gtext, gb) in enumerate(gold):
        best, best_key = None, None
        for ri, (rid, rtext, rb) in enumerate(rec):
            if ri in used:
                continue
            sim = text_sim(gtext, rtext)
            if sim < 0.6:
                continue
            key = (-sim, centroid_dist(gb, rb))
            if best_key is None or key < best_key:
                best, best_key = ri, key
        if best is not None:
            used.add(best)
            pairs.append((gi, best))
    # 2차: 남은 골든을 공간 매칭 (IoU > 0.3)
    matched_g = {gi for gi, _ in pairs}
    for gi, (gid, gtext, gb) in enumerate(gold):
        if gi in matched_g:
            continue
        best, best_iou = None, 0.3
        for ri, (rid, rtext, rb) in enumerate(rec):
            if ri in used:
                continue
            v = iou(gb, rb)
            if v > best_iou:
                best, best_iou = ri, v
        if best is not None:
            used.add(best)
            pairs.append((gi, best))
    return pairs


def pct(v, n):
    return f"{v}/{n} ({100.0 * v / n:.0f}%)" if n else "n/a"


def quantile(xs, q):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    i = (len(xs) - 1) * q
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def edge_key(e, id2box_idx, pairs_map, side):
    """엣지를 매칭된 상대 id로 정규화한 (from,to) 키로 변환. side='gold'|'rec'."""
    return (e["from"], e["to"])


def main():
    rec_path, gold_path = sys.argv[1], sys.argv[2]
    rec = json.load(open(rec_path))
    gold = json.load(open(gold_path))

    rboxes, gboxes = boxes_of(rec), boxes_of(gold)
    pairs = match(rboxes, gboxes)

    dists = [centroid_dist(gboxes[gi][2], rboxes[ri][2]) for gi, ri in pairs]
    ious = [iou(gboxes[gi][2], rboxes[ri][2]) for gi, ri in pairs]

    print(f"== probe: {rec_path} vs {gold_path} ==")
    print(f"박스(노드+컨테이너) recall : {pct(len(pairs), len(gboxes))}   "
          f"(인식측 잉여: {len(rboxes) - len(pairs)}개)")
    if dists:
        print(f"centroid 오차 ‰          : median {quantile(dists, 0.5):.1f} / p90 {quantile(dists, 0.9):.1f}")
        print(f"IoU                      : median {quantile(ious, 0.5):.2f} / <0.5 개수 "
              f"{sum(1 for v in ious if v < 0.5)}/{len(ious)}")

    # 엣지 recall: 매칭된 박스 id 대응으로 (from,to) 번역 후 비교
    g2r = {gboxes[gi][0]: rboxes[ri][0] for gi, ri in pairs}
    rec_edge_set = set()
    for e in rec.get("edges", []):
        rec_edge_set.add((e["from"], e["to"]))
        if e.get("arrow") == "double":
            rec_edge_set.add((e["to"], e["from"]))
    hit = 0
    gedges = gold.get("edges", [])
    misses = []
    for e in gedges:
        f, t = g2r.get(e["from"]), g2r.get(e["to"])
        ok = f is not None and t is not None and (
            (f, t) in rec_edge_set or (e.get("arrow") == "double" and (t, f) in rec_edge_set))
        hit += ok
        if not ok:
            misses.append(f'{e["id"]}({e["from"]}→{e["to"]})')
    print(f"엣지 recall              : {pct(hit, len(gedges))}")
    if misses:
        print(f"  누락 엣지: {', '.join(misses)}")

    # 매칭 실패 골든 박스
    matched_g = {gi for gi, _ in pairs}
    lost = [gboxes[gi][0] + ":" + (gboxes[gi][1][:12] or "(무텍스트)")
            for gi in range(len(gboxes)) if gi not in matched_g]
    if lost:
        print(f"  누락 박스: {', '.join(lost)}")

    # 노드별 상세 (골든 순)
    print("-- per-box (‰ 오차 / IoU) --")
    for gi, ri in sorted(pairs):
        g, r = gboxes[gi], rboxes[ri]
        print(f"  {g[0]:>4} {g[1][:18]:<18} -> {r[0]:>4}  d={centroid_dist(g[2], r[2]):5.1f}  iou={iou(g[2], r[2]):.2f}")


if __name__ == "__main__":
    main()
