# Deep Interview Spec: 손그림 다이어그램 → 내 스타일 PPT 자동 변환 (sketch2pptx)

## Metadata
- Interview ID: di-pptcreator-20260714-a1
- Rounds: 5 (+ Round 0 토폴로지 게이트)
- Final Ambiguity Score: 16%
- Type: greenfield
- Generated: 2026-07-14
- Threshold: 20%
- Initial Context Summarized: no
- Status: PASSED

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.88 | 0.40 | 0.352 |
| Constraint Clarity | 0.85 | 0.30 | 0.255 |
| Success Criteria | 0.78 | 0.30 | 0.234 |
| **Total Clarity** | | | **0.841** |
| **Ambiguity** | | | **0.159 (16%)** |

## Topology (Round 0 확정, R1에서 ④ 재정의)
| Component | Status | Description | Coverage |
|-----------|--------|-------------|----------|
| 인식 (recognition) | active | 손그림 이미지 → IR JSON. 인식기 = Claude Code 세션(VLM). 수식·아이콘은 플레이스홀더 처리 | R3에서 범위 확정 |
| 스타일 정의 (style-config) | active | 원본 .pptx에서 스타일 추출 → 공통 config 1개 + 글꼴 변형 2종 스위치 | R2에서 소스 확보 확정 |
| 렌더링 (renderer) | active | IR + config → 편집 가능 pptx. **레이아웃 정규화가 품질 핵심** (R4) | R4에서 우선순위 승격 |
| 검수 루프 (review-loop) | active | 별도 검수 산출물 없음 — 바로 pptx 생성 → PowerPoint 직접 검수 → 채팅 지적(IR 수정→재렌더) 또는 PPT 손수정 | R1에서 방식 확정 |

## Goal
사용자가 태블릿에 그린 박스-화살표 다이어그램 이미지를 Claude Code 세션에 첨부하면,
세션이 IR(JSON)로 인식하고 파이썬 렌더러가 사용자의 기존 PPT 스타일(원본 .pptx에서
추출한 config)을 입혀 **배치까지 완성된, 완전히 편집 가능한 네이티브 도형 .pptx**를
생성한다. 검수·수정은 PowerPoint에서 직접 확인 후 채팅으로 지적하면 IR을 고쳐
재렌더링하는 루프로 처리한다.

## Constraints
- 실행 형태 = **Claude Code 세션** (인식기 = 세션 자체, 렌더러 = 세션이 호출하는 파이썬 스크립트). 별도 서비스/CLI/웹 UI 없음 (M4에서 /스킬 승격은 옵션)
- 다이어그램 범위 = **박스-화살표 도식** (노드·엣지·중첩 컨테이너·범례)
- 수식·아이콘(이미지)은 자동 변환하지 않고 **플레이스홀더 박스**로 위치만 표시 (사용자가 손으로 삽입)
- 스타일 소스 = 사용자 보유 **원본 .pptx 파일들** (스타일 2종 — 글꼴만 다르고 색·구조 동일 → 공통 config + 글꼴 스위치)
- 배치는 손그림의 좌표를 존중 (자동 레이아웃 재배치 금지), 정규화는 스냅·정렬·크기통일만
- 산출물은 덮어쓰지 않고 증분 파일명(-1, -2, …)으로 저장 (사용자 전역 규칙)
- 출력은 네이티브 pptx 도형만 (이미지 삽입 금지), 커넥터는 도형에 바인딩

## Non-Goals
- 웹 서비스/범용 제품화 (개인 도구)
- 수식(LaTeX)·아이콘의 자동 렌더링
- 표·타임라인·플로우차트 외 유형 (박스-화살표 외는 MVP 범위 밖)
- 자동 레이아웃(graphviz류) — 사용자 배치 의도 보존이 원칙
- 원샷 100% 자동 (검수 루프 전제)

## Acceptance Criteria
- [ ] 예시 손그림 입력 → 생성된 pptx가 PowerPoint에서 정상으로 열리고, 모든 도형이 그룹 엉킴 없이 개별 이동·텍스트 수정 가능하다
- [ ] **생성 직후 사용자가 위치를 손봐야 하는 박스가 전체의 10% 이하다** (예시 ~40박스 기준 4개 이하) — 1순위 기준 (R4 "재배치 지옥" 방지)
- [ ] M0 게이트: 노드·엣지 인식 재현율 ≥ 80% (예시 손그림 실측)
- [ ] 검수 루프 1~2회 후 내용 오류(텍스트·화살표 방향) 0
- [ ] 스타일이 원본 .pptx와 일치 (색·테두리·선굵기), 글꼴 변형 2종이 config 스위치로 전환된다
- [ ] 커넥터가 도형에 바인딩되어 박스를 옮기면 화살표가 따라온다
- [ ] 손그림 입력 → 최종 pptx까지 총 소요 ≤ 10분 (검수 포함)
- [ ] 수식·아이콘 위치에 플레이스홀더 박스가 표시된다
- [ ] 재렌더 시 기존 산출물을 덮어쓰지 않는다 (증분 파일명)

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| 검수에 별도 시각화(오버레이/HTML)가 필요하다 | R1: 검수 방식 4종 비교 제시 | **바로 pptx 생성 후 PowerPoint 직접 검수** — 중간 산출물 제거, 파이프라인 단순화 |
| 스타일을 이미지에서 눈대중으로 추출해야 할 수 있다 | R2: 원본 보유 여부 확인 | **원본 .pptx 보유** → 파일에서 직접 추출 (정확도 확보) |
| 스타일은 1개다 | R2 | **2종, 글꼴만 다름** → 공통 config + 글꼴 스위치 |
| 다양한 다이어그램 유형을 지원해야 할 수 있다 | R3: 유형 범위 질문 | **박스-화살표가 대다수**, 수식·아이콘은 수동 삽입 허용 → 플레이스홀더로 축소 |
| 성공 기준 = 속도 (10분 이내) | R4 컨트래리언: "무엇이면 도구를 버리나?" | **진짜 기준 = 재배치 최소화** — 레이아웃 정규화가 품질 핵심으로 승격, 속도는 부차 기준 |
| 실행 형태 미정 (CLI? 서비스?) | R5 | **Claude Code 세션** — 인프라 0, 인식·검수 대화 모두 세션에서 |

