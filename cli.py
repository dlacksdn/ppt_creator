#!/usr/bin/env python
# 사용법:
#   /home/dlacksdn/ppt_creator/.venv/bin/python cli.py render IR.json \
#       -o outputs/name.pptx [--normalize b1|b2] [--golden FULL.json] \
#       [--route-report outputs/name.routes.json]
#
#   - 출력 파일이 이미 있으면 덮어쓰지 않고 -1, -2 증분 suffix 자동 부여.
#   - --normalize : 렌더 전에 normalize.layout.normalize 적용 (b1|b2).
#   - --golden    : --normalize와 함께 주면 normalize.layout.count_corrections로
#                   미교정/과교정 리포트를 stdout에 JSON 출력.
#   - --route-report : 엣지별 계획 elbow 폴리라인(‰)을 JSON 저장 (계측용).
"""sketch2pptx CLI — IR(JSON) → pptx 렌더 진입점 (M0b 스텁)."""

import argparse
import json
import os
import sys

# 프로젝트 루트를 sys.path에 추가 (어느 cwd에서 실행해도 render/normalize import 가능)
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from render.renderer import render  # noqa: E402


def _load_json(path):
    """JSON 파일 로드 (에러 시 메시지와 함께 종료)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"[오류] JSON 로드 실패 {path}: {exc}")


def cmd_render(args):
    """render 서브커맨드 본체."""
    ir = _load_json(args.ir)

    # 정규화는 CLI에서 직접 수행 → --golden 리포트에 같은 결과를 재사용
    if args.normalize:
        try:
            from normalize.layout import normalize
        except ImportError as exc:
            sys.exit(f"[오류] --normalize에는 normalize/layout.py가 필요: {exc}")
        ir = normalize(ir, mode=args.normalize)

    if args.golden:
        if not args.normalize:
            print("[경고] --golden은 --normalize와 함께 써야 교정 리포트가 의미 있음 — 생략",
                  file=sys.stderr)
        else:
            from normalize.layout import count_corrections
            golden = _load_json(args.golden)
            report = count_corrections(golden, ir)
            print(json.dumps(report, ensure_ascii=False, indent=2))

    out = args.output
    if out is None:
        stem = os.path.splitext(os.path.basename(args.ir))[0]
        out = os.path.join(ROOT, "outputs", f"{stem}.pptx")

    pptx_path, routes_path = render(ir, out, normalize_mode=None,
                                    route_report=args.route_report)
    print(f"저장: {pptx_path}")
    if routes_path:
        print(f"route-report: {routes_path}")


def main():
    parser = argparse.ArgumentParser(
        prog="cli.py", description="sketch2pptx — IR(JSON)을 pptx로 렌더")
    sub = parser.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render", help="IR JSON → pptx (무스타일 스텁)")
    p_render.add_argument("ir", help="입력 IR JSON 경로")
    p_render.add_argument("-o", "--output", default=None,
                          help="출력 pptx 경로 (기본: outputs/<IR이름>.pptx, 존재 시 증분)")
    p_render.add_argument("--normalize", choices=["b1", "b2"], default=None,
                          help="렌더 전 레이아웃 정규화 모드")
    p_render.add_argument("--golden", default=None, metavar="FULL.json",
                          help="전체 골든 IR — --normalize와 함께 쓰면 교정 리포트 출력")
    p_render.add_argument("--route-report", default=None, metavar="OUT.json",
                          help="엣지별 계획 elbow 폴리라인(‰) JSON 저장 경로")
    p_render.set_defaults(func=cmd_render)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
