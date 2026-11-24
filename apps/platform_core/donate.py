"""Donation defaults and chat helpers used by ManiaPlanet billing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


_mindonation = 10
_publicappr = 100
donation_values = [20, 50, 100, 200, 500, 1000, 2000]

ML_ID_PAYMENT = 2800000


def register(aseco: "Aseco"):
    from .mp_planets import register as register_planets

    register_planets(aseco)


async def _send_login(aseco: "Aseco", login: str, message: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessageToLogin",
        aseco.format_colors(message),
        login,
    )


async def _send_all(aseco: "Aseco", message: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessage",
        aseco.format_colors(message),
    )


