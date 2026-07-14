#!/usr/bin/env python3
"""M0b 인식 충실도 계측 — 세션 인식 IR vs 골든 IR 7지표 산출 (AC3 귀속 레이어).

계획 §4 M0b / §7 2 전용. probe_recognition.py(M0a 일회용)의 매칭 로직을
재사용·개선한 완성판이다. pass/fail 게이트가 아니라, fail 원인을
"정규화 문제 vs 인식 문제"로 라우팅하기 위한 귀속(attribution) 계측기.

산출 지표 (모두 골든 기준):
  1. 박스(노드+컨테이너) recall / precision / F1
  2. bbox centroid 오차 중앙값·p90 (‰ = 등방 단위, 장축의 1/1000)
  3. IoU 중앙값 + IoU<0.5 매칭 쌍 개수/비율
  4. role confusion 행렬(골든 role → 인식 role) + 오분류율
  5. 엣지 recall / precision
  6. 골든↔인식 diff 크기 = 누락 + 잉여 + 텍스트 불일치 수 (AC7 조기추정용)

매칭 방식 (probe 재사용 + 개선):
  - 1차 텍스트 매칭: 정규화 텍스트 유사도 >= 0.6 후보를 전역 정렬
    (유사도 내림차순, 동률은 centroid 거리 오름차순) 후 greedy 배정.
    → 동일 텍스트 다중 박스(예: "Base Model" ×4)에서 centroid 최근접
      쌍이 먼저 배정된다. probe의 골든-순서 greedy는 앞 골든이 남의
      최근접 박스를 가로챌 수 있어 전역 greedy로 개선.
  - 2차 공간 매칭: 남은 골든을 IoU > 0.3 후보 전역 greedy로 배정.
  - 엣지: 매칭된 박스 id 대응(골든→인식)으로 (from,to)를 번역해 비교.
    arrow가 "double" 또는 "none"(머리 없음 = 방향 시각 정보 없음)이면
    어느 한쪽이라도 역방향 일치를 허용. 다중 동일 엣지는 multiset greedy
    (인식 엣지 1개는 골든 엣지 1개에만 대응 → precision 부풀림 방지).

좌표계: 등방 정규화 정수 (ir/schema.md — 장축 0~1000, 단축 비례).
‰ 오차는 두 축에서 동일 물리 척도다. IoU는 무차원 비율.

사용법:
  /home/dlacksdn/ppt_creator/.venv/bin/python eval/recognition_eval.py \
      REC.json GOLDEN.json [--json OUT.json]
  REC.json    = 세션이 인식한 IR
  GOLDEN.json = 사람이 라벨한 골든 IR (최소 골든이든 전체 골든이든 무방)
  --json      = 기계가독 지표 JSON 저장 경로 (사람용 출력은 항상 stdout)
"""
import argparse
import json
import math
import sys
from difflib import SequenceMatcher


# ---------------------------------------------------------------- 기초 유틸

def norm_text(s):
    """텍스트 정규화: 소문자화 후 영숫자(유니코드 포함)만 남긴다."""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def text_sim(a, b):
    """정규화 텍스트 유사도 (0~1). 둘 다 빈 문자열이면 1.0."""
    a, b = norm_text(a), norm_text(b)
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def centroid(b):
    return (b[0] + b[2] / 2.0, b[1] + b[3] / 2.0)


def centroid_dist(b1, b2):
    """centroid 2D 거리 (‰ — 등방 단위라 x·y 동일 물리 척도)."""
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


def quantile(xs, q):
    """단순 선형보간 분위수. 빈 목록이면 None (JSON 직렬화 안전)."""
    if not xs:
        return None
    xs = sorted(xs)
    i = (len(xs) - 1) * q
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


# ---------------------------------------------------------------- 박스 매칭