## Technical Context (greenfield)
- Python 3.11+ 전용 venv (`ppt_creator/.venv`), `python-pptx` + `lxml`(커넥터 XML) + `pyyaml`
- 인식 = Claude Code 세션이 이미지 Read → IR JSON 작성 (API 자동화는 범위 밖)
- 계획 v1 = `_thinking/plan/001-sketch2pptx-plan.md` (IR 기반 5단 파이프라인, 마일스톤 M0~M4)
- 이 스펙이 계획 v1에 덮어쓰는 변경점: ① 검수 = pptx 직접 (오버레이/HTML 원안 폐기)
  ② 스타일 config = 원본 pptx 추출 + 글꼴 스위치 ③ 레이아웃 정규화 = 품질 1순위로 승격
  ④ 수식·아이콘 플레이스홀더 추가 ⑤ 실행 형태 = 세션 확정

## Ontology (Key Entities — 최종 라운드 기준)
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| 손그림 이미지 | core domain | 파일경로, 해상도 | 인식기의 입력 |
| IR (중간표현) | core domain | canvas, nodes[], edges[], annotations[] | 손그림에서 추출, 렌더러의 입력, 검수 대상 |
| 노드 | core domain | id, kind(box/container), bbox, text, role | IR에 속함, 엣지가 연결 |
| 엣지 | core domain | from, to, arrow, label, style | 노드 2개를 연결 |
| 플레이스홀더 | supporting | bbox, kind(수식/아이콘) | 노드의 특수형 — 수동 삽입 표시 |
| 스타일 Config | core domain | roles{}, edges{}, layout{}, **font_variant(2종)** | 원본 pptx에서 추출, 렌더러가 소비 |
| 원본 .pptx | supporting | 스타일 2종 (글꼴만 상이) | 스타일 Config의 소스 |
| 렌더러 | core domain | IR+config → pptx, 레이아웃 정규화 포함 | 결정론적 |
| pptx 산출물 | core domain | 증분 파일명, 네이티브 도형, 바인딩 커넥터 | 검수 루프의 대상 |
| 검수 루프 | core domain | PPT 직접 확인 → 채팅 지적 → IR 수정 → 재렌더 | 세션에서 수행 |
| Claude Code 세션 | external system | 인식기 + 오케스트레이터 | 전 파이프라인의 실행 주체 |
| VLM 인식 | supporting | 재현율 ≥80% 게이트(M0) | 세션에 내장 |

## Ontology Convergence
| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 8 | 8 | - | - | N/A |
| 2 | 10 | 2 (원본pptx, 글꼴변형) | 0 | 8 | 80% |
| 3 | 12 | 2 (수식·아이콘 플레이스홀더) | 0 | 10 | 83% |
| 4 | 12 | 0 | 0 | 12 | 100% |
| 5 | 12 | 0 | 0 | 12 | **100% (수렴)** |

## Interview Transcript
<details>
<summary>Full Q&A (Round 0 + 5 rounds)</summary>

### Round 0 (토폴로지 게이트)
**Q:** 4개 컴포넌트(인식/스타일/렌더링/검수)가 맞는가?
**A:** (역질문) "검수는 어떤 식으로 진행하려고?"

### Round 1
**Q:** 검수 방식 — 오버레이 이미지 / 바로 pptx / HTML 나란히 / 텍스트 요약 중 무엇?
**A:** **바로 pptx 만들고 검수** (+ 토폴로지 4개 확정)
**Ambiguity:** 40% (Goal 0.75, Constraints 0.45, Criteria 0.55)

### Round 2
**Q:** 완성 PPT의 원본 .pptx 파일을 갖고 있는가?
**A:** **있다. 스타일 2가지인데 글꼴만 다르고 색상·구조는 동일**
**Ambiguity:** 34% (Goal 0.78, Constraints 0.60, Criteria 0.55)

### Round 3
**Q:** 다이어그램 유형 범위는?
**A:** **박스-화살표가 대다수. 수식 가끔, 아이콘도 들어가지만 그 정도는 손으로 넣어도 됨**
**Ambiguity:** 29% (Goal 0.82, Constraints 0.72, Criteria 0.55)

### Round 4 (컨트래리언 모드)
**Q:** 무엇이 나오면 "내가 직접 그리는 게 낫다"며 도구를 버리는가?
**A:** **재배치 지옥** (정렬·간격·크기가 어색해 결국 전부 재배치하게 되는 것)
**Ambiguity:** 22% (Goal 0.85, Constraints 0.72, Criteria 0.75)

### Round 5
**Q:** 도구의 실행 형태는? (세션/CLI/웹/보류)
**A:** **Claude Code 세션**
**Ambiguity:** 16% (Goal 0.88, Constraints 0.85, Criteria 0.78) — **임계값 통과**

</details>
