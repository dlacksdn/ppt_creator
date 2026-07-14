# IR (중간 표현) 스키마 v0.1 — M0a 확정본

작성: 2026-07-14 (계획 §4 "0-pre" 산출물). 기계 검증용 정의는 `ir/schema.json`.
IR은 손그림 다이어그램의 **내용**(무엇이 어디에 있고 무엇을 연결하는가)만 담는다.
색·폰트·선굵기 같은 꾸밈은 담지 않는다 — 그건 스타일 config(`styles/`)의 몫이다.

## 좌표계 (확정 — 계획 v6, 라운드5 MAJOR 반영)

**등방(isotropic) 정규화 정수.**

- `canvas.aspect` = 종횡비 문자열 `"W:H"` (예: `"16:9"`). canvas는 종횡비**만** 보유한다.
- **장축을 0~1000**으로, **단축을 0~round(1000 × 단축/장축)** 으로 정규화한다.
  - 예: 가로가 긴 16:9 → x ∈ 0~1000, y ∈ 0~563 (= round(1000×9/16))
  - 예: 4:3 → x ∈ 0~1000, y ∈ 0~750
- 모든 `bbox`의 x·y·w·h는 이 등방 단위의 **정수**다.
- 왜 등방인가: 1‰(단위 1)가 **두 축에서 동일한 물리 길이**여야 centroid 2D 거리,
  클러스터링 거리, "박스폭 X%" 임계가 단일 척도에서 돈다. 축별 독립 0~1000은
  비정방 캔버스에서 1‰(x)≠1‰(y)라 거리 지표를 왜곡한다.
- 왜 절대 픽셀이 아닌가: VLM은 고해상도 절대 px 좌표 추정에 구조적으로 약하고,
  태블릿 사진은 해상도가 매번 다르다. 정규화가 R10(좌표 오차) 스키마 선제 방어.

`bbox` = `[x, y, w, h]` (좌상단 기준, w·h > 0).

## 최상위 구조

```json
{
  "canvas": { "aspect": "16:9" },
  "nodes": [ ... ],
  "edges": [ ... ],
  "containers": [ ... ],
  "annotations": [ ... ]
}
```

## nodes[] — 박스·플레이스홀더

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | string | ✔ | 유일 식별자 (`n1`, `n2`, …) |
| `kind` | `"box"` \| `"placeholder"` | ✔ | placeholder = 수식·아이콘 자리 (자동 변환 안 함, 위치만 표시) |
| `bbox` | [int×4] | ✔ | 등방 정규화 좌표 |
| `text` | string | ✔ | 박스 안 텍스트 (한글/영문 그대로, 없으면 `""`) |
| `role` | string | ✔ | 스타일 매핑 열쇠. 허용값: `default`(흰 박스) / `emphasis`(강조·분홍) / `input`(입력·하늘) / `output`(출력·초록) / `phase`(단계 헤더) / `unknown` |
| `placeholder_kind` | `"equation"` \| `"icon"` | placeholder일 때만 | 손으로 넣을 내용의 종류 |

## edges[] — 화살표

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | string | ✔ | `e1`, `e2`, … |
| `from` / `to` | string | ✔ | 노드·컨테이너 id. 방향은 from→to |
| `arrow` | `"single"` \| `"double"` \| `"none"` | ✔ | 화살표 머리 |
| `label` | string | — | 엣지 라벨 (없으면 생략) |
| `style` | `"straight"` \| `"elbow"` | ✔ | 손그림에서 관찰된 형태 |

## containers[] — 중첩 컨테이너 (큰 배경 박스)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | string | ✔ | `g1`, `g2`, … |
| `bbox` | [int×4] | ✔ | 등방 정규화 좌표 |
| `title` | string | ✔ | 컨테이너 제목 (없으면 `""`) |
| `children` | [string] | ✔ | 직속 자식 id 목록 (노드·하위 컨테이너) |
| `role` | string | ✔ | nodes와 동일 규약 (보통 `default`) |

## annotations[] — 범례 등 부속물

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | string | ✔ | `a1`, … |
| `kind` | `"legend"` \| `"note"` | ✔ | |
| `bbox` | [int×4] | ✔ | |
| `items` | [string] | legend일 때 | 항목 텍스트 목록 (예: `["Trainable", "Frozen"]`) |
| `text` | string | note일 때 | |

## 렌더 결정 고정 (AC1 카운팅 공식과 일치 — 계획 v5·v6 확정)

렌더러가 IR 원소당 생성하는 pptx shape 수를 여기 못박는다 (변경 시 schema versioning):

| IR 원소 | 렌더 shape 수 | 결정 |
|---|---|---|
| node (box/placeholder) | **1** | 자기 text_frame에 텍스트 인라인 |
| container | **1** | **title도 자기 text_frame 인라인** (별도 텍스트박스 ❌) |
| edge | **1 + (label 있으면 +1)** | 커넥터 1개 + **라벨은 별도 텍스트박스** (python-pptx 커넥터 text_frame 불안정 대응). caveat: 박스 수동 이동 시 라벨은 미추종(재렌더로 정합) |
| legend | **배경 1 + 2N (+제목 있으면 +1)** | **항목 = 스와치 사각형 1 + 라벨 텍스트박스 1 = 2 shape** |

## M0b 확장 예약 필드 (M0a에서는 사용 안 함)

- `intent_align` (eval 전용): 의도된 정렬 그룹 라벨 — 골든 IR에만
- `size_class` (eval 전용): 의도된 크기 클래스 — 골든 IR에만
- `align_hint` (런타임, M2): 검수 루프의 "이 셋을 한 줄로" 채팅 교정 채널

## 오차 단위 규약 (probe/recognition_eval과 일치)

좌표 오차는 **‰ (등방 단위, 장축의 1/1000)** 로 보고한다. 등방이므로 x·y 오차가
동일 물리 척도다. IoU는 무차원 비율.
