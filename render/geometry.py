# 사용법 (렌더 파이프라인 내부 모듈 — 직접 실행하지 않음):
#   from render.geometry import CanvasTransform
#   tr = CanvasTransform.from_ir(ir)
#   left, top, w, h = tr.bbox_to_emu([x, y, w, h])   # ‰ 정수 → EMU
"""IR 등방(isotropic) ‰ 좌표 → pptx EMU 좌표 변환.

좌표계 규약 (ir/schema.md 확정):
  - canvas.aspect = "W:H" 문자열. 장축을 0~1000, 단축을 0~round(1000×단축/장축)으로 정규화.
  - 모든 bbox = [x, y, w, h] (좌상단 기준, 등방 ‰ 정수).

렌더 배치 규약 (계약 3):
  - 슬라이드 16:9 고정 (EMU 12192000 × 6858000), 좌우 여백 2%.
  - scale = 슬라이드폭 × 0.96 / 1000  (x·y 동일 scale = 등방 유지).
  - 가로 = 좌측 2% 여백에서 시작, 세로 = 슬라이드 내 중앙정렬.
  - 안전장치: 세로형 캔버스(y 범위가 장축) 등으로 콘텐츠 높이가 슬라이드를
    벗어나면 scale을 슬라이드높이×0.96/y범위로 축소하고 가로도 중앙정렬한다.
    (16:9 계열 입력에서는 계약 공식 그대로 동작하며 이 분기는 타지 않음)
"""

# 슬라이드 크기 (16:9 고정)
SLIDE_W_EMU = 12192000
SLIDE_H_EMU = 6858000
MARGIN_RATIO = 0.02  # 좌우 여백 2%
LONG_AXIS = 1000     # 장축 ‰ 범위


def parse_aspect(aspect):
    """canvas.aspect 문자열 "W:H" → (w, h) 실수 튜플. 형식 오류 시 ValueError."""
    try:
        w_s, h_s = aspect.split(":")
        w, h = float(w_s), float(h_s)
    except (ValueError, AttributeError):
        raise ValueError(f"canvas.aspect 형식 오류: {aspect!r} (기대: 'W:H')")
    if w <= 0 or h <= 0:
        raise ValueError(f"canvas.aspect 값은 양수여야 함: {aspect!r}")
    return w, h


def canvas_extent(aspect):
    """종횡비 → (x_max, y_max) ‰ 범위. 장축 1000, 단축 round(1000×단/장).

    예: "16:9" → (1000, 563), "4:3" → (1000, 750), "9:16" → (563, 1000)
    """
    w, h = parse_aspect(aspect)
    long_side = max(w, h)
    x_max = round(LONG_AXIS * w / long_side)
    y_max = round(LONG_AXIS * h / long_side)
    return x_max, y_max


class CanvasTransform:
    """‰ → EMU 등방 변환기. from_ir()로 생성한다."""

    def __init__(self, x_max, y_max):
        self.x_max = x_max
        self.y_max = y_max
        # 계약 공식: scale = 슬라이드폭 × 0.96 / 1000 (장축 기준)
        scale = SLIDE_W_EMU * (1.0 - 2 * MARGIN_RATIO) / LONG_AXIS
        off_x = SLIDE_W_EMU * MARGIN_RATIO
        # 안전장치: 콘텐츠 높이가 슬라이드를 넘으면 높이 기준으로 재축소
        if y_max * scale > SLIDE_H_EMU:
            scale = SLIDE_H_EMU * (1.0 - 2 * MARGIN_RATIO) / y_max
            off_x = (SLIDE_W_EMU - x_max * scale) / 2.0  # 가로도 중앙정렬
        self.scale = scale
        self.off_x = off_x
        self.off_y = (SLIDE_H_EMU - y_max * scale) / 2.0  # 세로 중앙정렬

    @classmethod
    def from_ir(cls, ir):
        """IR dict의 canvas.aspect로 변환기 생성. canvas 누락 시 16:9 가정."""
        aspect = (ir.get("canvas") or {}).get("aspect", "16:9")
        return cls(*canvas_extent(aspect))

    # --- 좌표 변환 (모두 int EMU 반환) ---

    def x_emu(self, u):
        """‰ x 좌표 → EMU."""
        return int(round(self.off_x + u * self.scale))

    def y_emu(self, u):
        """‰ y 좌표 → EMU."""
        return int(round(self.off_y + u * self.scale))

    def len_emu(self, u):
        """‰ 길이 → EMU (오프셋 없음, x·y 공통 — 등방)."""
        return int(round(u * self.scale))

    def bbox_to_emu(self, bbox):
        """[x, y, w, h] ‰ → (left, top, width, height) EMU."""
        x, y, w, h = bbox
        return self.x_emu(x), self.y_emu(y), self.len_emu(w), self.len_emu(h)

    def point_to_emu(self, pt):
        """(x, y) ‰ → (x, y) EMU."""
        return self.x_emu(pt[0]), self.y_emu(pt[1])
