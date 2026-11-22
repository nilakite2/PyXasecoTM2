"""Fixed Eyepiece columns for MP record cards, in shared legacy units."""

import re


def numeric_width(text):
    plain = re.sub(r'\$(?:[0-9a-fA-F]{3}|[a-zA-Z])', '', str(text))
    width = .2 + sum(.32 if char in '.:- ' else .72 for char in plain)
    return width * .7 if str(text).startswith('$n') else width


def record_columns(width, ranks, scores):
    available = max(.5, float(width) - .8)
    # Match TMF's rank/time/name anchors (2.3 / 5.9 / 6.1). Fit the
    # values inside their slots instead of shifting names for larger ranks.
    factor = min(1.0, available / 6.2)
    rank_width = 1.9 * factor
    score_width = 3.5 * factor
    rank_right = .4 + rank_width
    score_left = rank_right + .1 * factor
    score_right = score_left + score_width
    name_x = score_right + .2 * factor
    return {'rank_right': rank_right, 'rank_width': rank_width,
            'score_left': score_left, 'score_right': score_right, 'score_width': score_width,
            'name_x': name_x, 'name_width': max(.1, float(width) - .4 - name_x)}


def fitted_size(text, width):
    # Explicit textsize survives the MP adapter's standard label-scale pass.
    return f'{min(1.0, max(.1, width) / numeric_width(text)):.4f}'
