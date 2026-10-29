"""Resuelve un sonido_id a un fichero de audio real y lo reproduce.

Filosofía "shell-out a herramienta CLI", igual que switchboard usa `pactl` para audio: aquí
se llama a `paplay` en vez de reimplementar reproducción de audio con bindings GStreamer.
"""

import os
import shutil
import subprocess

SOUND_EXTENSIONS = (".ogg", ".wav", ".mp3")

# sounds/default/<categoria>/<fichero>: paleta CC0 empaquetada con la app (ver LICENSES.md).
BUNDLED_SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "sounds", "default")
# sounds/user/<fichero>: sonidos que el propio usuario añade. Vive en el HOME, no en el
# árbol del paquete, para que sobreviva a actualizaciones/reinstalaciones del .deb.
USER_SOUNDS_DIR = os.path.join(
    os.path.expanduser("~"), ".local", "share", "mk96-app-debian-rocket-tool", "sounds", "user"
)


def sonido_display_name(sonido_id: str) -> str:
    """Lógica pura: nombre legible de un sonido_id para la UI ('categoria/nombre' ->
    'nombre'; los sonidos propios, sin categoría, se muestran tal cual)."""
    return sonido_id.rsplit("/", 1)[-1]


def resolve_sound_path(
    sonido_id: str, user_dir: str = USER_SOUNDS_DIR, bundled_dir: str = BUNDLED_SOUNDS_DIR
) -> str | None:
    for directory in (user_dir, bundled_dir):
        if not os.path.isdir(directory):
            continue
        for extension in SOUND_EXTENSIONS:
            candidate = os.path.join(directory, sonido_id + extension)
            if os.path.isfile(candidate):
                return candidate
    return None


def list_default_sounds(base_dir: str = BUNDLED_SOUNDS_DIR) -> list:
    """Sonidos de la paleta empaquetada, agrupados por categoría (una subcarpeta por
    categoría bajo sounds/default/)."""
    if not os.path.isdir(base_dir):
        return []

    result = []
    for categoria in sorted(os.listdir(base_dir)):
        categoria_dir = os.path.join(base_dir, categoria)
        if not os.path.isdir(categoria_dir):
            continue
        for filename in sorted(os.listdir(categoria_dir)):
            nombre, extension = os.path.splitext(filename)
            if extension.lower() not in SOUND_EXTENSIONS:
                continue
            result.append(
                {
                    "sonido_id": f"{categoria}/{nombre}",
                    "categoria": categoria,
                    "nombre": nombre,
                    "origen": "default",
                }
            )
    return result


def list_user_sounds(base_dir: str = USER_SOUNDS_DIR) -> list:
    """Sonidos propios añadidos por el usuario, sin categoría (carpeta plana)."""
    if not os.path.isdir(base_dir):
        return []

    result = []
    for filename in sorted(os.listdir(base_dir)):
        nombre, extension = os.path.splitext(filename)
        if extension.lower() not in SOUND_EXTENSIONS:
            continue
        result.append(
            {"sonido_id": nombre, "categoria": "Tus sonidos", "nombre": nombre, "origen": "user"}
        )
    return result


def list_available_sounds() -> list:
    return list_user_sounds() + list_default_sounds()


class SoundPlaybackError(Exception):
    """`paplay` no está disponible o devolvió un error."""


def play_sound(sonido_id: str) -> None:
    """Lanza `paplay` en background y vuelve enseguida -esto se llama desde el bucle
    principal de GTK (poller/reglas); esperar a que termine de sonar bloquearía toda
    la UI mientras dura la reproducción."""
    path = resolve_sound_path(sonido_id)
    if path is None:
        raise SoundPlaybackError(f"No se encontró ningún fichero de audio para '{sonido_id}'")
    try:
        subprocess.Popen(["paplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise SoundPlaybackError(str(exc)) from exc


def add_custom_sound(source_path: str, sonido_id: str) -> str:
    """Copia un fichero de audio elegido por el usuario a sounds/user/, para que quede
    disponible en el selector y sobreviva a actualizaciones/reinstalaciones del .deb."""
    os.makedirs(USER_SOUNDS_DIR, exist_ok=True)
    extension = os.path.splitext(source_path)[1].lower()
    if extension not in SOUND_EXTENSIONS:
        raise ValueError(f"Formato de audio no soportado: {extension}")

    destination = os.path.join(USER_SOUNDS_DIR, sonido_id + extension)
    shutil.copyfile(source_path, destination)
    return destination