def boxes_of(ir):
    """노드+컨테이너를 (id, text, bbox, role) 목록으로 (둘 다 '박스' 취급).

    컨테이너의 텍스트는 title 필드다. role 누락 시 "unknown".
    """
    out = []
    for n in ir.get("nodes", []):
        out.append((n["id"], n.get("text", ""), n["bbox"], n.get("role", "unknown")))
    for c in ir.get("containers", []):
        out.append((c["id"], c.get("title", ""), c["bbox"], c.get("role", "unknown")))
    return out


def match_boxes(rec, gold, sim_thresh=0.6, iou_thresh=0.3):
    """골든↔인식 박스 매칭 (텍스트 우선 전역 greedy → 잔여 IoU 전역 greedy).

    반환: [(gold_idx, rec_idx)] — 각 인덱스는 최대 1회 사용.
    동일 텍스트 다중 박스는 (유사도 동률 → centroid 거리) 정렬이
    최근접 쌍부터 배정되게 보장한다.
    """
    pairs = []
    used_g, used_r = set(), set()

    # 1차: 텍스트 후보 전역 정렬 후 greedy
    cands = []
    for gi, (_, gtext, gb, _) in enumerate(gold):
        for ri, (_, rtext, rb, _) in enumerate(rec):
            sim = text_sim(gtext, rtext)
            if sim >= sim_thresh:
                cands.append((-sim, centroid_dist(gb, rb), gi, ri))
    cands.sort()
    for _, _, gi, ri in cands:
        if gi in used_g or ri in used_r:
            continue
        used_g.add(gi)
        used_r.add(ri)
        pairs.append((gi, ri))

    # 2차: 남은 골든을 공간(IoU) 후보 전역 greedy
    cands = []
    for gi, (_, _, gb, _) in enumerate(gold):
        if gi in used_g:
            continue
        for ri, (_, _, rb, _) in enumerate(rec):
            if ri in used_r:
                continue
            v = iou(gb, rb)
            if v > iou_thresh:
                cands.append((-v, gi, ri))
    cands.sort()
    for _, gi, ri in cands:
        if gi in used_g or ri in used_r:
            continue
        used_g.add(gi)
        used_r.add(ri)
        pairs.append((gi, ri))

    return sorted(pairs)


# ---------------------------------------------------------------- 엣지 매칭

def _undirected(e):
    """화살표 머리가 없거나(double 제외 none) 양방향이면 방향 정보 없음."""
    return e.get("arrow") in ("double", "none")


def match_edges(rec_edges, gold_edges, g2r):
    """골든 엣지 ↔ 인식 엣지 multiset greedy 매칭.

    골든 엣지의 (from,to)를 g2r(골든 id→인식 id)로 번역해 인식 엣지와 비교.
    정방향 일치 우선, 어느 한쪽이 double/none이면 역방향도 허용.
    인식 엣지 1개는 골든 엣지 1개에만 소비된다 (precision 정직성).

    반환: (matched_pairs [(g_edge, r_edge)], missed_gold [g_edge], extra_rec [r_edge])
    """
    used_r = set()
    matched, missed = [], []
    for ge in gold_edges:
        f, t = g2r.get(ge["from"]), g2r.get(ge["to"])
        found = None
        if f is not None and t is not None:
            # 정방향 우선 스캔, 없으면 역방향 허용 스캔
            for allow_rev in (False, True):
                for ri, re_ in enumerate(rec_edges):
                    if ri in used_r:
                        continue
                    fwd = re_["from"] == f and re_["to"] == t
                    rev = re_["from"] == t and re_["to"] == f
                    ok = fwd or (allow_rev and rev and (_undirected(ge) or _undirected(re_)))
                    if ok:
                        found = ri
                        break
                if found is not None:
                    break
        if found is not None:
            used_r.add(found)
            matched.append((ge, rec_edges[found]))
        else:
            missed.append(ge)
    extra = [re_ for ri, re_ in enumerate(rec_edges) if ri not in used_r]
    return matched, missed, extra


# ---------------------------------------------------------------- 지표 집계

