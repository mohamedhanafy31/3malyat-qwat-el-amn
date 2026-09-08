#!/usr/bin/env python3
"""Identity resolution helpers shared by the builder."""
from common import norm_name


def tokens(s):
    return [t for t in norm_name(s).split() if t]


def name_compatible(a, b):
    """True when two Arabic names plausibly denote the same person.

    Short forms in the daily sheets drop middle/last names, so we accept a
    match when one token sequence is an ordered subsequence of the other and
    the first token agrees.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    if ta[0] != tb[0]:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    i = 0
    for t in long_:
        if i < len(short) and short[i] == t:
            i += 1
    return i == len(short)


def match_one(name, candidates, key=lambda c: c):
    """Return the single compatible candidate, or None if 0 or >1 match."""
    hits = [c for c in candidates if name_compatible(name, key(c))]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        # prefer the longest-name candidate when the shorter ones are prefixes
        hits.sort(key=lambda c: -len(tokens(key(c))))
        return hits[0]
    return None
