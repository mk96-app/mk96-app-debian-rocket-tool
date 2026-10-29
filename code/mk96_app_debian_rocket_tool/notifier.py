"""Notificaciones de escritorio para eventos especiales de Rocket.Chat y avisos de
reuniones."""

from mk96_app_debian_rocket_tool.gtk_helpers import notify_message


def notify_special_message(etiqueta: str, sender: str, text: str) -> None:
    summary = f"{etiqueta}" if etiqueta else (sender or "Rocket.Chat")
    body = f"{sender}: {text}" if sender else (text or "")
    notify_message(summary, body, icon="mail-message-new")


def notify_meeting_reminder(titulo: str, hora_texto: str, enlace: str | None, momento: str = "hora") -> None:
    """momento: "aviso" (con antelación) u "hora" (justo cuando empieza) -ver
    meetings.due_meetings, que dispara ambos por separado cuando hay aviso previo. El
    enlace se muestra como texto informativo -abrirlo con un clic es una acción del
    menú de bandeja (ver tray.py), no de esta notificación."""
    summary = f"Reunión en breve: {titulo}" if momento == "aviso" else f"Reunión ahora: {titulo}"
    body = f"A las {hora_texto}"
    if enlace:
        body += f"\n{enlace}"
    notify_message(summary, body, icon="x-office-calendar")