def evaluate(rec, gold):
    """인식 IR vs 골든 IR 전 지표를 dict로 산출 (JSON 직렬화 가능)."""
    rboxes, gboxes = boxes_of(rec), boxes_of(gold)
    pairs = match_boxes(rboxes, gboxes)

    # --- 박스 존재 지표
    n_g, n_r, n_m = len(gboxes), len(rboxes), len(pairs)
    recall = n_m / n_g if n_g else None
    precision = n_m / n_r if n_r else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall and (precision + recall) > 0 else
          (0.0 if precision is not None and recall is not None else None))

    matched_g = {gi for gi, _ in pairs}
    matched_r = {ri for _, ri in pairs}
    missing_boxes = [gboxes[gi][0] for gi in range(n_g) if gi not in matched_g]
    extra_boxes = [rboxes[ri][0] for ri in range(n_r) if ri not in matched_r]

    # --- 좌표 지표 + role confusion + 텍스트 불일치 (매칭 쌍 단위)
    per_pair = []
    dists, ious = [], []
    confusion = {}   # gold_role -> rec_role -> count
    role_mismatches = []
    text_mismatch = 0
    for gi, ri in pairs:
        gid, gtext, gb, grole = gboxes[gi]
        rid, rtext, rb, rrole = rboxes[ri]
        d, v = centroid_dist(gb, rb), iou(gb, rb)
        dists.append(d)
        ious.append(v)
        confusion.setdefault(grole, {})
        confusion[grole][rrole] = confusion[grole].get(rrole, 0) + 1
        if grole != rrole:
            role_mismatches.append(
                {"gold_id": gid, "rec_id": rid, "gold_role": grole, "rec_role": rrole})
        txt_ok = norm_text(gtext) == norm_text(rtext)
        if not txt_ok:
            text_mismatch += 1
        per_pair.append({
            "gold_id": gid, "rec_id": rid,
            "gold_text": gtext, "rec_text": rtext, "text_match": txt_ok,
            "centroid_dist_permil": round(d, 2), "iou": round(v, 4),
            "gold_role": grole, "rec_role": rrole,
        })

    iou_low = sum(1 for v in ious if v < 0.5)
    role_err = len(role_mismatches)

    # --- 엣지 지표
    g2r = {gboxes[gi][0]: rboxes[ri][0] for gi, ri in pairs}
    gedges, redges = gold.get("edges", []), rec.get("edges", [])
    e_matched, e_missed, e_extra = match_edges(redges, gedges, g2r)
    e_recall = len(e_matched) / len(gedges) if gedges else None
    e_precision = len(e_matched) / len(redges) if redges else None

    # --- diff 크기 (AC7 조기추정: 검수 때 손대야 할 원소 수)
    diff = {
        "missing_boxes": len(missing_boxes),
        "extra_boxes": len(extra_boxes),
        "missing_edges": len(e_missed),
        "extra_edges": len(e_extra),
        "text_mismatch": text_mismatch,
    }
    diff["total"] = sum(diff.values())

    return {
        "boxes": {
            "golden_count": n_g, "rec_count": n_r, "matched": n_m,
            "recall": recall, "precision": precision, "f1": f1,
            "missing_ids": missing_boxes, "extra_ids": extra_boxes,
        },
        "centroid_permil": {
            "median": quantile(dists, 0.5), "p90": quantile(dists, 0.9),
        },
        "iou": {
            "median": quantile(ious, 0.5),
            "below_05_count": iou_low,
            "below_05_ratio": (iou_low / n_m) if n_m else None,
        },
        "role": {
            "confusion": confusion,
            "errors": role_err,
            "error_rate": (role_err / n_m) if n_m else None,
            "mismatches": role_mismatches,
        },
        "edges": {
            "golden_count": len(gedges), "rec_count": len(redges),
            "matched": len(e_matched),
            "recall": e_recall, "precision": e_precision,
            "missing_ids": [e["id"] for e in e_missed],
            "extra_ids": [e["id"] for e in e_extra],
        },
        "diff": diff,
        "pairs": per_pair,
    }


# ---------------------------------------------------------------- 사람용 출력

