# 002 — M0b 얇은 수직 슬라이스: 기계 게이트 결과 (사용자 실기 대기)

작성: 2026-07-14. [[001-m0a-probe]] 후속. 계획 정본 §4 M0b / §7 0~5의 실행 기록.
**상태: 기계 쪽 게이트 전부 통과. 남은 것 = ① 적대적 검증 3종(세션 한도로 연기) ② 사용자
PowerPoint 실기 2건(AC2 존재적 게이트 + R13 스파이크) — 이 둘이 끝나야 M0b가 닫힌다.**

## 1. 무엇을 지었나 (빌드, 병렬 5 에이전트)

| 산출물 | 내용 |
|---|---|
| `tests/fixtures/example-0N.golden.ir.json` | 전체 골든 (min-golden + intent_row/col·size_class, 포함관계 기계검증 통과) |
| `eval/recognition_eval.py` | 7지표 계측기 (존재 R/P/F1 + 좌표 med/p90·IoU + role confusion + 엣지 + diff) |
| `normalize/layout.py` | B1(클러스터링 정렬+크기통일)/B2(스냅만) + 의도-기반 과·미교정 카운터 |
| `render/` + `cli.py` | 스텁 렌더러 (elbow 바인딩 커넥터, AC1 규약 준수, **증분 파일명 내장**) |
| `docs/golden-ir-labeling.md` | 라벨링 프로토콜 (M0a 골든 오류 교훈 반영) |
| `eval/noise_sweep.py`, `eval/elbow_gate.py` | 임계 도출·R13 계측 (통합 단계 신설) |

사고 기록: 통합 실행 에이전트가 **세션 사용량 한도**로 중단(산출물 대부분 생성 후) →
메인 세션이 통합을 직접 인수. 17:12 layout.py 수정 이전에 렌더된 pptx가 stale임을
발견해 b1 4종 재렌더(-1 suffix — 증분 규칙이 실전에서 작동함을 확인).

## 2. 기계 게이트 결과

| 게이트 | 결과 | 수치 |
|---|---|---|
| 귀속 계측 (4쌍) | ✅ | 존재 R/P/F1 전부 1.00, 좌표 M0a와 정합, role 오분류 ex01 2/40(n25, g5)·경미 |
| **gate1: 과교정+미교정 (골든 경로 B1)** | ✅ PASS | **박스 기준 ex01 2/40(5%), ex02 1/15(7%)** ≤10% |
| gate2: elbow 라우팅 (계획 경로) | ✅ PASS | 관통 0%, 과다교차 0% (골든·인식 경로 모두) |
| AC1 도형수 공식 | ✅ | 10개 pptx 전부 기대=실제 (node1·edge1+label·legend 1+2N·컨테이너1) |
| 노이즈 스윕 | ⚠️ 주의 | tol 7.2에서 붕괴 σ≈4‰. 실측 인식 노이즈 med 2.8‰ → **통과하나 마진 얇음** |

gate1 집계 주의: 계획 문구 "합 ≤ 전체 10%"를 **쌍(pair) 기준으로 세면 ex01 FAIL(13/40)**,
**박스 기준으로 세면 PASS(2/40)**. AC2의 정의가 "사용자가 위치를 손봐야 하는 박스 수"이므로
박스 기준이 정합 — 미교정 5쌍의 실체는 박스 1개(n15)가 5개 파트너와 어긋난 것.
`eval_out/gates-2.json`에 박스 기준 집계 병기 (gates.json은 17:12 수정 전 stale).

## 3. 핵심 발견 — 단일 tol의 구조적 한계 (M1 백로그)

임계값 스윕(7.2/10/13/16/20)에서 3중 긴장 확인:
- 의도 그룹 **내** 손그림 산포: 8~12‰ (이걸 다 붙이려면 tol ≥ 12 필요)
- 서로 다른 그룹 **간** 최소 간격: ~9‰ (tol이 이걸 넘으면 오병합)
- 두 값이 **겹침** → 단일 tol로 완벽 분리 불가능

**tol=16 함정**: count 게이트는 "통과"(미교정 0)하지만 클러스터 순도(pair F1)가 σ=1에서
0.33~0.62로 붕괴 — 1D 단일연결 클러스터링이 다리 박스(n15)를 통해 무관한 행을 연쇄
병합(chaining)하고, 병합 스냅이 정렬처럼 보이는 **가짜 통과**. n2가 21.5‰ 이동하는
과교정 발생 (pre-mortem #1 실물). count 지표와 순도 지표의 교차 검증이 잡아냄.

**결정: 기본 tol=7.2 유지** (미교정 실체 = n15 한 박스, 박스 기준 PASS).
근본 해법 = **컨테이너 스코프 클러스터링**(같은 부모 안에서만 병합; 단 cross-container
의도 정렬(acm_top의 n15)은 별도 메커니즘 필요) 또는 complete-linkage — **M1 백로그**로 이관.

## 4. 남은 절차 (M0b 마감 조건)

**A. 적대적 검증 3종** (세션 한도 리셋 후 실행): ① normalize 카운터 반례 실험
(near-zero-by-construction 퇴행 검사) ② 렌더러 XML 실검사(stCxn/endCxn 존재) ③ 기능 스모크.
메인 루프가 수행한 기계 검증(AC1·게이트 재계산)과 별개의 독립 패스.

**B. 사용자 PowerPoint 실기 (Windows에서 `\\wsl.localhost\Ubuntu\home\dlacksdn\ppt_creator\outputs\` 열기):**

1. **AC2 존재적 게이트 (B1 vs B2 A/B)** — 4개 파일 각각에서 "위치·정렬·크기가 틀려서
   내가 손봐야 할 박스 수"를 센다 (스타일 없음·커넥터 모양 조악은 카운트 제외):
   - `ex01-recog-b1-1.pptx` vs `ex01-recog-b2.pptx` (40박스)
   - `ex02-recog-b1-1.pptx` vs `ex02-recog-b2.pptx` (15박스)
   - 판정: 전 표본 ≤7% GO(ex01 ≤2개·ex02 ≤1개) / 하나라도 >13% NO-GO(ex01 ≥6개·ex02 ≥2개) / 그 외 표본 추가.
     B1 우월분 ±3%p 초과 시에만 B1 확정, 이내면 B2 채택(YAGNI).
   - 캘리브레이션: 시차를 두고 같은 파일 1개를 2회 판정, 카운트 편차 기록.
2. **R13 저장 경로 생존 스파이크** — `ex01-recog-b1-1.pptx`를 열고 → **아무것도 옮기지
   말고** → "다른 이름으로 저장" `ex01-recog-b1-1.saved.pptx` → 알려주면 XML 비교로
   재라우팅/생존/cxnIdx 재선택을 세션이 판정한다.

## 5. 산출물 경로

- 코드: `normalize/layout.py`, `render/*`, `cli.py`, `eval/recognition_eval.py`, `eval/noise_sweep.py`, `eval/elbow_gate.py`
- 데이터: `tests/fixtures/example-0N.golden.ir.json`, `eval_out/*.json` (gates-2.json = 최신 집계)
- pptx: `outputs/ex0N-{golden,recog}-b1-1.pptx`(최신), `ex0N-recog-b2.pptx`, 구판 b1(참고용 보존)
- 문서: `docs/golden-ir-labeling.md`, `ir/schema.md` M0b 확장 절
