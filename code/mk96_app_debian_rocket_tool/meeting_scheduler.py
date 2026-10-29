"""Planificador de avisos de reuniones: temporizador GLib independiente del Poller de
Rocket.Chat -funciona sin servidor conectado. La lógica de qué reuniones están debidas
vive en meetings.due_meetings (pura); esta clase solo la orquesta con el temporizador.
Al arrancar se recuperan además los avisos cuya ventana de antelación ya se había
abierto antes de iniciar la aplicación, para no perderlos silenciosamente.
"""

from datetime import datetime

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from mk96_app_debian_rocket_tool.meetings import due_meetings, startup_due_meetings

DEFAULT_CHECK_INTERVAL_S = 30


class MeetingScheduler:
    def __init__(self, get_meetings, on_due, on_tick=None, check_interval_s=DEFAULT_CHECK_INTERVAL_S):
        """get_meetings() -> list de reuniones actuales (se llama en cada tick, para ver
        siempre la config más reciente). on_due(meeting, ocurrencia, momento) se llama
        por cada aviso que toca disparar (momento: "aviso" o "hora" -ver
        meetings.due_meetings). on_tick(), si se da, se llama en cada tick tras
        procesar los avisos -para refrescar UI derivada (p.ej. "próximas reuniones")
        aunque no haya ningún aviso nuevo."""
        self._get_meetings = get_meetings
        self._on_due = on_due
        self._on_tick = on_tick or (lambda: None)
        self._check_interval_s = check_interval_s
        self._ultimo_chequeo = None
        self._timeout_id = None

    def start(self) -> None:
        self._ultimo_chequeo = datetime.now()
        try:
            recuperados = startup_due_meetings(self._get_meetings(), self._ultimo_chequeo)
        except Exception:
            recuperados = []
        for meeting, ocurrencia, momento in recuperados:
            # Cada aviso de recuperación se aísla: uno mal formado no debe impedir
            # que el resto (ni el arranque del temporizador de abajo) siga adelante.
            try:
                self._on_due(meeting, ocurrencia, momento)
            except Exception:
                pass
        self._timeout_id = GLib.timeout_add_seconds(self._check_interval_s, self._tick)

    def stop(self) -> None:
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None

    def _tick(self) -> bool:
        ahora = datetime.now()
        # Una sola reunión mal formada no puede tumbar el temporizador: si _tick lanza,
        # GLib retira la fuente y no vuelve a haber avisos en toda la sesión.
        try:
            for meeting, ocurrencia, momento in due_meetings(
                self._get_meetings(), ahora, self._ultimo_chequeo
            ):
                self._on_due(meeting, ocurrencia, momento)
        except Exception:
            pass
        self._ultimo_chequeo = ahora
        self._on_tick()
        return GLib.SOURCE_CONTINUE