def _fmt(v, nd=2, suffix=""):
    return "n/a" if v is None else f"{v:.{nd}f}{suffix}"


def print_report(res, rec_path, gold_path):
    b, c, i = res["boxes"], res["centroid_permil"], res["iou"]
    r, e, d = res["role"], res["edges"], res["diff"]
    print(f"== recognition_eval: {rec_path} vs {gold_path} ==")
    print(f"[박스 존재] recall {_fmt(b['recall'])}  precision {_fmt(b['precision'])}  "
          f"F1 {_fmt(b['f1'])}   (골든 {b['golden_count']} / 인식 {b['rec_count']} / 매칭 {b['matched']})")
    if b["missing_ids"]:
        print(f"  누락 박스: {', '.join(b['missing_ids'])}")
    if b["extra_ids"]:
        print(f"  잉여 박스: {', '.join(b['extra_ids'])}")
    print(f"[좌표]      centroid ‰  median {_fmt(c['median'], 1)} / p90 {_fmt(c['p90'], 1)}")
    print(f"            IoU median {_fmt(i['median'])} / <0.5 개수 {i['below_05_count']}"
          f"/{b['matched']} ({_fmt((i['below_05_ratio'] or 0) * 100 if i['below_05_ratio'] is not None else None, 0, '%')})")
    print(f"[role]      오분류 {r['errors']}/{b['matched']} (오류율 {_fmt(r['error_rate'])})")
    roles = sorted(set(r["confusion"]) | {rr for m in r["confusion"].values() for rr in m})
    if roles:
        head = "            골든\\인식 " + " ".join(f"{x:>9}" for x in roles)
        print(head)
        for gr in sorted(r["confusion"]):
            row = r["confusion"][gr]
            print("            " + f"{gr:>9} " + " ".join(f"{row.get(x, 0):>9}" for x in roles))
    for m in r["mismatches"]:
        print(f"  role 불일치: {m['gold_id']}({m['gold_role']}) -> {m['rec_id']}({m['rec_role']})")
    print(f"[엣지]      recall {_fmt(e['recall'])}  precision {_fmt(e['precision'])}   "
          f"(골든 {e['golden_count']} / 인식 {e['rec_count']} / 매칭 {e['matched']})")
    if e["missing_ids"]:
        print(f"  누락 엣지: {', '.join(e['missing_ids'])}")
    if e["extra_ids"]:
        print(f"  잉여 엣지: {', '.join(e['extra_ids'])}")
    print(f"[diff 크기] 총 {d['total']}  (누락 박스 {d['missing_boxes']} + 잉여 박스 {d['extra_boxes']}"
          f" + 누락 엣지 {d['missing_edges']} + 잉여 엣지 {d['extra_edges']}"
          f" + 텍스트 불일치 {d['text_mismatch']})")
    print("-- per-box (‰ 오차 / IoU / role) --")
    for p in res["pairs"]:
        mark = "" if p["gold_role"] == p["rec_role"] else "  <role!>"
        tmark = "" if p["text_match"] else " <text!>"
        print(f"  {p['gold_id']:>4} {p['gold_text'][:18]:<18} -> {p['rec_id']:>4}"
              f"  d={p['centroid_dist_permil']:6.1f}  iou={p['iou']:.2f}"
              f"  {p['gold_role']}->{p['rec_role']}{mark}{tmark}")


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="세션 인식 IR vs 골든 IR 7지표 계측 (AC3 귀속 레이어)")
    ap.add_argument("rec", help="인식 IR JSON 경로")
    ap.add_argument("golden", help="골든 IR JSON 경로")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="기계가독 지표 JSON 저장 경로")
    args = ap.parse_args(argv)

    with open(args.rec, encoding="utf-8") as f:
        rec = json.load(f)
    with open(args.golden, encoding="utf-8") as f:
        gold = json.load(f)

    res = evaluate(rec, gold)
    print_report(res, args.rec, args.golden)

    if args.json_out:
        out = {"rec_path": args.rec, "golden_path": args.golden}
        out.update(res)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"[json] 지표 저장: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
