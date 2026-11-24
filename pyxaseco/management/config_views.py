"""Shared table discovery and sizing for the two admin configuration views."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyxaseco.models import Gameinfo

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def _read_nested(data: Any, path: tuple[str, ...]) -> Any:
    node = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _format_config_label(parts: tuple[str, ...]) -> str:
    text = ' / '.join(str(part).replace('_', ' ').strip() for part in parts if str(part).strip())
    return text.title() if text else 'Config'


def discover_table_items(
    aseco: 'Aseco',
    file_path: Path,
    root_table: tuple[str, ...],
    data: dict[str, Any],
    *,
    label_prefix: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    root = _read_nested(data, root_table)
    if not isinstance(root, dict):
        return []

    file_name = str(file_path.relative_to(Path(str(getattr(aseco, 'base_dir', Path.cwd()))))).replace('\\', '/')
    items: list[dict[str, Any]] = []

    def visit(path_parts: tuple[str, ...], table: dict[str, Any], labels: tuple[str, ...]) -> None:
        scalar_keys = [key for key, value in table.items() if not isinstance(value, dict)]
        if scalar_keys:
            rel_parts = path_parts if path_parts else (root_table[-1],)
            items.append({
                'key': '.'.join(rel_parts),
                'label': _format_config_label(labels or rel_parts[-1:]),
                'file': file_name,
                'table_path': root_table + path_parts,
            })
        for key, value in table.items():
            if isinstance(value, dict):
                visit(path_parts + (key,), value, labels + (key,))

    visit((), root, label_prefix)
    return items


def current_ui_mode_key(aseco: 'Aseco') -> str | None:
    mode = getattr(getattr(aseco.server, 'gameinfo', None), 'mode', -1)
    try:
        from apps.ui.config import _effective_mode
        mode = _effective_mode(aseco)
    except Exception:
        pass

    mapping = {
        Gameinfo.RNDS: 'rounds',
        Gameinfo.TA: 'time_attack',
        Gameinfo.TEAM: 'team',
        Gameinfo.LAPS: 'laps',
        Gameinfo.STNT: 'stunts',
        Gameinfo.CUP: 'cup',
        Gameinfo.SCOR: 'score',
    }
    return mapping.get(int(mode)) if isinstance(mode, int) else None


def autosize_widths(
    table_header: list[str],
    entries: list[list[Any]],
    *,
    min_total: float = 1.08,
    max_total: float = 1.38,
) -> list[float]:
    if not table_header:
        return [min_total]

    col_count = len(table_header)
    max_lens = [max(4, len(str(head or ''))) for head in table_header]
    for row in entries:
        for idx in range(min(len(row), col_count)):
            cell = row[idx]
            text = cell[0] if isinstance(cell, list) else cell
            max_lens[idx] = max(max_lens[idx], len(str(text or '')))

    col_widths: list[float] = []
    for idx, length in enumerate(max_lens):
        if idx >= col_count - 2:
            width = 0.12 + min(length, 12) * 0.014
        elif idx == 0:
            width = 0.18 + min(length, 48) * 0.020
        else:
            width = 0.12 + min(length, 40) * 0.015
        col_widths.append(max(0.12, min(width, 1.10)))

    total = sum(col_widths)
    if total < min_total:
        factor = min_total / total if total else 1.0
        col_widths = [width * factor for width in col_widths]
        total = sum(col_widths)
    if total > max_total:
        factor = max_total / total
        col_widths = [width * factor for width in col_widths]
        total = sum(col_widths)

    return [max(min_total, min(total, max_total))] + [round(width, 3) for width in col_widths]
