#!/usr/bin/env python3
"""Direct check of a peaceable placement on the n x n torus: no white/black pair sharing a row, column,
or a toroidal diagonal (i-j mod n) or antidiagonal (i+j mod n).  Reads W/B/. boards (one row per line)."""
import sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
from check_placement import boards
for b in boards(open(sys.argv[1]).read()):
    n = len(b); W = [(i, j) for i in range(n) for j in range(n) if b[i][j] == 'W']; B = [(i, j) for i in range(n) for j in range(n) if b[i][j] == 'B']
    bad = sum(1 for (i, j) in W for (k, l) in B if i == k or j == l or (i - j - k + l) % n == 0 or (i + j - k - l) % n == 0)
    print(f'torus n={n} white={len(W)} black={len(B)} attacks={bad} {"OK" if bad == 0 else "INVALID"}')
