"""Shared validation helpers for ManiaPlanet runtime data."""

from dataclasses import dataclass
import re


LOGIN = re.compile(r'[A-Za-z0-9_.@-]{1,100}')
UID = re.compile(r'[A-Za-z0-9_-]{1,64}')


class ControllerError(ValueError):
    """The ManiaPlanet controller cannot run under the current conditions."""


def safe_login(value):
    return value if isinstance(value, str) and LOGIN.fullmatch(value) else None


@dataclass(frozen=True)
class Course:
    uid: str
    name: str
    checkpoints: int


def course_from_rpc(data):
    if not isinstance(data, dict):
        return None
    uid = data.get('Uid') or data.get('UId')
    count = data.get('NbCheckpoints')
    if not isinstance(uid, str) or not UID.fullmatch(uid) or type(count) is not int or not 1 <= count <= 5000:
        return None
    name = data.get('Name')
    return Course(uid, name if isinstance(name, str) else uid, count)
