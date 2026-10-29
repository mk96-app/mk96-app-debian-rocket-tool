"""Motor de reglas: decide qué sonido distintivo (si alguno) corresponde a un evento
entrante de Rocket.Chat.

Tipos de regla:
- "sala": coincide por room_id (rid) exacto, sirve tanto para canales como para DMs 1:1.
- "mencion": regla global, coincide cuando el evento indica que el usuario fue
  mencionado, sin importar la sala. Con `mencion_todos` activo en la regla, también
  coincide con @all / @here (evento["mentioned_all"]).

Una regla de sala coincidente tiene prioridad sobre la de mención, para no sonar dos
veces ni tapar el sonido distintivo de un contacto clave con el genérico de mención.
"""


def match_rule(event: dict, rules: list) -> dict | None:
    active_rules = [rule for rule in rules if rule.get("activa", True)]

    for rule in active_rules:
        if rule["tipo"] == "sala" and rule["room_id"] == event.get("rid"):
            return rule

    for rule in active_rules:
        if rule["tipo"] != "mencion":
            continue
        if event.get("mentioned"):
            return rule
        if event.get("mentioned_all") and rule.get("mencion_todos"):
            return rule

    return None


def rooms_to_mark_read(subs: list, rules: list, solo_no_configuradas: bool) -> list:
    """Rids de las suscripciones con mensajes sin leer. Con `solo_no_configuradas`
    se descartan las salas con una regla de sala activa; una regla silenciada no
    cuenta como configurada, igual que en match_rule."""
    configuradas = {
        rule["room_id"]
        for rule in rules
        if rule["tipo"] == "sala" and rule.get("activa", True)
    }
    return [
        sub["rid"]
        for sub in subs
        if sub.get("rid")
        and (sub.get("unread", 0) > 0 or sub.get("alert"))
        and not (solo_no_configuradas and sub["rid"] in configuradas)
    ]
