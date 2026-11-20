#!/usr/bin/env python3
"""Referee check 1: a(n) straight from the definition, for small n, with no line labelling, no bound
beyond counting, and no symmetry.

For a set S of white queens, black queens may stand exactly on the cells that share no row, column,
diagonal or antidiagonal with a queen of S (cells of S share lines with themselves).  So
a(n) = max_S min(|S|, f(S)), f(S) = #cells not attacked by S.  f is decreasing in S, so a depth-first
search over the cells (put a white queen here or not) may stop as soon as f(S) < T.  We decide
"exists S with |S| >= T and f(S) >= T" for T = a(n) and T = a(n)+1.

Part 2 (n <= 4): every placement of white and black queens (3^(n^2) of them) is tested with the chess
rule including blocking -- a white and a black queen attack iff they share a line and no queen stands
between them -- and the maximum m is compared with the line-sharing value.
usage: brute.py NMAX [NMAX_BLOCKING]"""
import sys, itertools, json

def att_masks(n):
    A = []
    for i in range(n):
        for j in range(n):
            m = 0
            for k in range(n):
                for l in range(n):
                    if i == k or j == l or i - j == k - l or i + j == k + l:
                        m |= 1 << (k * n + l)
            A.append(m)
    return A

def feasible(n, T):
    N = n * n; A = att_masks(n); full = (1 << N) - 1
    sys.setrecursionlimit(10000)
    def dfs(c, cnt, attacked):
        # attacked: cells attacked by S (incl. S); free = N - popcount(attacked)
        free = N - attacked.bit_count()
        if free < T: return False
        if cnt >= T: return True
        if cnt + (N - c) < T or c == N: return False
        # include c as a white queen (only useful if c not already ... any cell may hold a white queen)
        if dfs(c + 1, cnt + 1, attacked | A[c]): return True
        return dfs(c + 1, cnt, attacked)
    return dfs(0, 0, 0)

def a_value(n):
    t = 0
    while feasible(n, t + 1): t += 1
    return t

def blocking_value(n):
    """max m over all placements (cells empty/W/B) with m white and m black and no attack (chess rule)."""
    N = n * n; best = 0
    lines = []
    for i in range(n): lines.append([(i, j) for j in range(n)])
    for j in range(n): lines.append([(i, j) for i in range(n)])
    for d in range(-(n - 1), n): lines.append([(i, i - d) for i in range(n) if 0 <= i - d < n])
    for s in range(2 * n - 1): lines.append([(i, s - i) for i in range(n) if 0 <= s - i < n])
    for p in itertools.product((0, 1, 2), repeat=N):
        w = p.count(1); b = p.count(2); m = min(w, b)
        if m <= best: continue
        ok = True
        for L in lines:
            seq = [p[i * n + j] for (i, j) in L if p[i * n + j]]
            if any(seq[k] != seq[k + 1] for k in range(len(seq) - 1)): ok = False; break   # adjacent W,B on a line
        if ok: best = m
    return best

if __name__ == '__main__':
    nmax = int(sys.argv[1]); nb = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    out = {'line_sharing': {}, 'blocking': {}}
    for n in range(1, nmax + 1):
        out['line_sharing'][n] = a_value(n); print('n', n, 'a(n) =', out['line_sharing'][n], flush=True)
    for n in range(1, nb + 1):
        out['blocking'][n] = blocking_value(n); print('n', n, 'blocking a(n) =', out['blocking'][n], flush=True)
    print(json.dumps(out))
