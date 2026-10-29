import os
import time

from mk96_app_debian_rocket_tool import sound_manager
from mk96_app_debian_rocket_tool.sound_manager import (
    list_default_sounds,
    list_user_sounds,
    resolve_sound_path,
    sonido_display_name,
)


def test_resolve_prefers_custom_dir_over_bundled(tmp_path):
    custom_dir = tmp_path / "custom"
    bundled_dir = tmp_path / "bundled"
    custom_dir.mkdir()
    bundled_dir.mkdir()
    (custom_dir / "cat.ogg").write_bytes(b"custom")
    (bundled_dir / "cat.ogg").write_bytes(b"bundled")

    result = resolve_sound_path("cat", str(custom_dir), str(bundled_dir))
    assert result == str(custom_dir / "cat.ogg")


def test_resolve_falls_back_to_bundled_dir(tmp_path):
    custom_dir = tmp_path / "custom"
    bundled_dir = tmp_path / "bundled"
    custom_dir.mkdir()
    bundled_dir.mkdir()
    (bundled_dir / "dog.wav").write_bytes(b"bundled")

    result = resolve_sound_path("dog", str(custom_dir), str(bundled_dir))
    assert result == str(bundled_dir / "dog.wav")


def test_resolve_returns_none_when_missing_everywhere(tmp_path):
    custom_dir = tmp_path / "custom"
    bundled_dir = tmp_path / "bundled"
    custom_dir.mkdir()
    bundled_dir.mkdir()

    assert resolve_sound_path("ghost", str(custom_dir), str(bundled_dir)) is None


def test_resolve_ignores_nonexistent_directories(tmp_path):
    missing_custom = tmp_path / "no-custom"
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    (bundled_dir / "owl.mp3").write_bytes(b"bundled")

    result = resolve_sound_path("owl", str(missing_custom), str(bundled_dir))
    assert result == str(bundled_dir / "owl.mp3")


def test_list_default_sounds_groups_by_category_subfolder(tmp_path):
    (tmp_path / "digital-audio").mkdir()
    (tmp_path / "digital-audio" / "highDown.ogg").write_bytes(b"x")
    (tmp_path / "impact-sounds").mkdir()
    (tmp_path / "impact-sounds" / "hit1.ogg").write_bytes(b"x")

    result = list_default_sounds(str(tmp_path))
    assert {"sonido_id": "digital-audio/highDown", "categoria": "digital-audio", "nombre": "highDown", "origen": "default"} in result
    assert {"sonido_id": "impact-sounds/hit1", "categoria": "impact-sounds", "nombre": "hit1", "origen": "default"} in result
    assert len(result) == 2


def test_list_default_sounds_ignores_non_audio_files(tmp_path):
    (tmp_path / "digital-audio").mkdir()
    (tmp_path / "digital-audio" / "License.txt").write_text("cc0")
    (tmp_path / "digital-audio" / "highDown.ogg").write_bytes(b"x")

    result = list_default_sounds(str(tmp_path))
    assert len(result) == 1
    assert result[0]["nombre"] == "highDown"


def test_list_default_sounds_empty_when_missing_dir(tmp_path):
    assert list_default_sounds(str(tmp_path / "does-not-exist")) == []


def test_list_user_sounds_is_flat_with_own_category_label(tmp_path):
    (tmp_path / "mi-sonido.ogg").write_bytes(b"x")

    result = list_user_sounds(str(tmp_path))
    assert result == [
        {"sonido_id": "mi-sonido", "categoria": "Tus sonidos", "nombre": "mi-sonido", "origen": "user"}
    ]


def test_list_user_sounds_empty_when_missing_dir(tmp_path):
    assert list_user_sounds(str(tmp_path / "does-not-exist")) == []


def test_sonido_display_name_strips_category():
    assert sonido_display_name("digital-audio/highDown") == "highDown"


def test_sonido_display_name_keeps_flat_ids_unchanged():
    assert sonido_display_name("mi-sonido") == "mi-sonido"


def test_play_sound_does_not_block_the_caller(tmp_path, monkeypatch):
    """play_sound() se llama desde el hilo principal de GTK (poller/rules); si espera a
    que el audio termine de sonar, bloquea toda la UI mientras dura la reproducción."""
    sound_file = tmp_path / "cat.ogg"
    sound_file.write_bytes(b"x")
    monkeypatch.setattr(sound_manager, "resolve_sound_path", lambda sonido_id: str(sound_file))

    fake_paplay = tmp_path / "paplay"
    fake_paplay.write_text("#!/bin/sh\nsleep 2\n")
    fake_paplay.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    start = time.monotonic()
    sound_manager.play_sound("cat")
    elapsed = time.monotonic() - start

    assert elapsed < 1.0
