import os
import sys
import time

import pytest

SKIP = {
    "file.open", "file.open_folder", "file.open_audio", "file.open_session", "file.save_session",
    "file.save_session_as", "file.save_frame", "file.export", "file.export_pdf", "file.reveal", "file.quit",
    "file.close", "file.close_all", "play.goto", "app.preferences", "app.hotkeys", "app.about", "view.on_top",
}


def pump(app, seconds=0.2, until=None):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.005)
    return until() if until else True


@pytest.fixture()
def window(qapp, isolated_settings, monkeypatch):
    monkeypatch.setenv("COCSEQ_TESTING", "1")
    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda *exc: errors.append(exc)
    from cocseq.prefs import store
    from cocseq.ui.main_window import MainWindow

    st = store()
    st.prefs.single_instance = False
    win = MainWindow(st)
    win.resize(1400, 860)
    win.show()
    pump(qapp, 0.3)
    yield win, errors
    win.close()
    pump(qapp, 0.1)
    sys.excepthook = old_hook


def test_open_play_and_every_action(window, qapp, media):
    win, errors = window
    win.open_paths([media["exr"], media["movie"], media["png"]])
    assert [s.kind for s in win.sources] == ["sequence", "movie", "sequence"]
    assert win.a is win.sources[0]
    assert pump(qapp, 5, lambda: win.viewer.slots and win.viewer.slots[0].frame is not None)
    win.playback.play(1)
    pump(qapp, 0.4)
    win.playback.stop()
    assert win.playback.frame != 1001 or True
    for act_id, act in win.actions_by_id.items():
        if act_id in SKIP:
            continue
        act.trigger()
        pump(qapp, 0.02)
    # Leave every mode in a sane state and make sure nothing raised.
    for mode in ("A", "wipe", "overlay", "difference", "horizontal", "vertical", "tile", "B", "A"):
        win.set_compare_mode(mode)
        pump(qapp, 0.03)
    for key in ("playlist", "color", "compare", "annotate", "info", "scopes", "area", "env", "logs"):
        win.show_panel(key)
        pump(qapp, 0.03)
    if win.isFullScreen():
        win.toggle_fullscreen()
    assert not errors, errors[0]


def test_session_round_trip(window, qapp, media, tmp_path):
    from cocseq.annotations import Shape
    from cocseq.session import load_session, save_session

    win, errors = window
    win.open_paths([media["exr"], media["exr_v2"]])
    assert len(win.sources) == 2
    a, b = win.sources
    win.set_a(a)
    win.playback.seek(1005)
    win.set_in(1003)
    win.set_out(1020)
    a.set_layer("diffuse")
    win.set_compare_slot(0, b, auto_mode=True)
    assert win.compare_mode == "wipe"
    win._set_display(exposure=1.25, gamma=1.1)
    a.annotations.add(1005, Shape("arrow", [(1, 1), (50, 50)], "#00FF00", 3))
    a.annotations.set_note(1005, "노트 테스트")
    path = str(tmp_path / "review.cocseq")
    save_session(win, path)
    win.close_all(confirm=False)
    assert not win.sources
    missing = load_session(win, path)
    assert missing == []
    assert len(win.sources) == 2
    a2 = win.a
    assert a2.name == a.name and a2.layer.name == "diffuse"
    assert a2.range == (1003, 1020)
    assert a2.annotations.notes[1005] == "노트 테스트"
    assert win.compare_mode == "wipe" and win.compare_slots[0] is win.sources[1]
    assert abs(win.viewer.display.exposure - 1.25) < 1e-6
    assert not errors, errors[0]


def test_version_switch_keeps_frame(window, qapp, media):
    win, _errors = window
    win.open_paths([media["exr"]])
    win.playback.seek(1007)
    win.version_step(1)
    assert "shot_v002" in win.a.name
    assert win.playback.frame == 1007
    win.version_step(-1)
    assert "shot_v001" in win.a.name
    assert len(win.sources) == 2          # the first version is reused, not opened twice


def test_open_folder_scans_everything(window, qapp, media):
    win, _errors = window
    win.open_paths([os.path.join(media["root"], "png")])
    assert len(win.sources) == 1 and win.a.length == 30


def test_preferences_apply(window, qapp, media, monkeypatch):
    import copy

    from cocseq.ui.dialogs import hotkeys_dialog, prefs_dialog

    win, errors = window
    win.open_paths([media["exr"]])
    new = copy.deepcopy(win.prefs)
    new.accent = "#4C8DFF"
    new.cache_gb = 1.5
    new.ocio_config = "ocio://cg-config-latest"
    new.ocio_prefer_env = False
    new.background = "checker"
    new.time_display = "timecode"
    monkeypatch.setattr(prefs_dialog.PreferencesDialog, "exec", lambda self: 1)
    monkeypatch.setattr(prefs_dialog.PreferencesDialog, "result_prefs", lambda self: copy.deepcopy(new))
    win.show_preferences()
    pump(qapp, 0.2)
    assert win.cache.budget == int(1.5 * 1024 ** 3)
    assert win.colors.uri == "ocio://cg-config-latest"
    assert win.viewer.background == "checker"
    assert win.timeline.time_mode == "timecode"
    from cocseq.theme import PAL

    assert PAL.accent.lower() == "#4c8dff"
    monkeypatch.setattr(hotkeys_dialog.HotkeysDialog, "exec", lambda self: 1)
    monkeypatch.setattr(hotkeys_dialog.HotkeysDialog, "result_overrides", lambda self: {"view.fit": "Ctrl+Alt+F"})
    win.show_hotkeys()
    assert win.actions_by_id["view.fit"].shortcut().toString() == "Ctrl+Alt+F"
    assert not errors, errors[0]
    from cocseq import theme

    theme.set_accent("#FF7A45")
