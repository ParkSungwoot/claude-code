"""Every keyboard-triggered action with its default shortcut.

The main window turns each entry into a QAction; users can change the keys in the
hotkey editor (stored in Prefs.hotkeys as {action id: key sequence text}).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionDef:
    id: str
    label: str
    category: str
    default: str = ""
    icon: str = ""
    checkable: bool = False


ACTIONS: list[ActionDef] = [
    # File
    ActionDef("file.open", "파일 열기…", "파일", "Ctrl+O", "folder-open"),
    ActionDef("file.open_folder", "폴더 열기…", "파일", "Ctrl+Shift+O", "folder-open"),
    ActionDef("file.open_audio", "오디오 파일 연결…", "파일", "", "audio"),
    ActionDef("file.open_session", "세션 열기…", "파일", "Ctrl+Alt+O", "save"),
    ActionDef("file.save_session", "세션 저장", "파일", "Ctrl+S", "save"),
    ActionDef("file.save_session_as", "세션을 다른 이름으로 저장…", "파일", "Ctrl+Alt+S", "save"),
    ActionDef("file.save_frame", "현재 프레임 저장…", "파일", "Ctrl+Shift+S", "camera"),
    ActionDef("file.export", "동영상/시퀀스로 내보내기…", "파일", "Ctrl+E", "export"),
    ActionDef("file.export_pdf", "주석을 PDF로 내보내기…", "파일", "", "pdf"),
    ActionDef("file.reload", "다시 불러오기 (디스크 새로고침)", "파일", "F5", "refresh"),
    ActionDef("file.close", "현재 클립 닫기", "파일", "Ctrl+W", "close"),
    ActionDef("file.close_all", "모두 닫기", "파일", "Ctrl+Shift+W", "close"),
    ActionDef("file.reveal", "탐색기에서 폴더 열기", "파일", "", "folder-open"),
    ActionDef("file.copy_path", "파일 경로 복사", "파일", "", "link"),
    ActionDef("file.quit", "끝내기", "파일", "Ctrl+Q"),

    # Playback
    ActionDef("play.toggle", "재생 / 정지", "재생", "Space", "play"),
    ActionDef("play.forward", "앞으로 재생", "재생", "Up", "play"),
    ActionDef("play.backward", "거꾸로 재생", "재생", "Down", "play-reverse"),
    ActionDef("play.stop", "정지", "재생", "K", "stop"),
    ActionDef("play.jkl_forward", "앞으로 재생 (L)", "재생", "L"),
    ActionDef("play.jkl_backward", "거꾸로 재생 (J)", "재생", "J"),
    ActionDef("play.next_frame", "다음 프레임", "재생", "Right", "step-forward"),
    ActionDef("play.prev_frame", "이전 프레임", "재생", "Left", "step-back"),
    ActionDef("play.next_10", "10프레임 앞으로", "재생", "Shift+Right"),
    ActionDef("play.prev_10", "10프레임 뒤로", "재생", "Shift+Left"),
    ActionDef("play.start", "처음으로", "재생", "Home", "skip-start"),
    ActionDef("play.end", "끝으로", "재생", "End", "skip-end"),
    ActionDef("play.set_in", "시작점(In) 지정", "재생", "I", "in-point"),
    ActionDef("play.set_out", "끝점(Out) 지정", "재생", "O", "out-point"),
    ActionDef("play.clear_in", "시작점 지우기", "재생", "Shift+I"),
    ActionDef("play.clear_out", "끝점 지우기", "재생", "Shift+O"),
    ActionDef("play.clear_range", "시작/끝점 모두 지우기", "재생", "Alt+X", "clear-range"),
    ActionDef("play.loop_cycle", "반복 방식 바꾸기 (반복/한 번/왕복)", "재생", "Ctrl+L", "loop"),
    ActionDef("play.goto", "프레임으로 이동…", "재생", "Ctrl+G"),
    ActionDef("play.faster", "FPS 올리기", "재생", "Ctrl+Up"),
    ActionDef("play.slower", "FPS 내리기", "재생", "Ctrl+Down"),
    ActionDef("play.mute", "소리 끄기/켜기", "재생", "Ctrl+M", "volume-mute"),

    # Clips
    ActionDef("clip.next", "다음 클립", "클립", "Page Down", "next-clip"),
    ActionDef("clip.prev", "이전 클립", "클립", "Page Up", "prev-clip"),
    ActionDef("clip.next_version", "다음 버전 (v###)", "클립", "Ctrl+Page Up", "version-up"),
    ActionDef("clip.prev_version", "이전 버전 (v###)", "클립", "Ctrl+Page Down", "version-down"),
    ActionDef("clip.set_b", "현재 클립을 B로 지정", "클립", "Ctrl+B", "b-letter"),

    # Compare
    ActionDef("compare.A", "A만 보기", "비교", "Ctrl+1", "a-letter"),
    ActionDef("compare.B", "B만 보기", "비교", "Ctrl+2", "b-letter"),
    ActionDef("compare.wipe", "와이프", "비교", "W", "wipe"),
    ActionDef("compare.overlay", "오버레이", "비교", "Ctrl+3", "overlay"),
    ActionDef("compare.difference", "차이", "비교", "Ctrl+4", "difference"),
    ActionDef("compare.horizontal", "좌우 나란히", "비교", "Ctrl+5", "side-by-side"),
    ActionDef("compare.vertical", "위아래 나란히", "비교", "Ctrl+6", "top-bottom"),
    ActionDef("compare.tile", "타일", "비교", "Ctrl+7", "tile"),
    ActionDef("compare.swap", "A와 B 바꾸기", "비교", "Ctrl+Shift+B"),

    # View
    ActionDef("view.fit", "화면에 맞추기", "보기", "F", "fit"),
    ActionDef("view.zoom_1", "100% (1:1)", "보기", "1", "one-to-one"),
    ActionDef("view.zoom_2", "200%", "보기", "2"),
    ActionDef("view.zoom_half", "50%", "보기", "0"),
    ActionDef("view.zoom_in", "확대", "보기", "=", "zoom-in"),
    ActionDef("view.zoom_out", "축소", "보기", "-", "zoom-out"),
    ActionDef("view.center", "가운데로", "보기", "H"),
    ActionDef("view.mirror_x", "좌우 뒤집기", "보기", "Shift+X", "mirror-h", True),
    ActionDef("view.mirror_y", "상하 뒤집기", "보기", "Shift+Y", "mirror-v", True),
    ActionDef("view.rotate_cw", "시계 방향 90° 회전", "보기", "Ctrl+R", "rotate-cw"),
    ActionDef("view.rotate_ccw", "반시계 방향 90° 회전", "보기", "Ctrl+Shift+R", "rotate-ccw"),
    ActionDef("view.fullscreen", "전체 화면", "보기", "F11", "fullscreen", True),
    ActionDef("view.presentation", "프레젠테이션 모드", "보기", "F12", "presentation", True),
    ActionDef("view.on_top", "항상 위에 표시", "보기", "", "pin", True),
    ActionDef("view.hud", "HUD 정보 표시", "보기", "Ctrl+H", "hud", True),
    ActionDef("view.safe_areas", "안전 영역", "보기", "Ctrl+'", "safe-area", True),
    ActionDef("view.display_window", "디스플레이 윈도우 표시", "보기", "", "", True),
    ActionDef("view.data_window", "데이터 윈도우 표시", "보기", "", "", True),
    ActionDef("view.filter", "부드럽게 확대 (선형 필터)", "보기", "Ctrl+Shift+F", "", True),
    ActionDef("view.env_map", "360° 파노라마(환경 맵) 보기", "보기", "", "globe", True),
    ActionDef("view.side_panel", "사이드 패널 보이기/숨기기", "보기", "Tab", "playlist", True),
    ActionDef("view.timeline", "타임라인 보이기/숨기기", "보기", "Ctrl+T", "", True),

    # Color / channels
    ActionDef("ch.rgb", "컬러 (RGB)", "채널", "C", "channels"),
    ActionDef("ch.r", "빨강 채널", "채널", "R"),
    ActionDef("ch.g", "초록 채널", "채널", "G"),
    ActionDef("ch.b", "파랑 채널", "채널", "B"),
    ActionDef("ch.a", "알파 채널", "채널", "A", "alpha"),
    ActionDef("ch.luma", "휘도 (Luminance)", "채널", "Y"),
    ActionDef("ch.next_layer", "다음 레이어", "채널", "Ctrl+]"),
    ActionDef("ch.prev_layer", "이전 레이어", "채널", "Ctrl+["),
    ActionDef("color.exposure_up", "노출 +½ 스톱", "색", "]"),
    ActionDef("color.exposure_down", "노출 −½ 스톱", "색", "["),
    ActionDef("color.exposure_reset", "노출 초기화", "색", "\\"),
    ActionDef("color.gamma_up", "감마 올리기", "색", "}"),
    ActionDef("color.gamma_down", "감마 내리기", "색", "{"),
    ActionDef("color.reset", "색 조정 모두 초기화", "색", "Ctrl+\\"),

    # Annotation
    ActionDef("draw.none", "선택/이동 도구", "주석", "V", "hand"),
    ActionDef("draw.pen", "펜", "주석", "P", "pen"),
    ActionDef("draw.eraser", "지우개", "주석", "E", "eraser"),
    ActionDef("draw.line", "직선", "주석", "Shift+L", "line"),
    ActionDef("draw.arrow", "화살표", "주석", "Shift+A", "arrow"),
    ActionDef("draw.rect", "사각형", "주석", "Shift+R", "rect"),
    ActionDef("draw.ellipse", "원", "주석", "Shift+C", "ellipse"),
    ActionDef("draw.text", "텍스트", "주석", "T", "text"),
    ActionDef("draw.area", "영역 선택 (색 정보)", "주석", "Shift+M", "select-area"),
    ActionDef("draw.undo", "주석 실행 취소", "주석", "Ctrl+Z", "undo"),
    ActionDef("draw.redo", "주석 다시 실행", "주석", "Ctrl+Shift+Z", "redo"),
    ActionDef("draw.clear_frame", "현재 프레임 주석 지우기", "주석", "Ctrl+Backspace", "trash"),
    ActionDef("draw.next", "다음 주석 프레임", "주석", "Ctrl+Right", "marker"),
    ActionDef("draw.prev", "이전 주석 프레임", "주석", "Ctrl+Left", "marker"),
    ActionDef("draw.toggle", "주석 보이기/숨기기", "주석", "Ctrl+Shift+H", "eye", True),

    # Panels / windows
    ActionDef("panel.playlist", "플레이리스트", "패널", "Alt+1", "playlist"),
    ActionDef("panel.color", "색 보정", "패널", "Alt+2", "palette"),
    ActionDef("panel.compare", "비교", "패널", "Alt+3", "compare"),
    ActionDef("panel.annotate", "주석", "패널", "Alt+4", "pen"),
    ActionDef("panel.info", "미디어 정보", "패널", "Alt+5", "info"),
    ActionDef("panel.scopes", "스코프", "패널", "Alt+6", "histogram"),
    ActionDef("panel.area", "영역 색 정보", "패널", "Alt+7", "color-area"),
    ActionDef("panel.env", "환경 맵", "패널", "", "globe"),
    ActionDef("panel.logs", "로그", "패널", "", "terminal"),
    ActionDef("app.preferences", "환경 설정…", "창", "Ctrl+,", "settings"),
    ActionDef("app.hotkeys", "단축키 편집…", "창", "F1", "keyboard"),
    ActionDef("app.about", "COC_SEQ Player 정보", "창", ""),
]

BY_ID = {a.id: a for a in ACTIONS}


def shortcut_for(action_id: str, overrides: dict) -> str:
    if action_id in overrides:
        return overrides[action_id]
    a = BY_ID.get(action_id)
    return a.default if a else ""
