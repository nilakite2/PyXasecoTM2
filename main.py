#!/usr/bin/env python3
"""PyXasecoMP controller entry point with explicit ManiaPlanet diagnostics."""

import logging
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path

MANAGEMENT_RUNTIME_LOCK = 1


class ControllerFormatter(logging.Formatter):
    def format(self, record):
        if getattr(record, 'console_text', False):
            return record.getMessage()
        return super().format(record)


def setup_logging(debug: bool, log_path='logfile.txt'):
    from pyxaseco.core.log_limits import RepeatTraceFilter
    stream = logging.StreamHandler(sys.stdout)
    file = RotatingFileHandler(log_path, maxBytes=64 * 1024 * 1024,
                               backupCount=4, encoding='utf-8')
    for handler in (stream, file):
        handler.addFilter(RepeatTraceFilter())
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s%(repeat_summary)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            stream,
            file,
        ]
    )
    formatter = ControllerFormatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s%(repeat_summary)s',
        datefmt='%Y-%m-%d %H:%M:%S')
    stream.setFormatter(formatter)
    file.setFormatter(formatter)
    console = logging.getLogger('pyxaseco.console.file')
    console.setLevel(logging.INFO)
    console.propagate = False
    console.handlers = [file]


if __name__ == '__main__':
    from pyxaseco.maniaplanet_probe import main as mp_main

    raise SystemExit(mp_main(default_run=True,
                            configure_logging=lambda root, *, debug: setup_logging(debug, root / 'logfile.txt')))
