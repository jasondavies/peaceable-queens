#!/usr/bin/env python3
"""Check peaceable-queens placements directly (no line-labelling): reads boards made of W/B/. rows
(blank-line or header separated) from files or stdin, and for each board reports n, #W, #B and whether
some white queen and black queen share a row, column, diagonal or antidiagonal."""
import sys

def check(rows):
    n = len(rows)
    assert all(len(r) == n for r in rows), 'board not square'
    W = [(i, j) for i in range(n) for j in range(n) if rows[i][j] == 'W']
    B = [(i, j) for i in range(n) for j in range(n) if rows[i][j] == 'B']
    bad = [(w, b) for w in W for b in B
           if w[0] == b[0] or w[1] == b[1] or w[0] - w[1] == b[0] - b[1] or w[0] + w[1] == b[0] + b[1]]
    return n, len(W), len(B), bad

def boards(text):
    cur = []
    for line in text.splitlines():
        s = line.strip().replace(' ', '').replace('|', '')
        if s and set(s) <= set('WB.') and len(s) > 1:
            cur.append(s)
        else:
            if cur: yield cur
            cur = []
    if cur: yield cur

if __name__ == '__main__':
    text = ''.join(open(f).read() for f in sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    ok = True
    for b in boards(text):
        n, w, bl, bad = check(b)
        print(f'n={n} white={w} black={bl} min={min(w, bl)} attacks={len(bad)} {"OK" if not bad else "INVALID"}')
        ok &= not bad
    sys.exit(0 if ok else 1)
