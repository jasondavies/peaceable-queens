#!/usr/bin/env python3
"""A260680: number of inequivalent optimal peaceable configurations (a(n) white and a(n) black queens), up to
the 16-element group (D4 x colour interchange).  Reads `S W B board` lines from pqenum (all labellings with
min(W,B) >= a(n)), expands each into all placements (a-subsets of its W-cells x a-subsets of its B-cells),
canonicalises and counts orbits.  Each placement is re-checked for peacefulness directly.
usage: pqenum n a | count_configs.py n a"""
import sys
from itertools import combinations

n, a = int(sys.argv[1]), int(sys.argv[2])

def maps(n):
    m = n - 1
    fs = [lambda i, j: (i, j), lambda i, j: (j, m - i), lambda i, j: (m - i, m - j), lambda i, j: (m - j, i),
          lambda i, j: (i, m - j), lambda i, j: (m - i, j), lambda i, j: (j, i), lambda i, j: (m - j, m - i)]
    return [[f(c // n, c % n)[0] * n + f(c // n, c % n)[1] for c in range(n * n)] for f in fs]
G = maps(n)

def canon(w, b):
    best = None
    for g in G:
        W = tuple(sorted(g[c] for c in w)); B = tuple(sorted(g[c] for c in b))
        for key in ((W, B), (B, W)):
            if best is None or key < best: best = key
    return best

def peaceful(w, b):
    for x in w:
        for y in b:
            i, j, k, l = x // n, x % n, y // n, y % n
            if i == k or j == l or i - j == k - l or i + j == k + l: return False
    return True

seen_boards = set(); configs = set(); nlines = 0
for line in sys.stdin:
    if not line.startswith('S '): continue
    nlines += 1
    _, W, B, board = line.split()
    if board in seen_boards: continue
    seen_boards.add(board)
    wc = [c for c, ch in enumerate(board) if ch == 'W']; bc = [c for c, ch in enumerate(board) if ch == 'B']
    for w in combinations(wc, a):
        for b in combinations(bc, a):
            configs.add(canon(w, b))
bad = sum(1 for (w, b) in configs if not peaceful(w, b))
print(f'n={n} a={a} labellings={nlines} distinct cell-boards={len(seen_boards)} inequivalent configurations={len(configs)} non-peaceful={bad}')
