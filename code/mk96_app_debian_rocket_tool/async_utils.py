"""Ejecuta trabajo bloqueante (peticiones REST) fuera del hilo de GTK y entrega el
resultado de vuelta en el bucle principal -nunca se toca la UI desde el hilo."""

import threading

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib


def run_in_thread(work, on_done) -> None:
    """Llama a work() en un hilo; después on_done(resultado, error) en el hilo principal
    (error es la excepción si work falló, y resultado None)."""

    def runner():
        try:
            result, error = work(), None
        except Exception as exc:  # noqa: BLE001 - se entrega a on_done, que decide
            result, error = None, exc

        def deliver():
            on_done(result, error)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(deliver)

    threading.Thread(target=runner, daemon=True).start()
