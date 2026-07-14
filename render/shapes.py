# 사용법 (렌더 파이프라인 내부 모듈 — 직접 실행하지 않음):
#   from render.shapes import add_node, add_container, add_legend, add_note
#   shape = add_node(slide, node_dict, tr)          # tr = CanvasTransform
"""노드·컨테이너·placeholder·legend·note를 pptx 도형으로 생성 (무스타일 스텁).

무스타일 규약 (계약 3): 흰 채움 · 검정 1pt 테두리 · 검정 10pt 텍스트.
role 필드는 스텁에서 스타일에 반영하지 않는다 (스타일 config는 M1 이후).

렌더 결정 고정 (ir/schema.md — AC1 카운팅 공식과 일치):
  - node(box/placeholder) = shape 1개, 텍스트는 자기 text_frame 인라인.
  - container = shape 1개, title도 자기 text_frame 인라인(좌상단 정렬).
  - placeholder = 점선 테두리 + "[수식]"/"[아이콘]" 표기.
  - legend = 배경 1 + 항목당 (스와치 사각형 + 라벨 텍스트박스) = 1 + 2N shape.
  - note = 텍스트박스 1개 (테두리·채움 없음).
"""

from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt

BLACK = RGBColor(0, 0, 0)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT_PT = 10          # 무스타일 고정 폰트 크기
LINE_PT = 1           # 무스타일 고정 테두리 두께
_TF_MARGIN = Emu(9525)  # text_frame 여백 0.75pt — 작은 박스에서 텍스트 공간 확보


def apply_base_style(shape):
    """무스타일 적용: 흰 채움 + 검정 1pt 실선 테두리."""
    shape.fill.solid()
    shape.fill.fore_color.rgb = WHITE
    shape.line.color.rgb = BLACK
    shape.line.width = Pt(LINE_PT)


def set_text(text_frame, text, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE):
    """text_frame에 검정 10pt 텍스트 설정. \\n은 문단 분리로 처리된다."""
    text_frame.word_wrap = True
    text_frame.vertical_anchor = anchor
    text_frame.margin_left = _TF_MARGIN
    text_frame.margin_right = _TF_MARGIN
    text_frame.margin_top = _TF_MARGIN
    text_frame.margin_bottom = _TF_MARGIN
    text_frame.text = text
    for para in text_frame.paragraphs:
        para.alignment = align
        for run in para.runs:
            run.font.size = Pt(FONT_PT)
            run.font.color.rgb = BLACK


def add_textbox(slide, text, left, top, width, height,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE):
    """테두리·채움 없는 순수 텍스트박스 (엣지 라벨·legend 라벨·note 공용)."""
    box = slide.shapes.add_textbox(left, top, width, height)
    set_text(box.text_frame, text, align=align, anchor=anchor)
    return box


def add_node(slide, node, tr):
    """nodes[] 원소 1개 → 사각형 shape 1개.

    kind == "placeholder"면 점선 테두리 + placeholder_kind에 따라
    "[수식]"/"[아이콘]" 마커를 텍스트 앞에 붙인다 (자동 변환 없음, 자리 표시만).
    """
    left, top, width, height = tr.bbox_to_emu(node["bbox"])
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    apply_base_style(shape)

    text = node.get("text", "")
    if node.get("kind") == "placeholder":
        shape.line.dash_style = MSO_LINE.DASH  # 점선 테두리
        marker = {"equation": "[수식]", "icon": "[아이콘]"}.get(
            node.get("placeholder_kind"), "[자리]")
        text = f"{marker} {text}".strip()
    set_text(shape.text_frame, text)
    return shape


def add_container(slide, container, tr):
    """containers[] 원소 1개 → 배경 사각형 shape 1개 (비그룹).

    title은 별도 텍스트박스 없이 자기 text_frame 인라인, 좌상단 정렬
    (ir/schema.md 렌더 결정: container = 1 shape).
    """
    left, top, width, height = tr.bbox_to_emu(container["bbox"])
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    apply_base_style(shape)
    set_text(shape.text_frame, container.get("title", ""),
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)
    return shape


def add_note(slide, annotation, tr):
    """annotations[] kind=="note" → 텍스트박스 1개 (테두리·채움 없음)."""
    left, top, width, height = tr.bbox_to_emu(annotation["bbox"])
    return add_textbox(slide, annotation.get("text", ""),
                       left, top, width, height,
                       align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)


# legend 내부 배치 파라미터 (‰ 단위)
_LEGEND_PAD = 6        # bbox 내부 패딩
_SWATCH_MAX = 18       # 스와치 한 변 최대


def add_legend(slide, annotation, tr):
    """annotations[] kind=="legend" → 배경 1 + 항목당 (스와치 + 라벨) = 1+2N shape.

    항목은 bbox 안에서 세로로 균등 분할해 쌓는다. 스와치는 각 행 왼쪽의
    정사각형(무스타일 흰 채움 — 실제 색은 스타일 config 몫), 라벨은 그 오른쪽
    텍스트박스. 생성한 shape 리스트를 반환한다.
    """
    x, y, w, h = annotation["bbox"]
    shapes = []

    # 배경 사각형
    left, top, width, height = tr.bbox_to_emu([x, y, w, h])
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    apply_base_style(bg)
    shapes.append(bg)

    items = annotation.get("items", [])
    if not items:
        return shapes

    inner_x = x + _LEGEND_PAD
    inner_y = y + _LEGEND_PAD
    inner_w = max(w - 2 * _LEGEND_PAD, 1)
    inner_h = max(h - 2 * _LEGEND_PAD, 1)
    row_h = inner_h / len(items)
    swatch = min(_SWATCH_MAX, row_h * 0.6, inner_w * 0.3)
    swatch = max(swatch, 2)  # 극소 bbox 방어

    for i, item_text in enumerate(items):
        row_y = inner_y + i * row_h
        # 스와치: 행 왼쪽 세로 중앙의 정사각형
        s_left = tr.x_emu(inner_x)
        s_top = tr.y_emu(row_y + (row_h - swatch) / 2)
        s_side = tr.len_emu(swatch)
        sw = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, s_left, s_top, s_side, s_side)
        apply_base_style(sw)
        shapes.append(sw)
        # 라벨: 스와치 오른쪽 나머지 폭
        l_left = tr.x_emu(inner_x + swatch + 3)
        l_top = tr.y_emu(row_y)
        l_width = tr.len_emu(max(inner_w - swatch - 3, 1))
        l_height = tr.len_emu(row_h)
        shapes.append(add_textbox(slide, item_text, l_left, l_top, l_width, l_height,
                                  align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE))
    return shapes
