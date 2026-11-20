#!/usr/bin/env python3
"""Referee check 4: exact LP-relaxation bounds for single row/column labellings (R, C), independent of
Lemmas 2-4 and of all project code.

Fix (R, C).  W-candidates are the cells of R x C, B-candidates those of R' x C'.  With x_d, y_a in [0,1]
for the diagonals and antidiagonals (1 = W), the LP
    max s  s.t.  s <= sum_{W-cand} z_c,  s <= sum_{B-cand} u_c,
                 z_c <= x_d(c), z_c <= y_a(c),  u_c <= 1 - x_d(c), u_c <= 1 - y_a(c),  all in [0,1]
is a relaxation of max min(W, B) over the diagonal labels (put z_c = [c is a W-cell], u_c = [c is a
B-cell]).  So if its value is < T, no labelling extending (R, C) has W >= T and B >= T.

The LP is solved in floating point (HiGHS via SciPy), but the bound is certified exactly: the dual
multipliers are rounded to rationals, made feasible (y >= 0, the two multipliers of s summing to 1, and
the slack of each variable's upper bound computed exactly), and the dual objective is evaluated in exact
rational arithmetic.  Weak LP duality makes that number a valid upper bound whatever the rounding.

Modes:
  lp_leaves.py random n T k seed      k uniform random (R, C) passing the count test (no symmetry used)
  lp_leaves.py balanced n T k seed    k random (R, C) with |R||C| and |R'||C'| both >= T + n
  lp_leaves.py board n T FILE         the (R, C) of the first n x n board in FILE (W rows/cols = rows/cols
                                      holding a W queen) and all its neighbours at Hamming distance 1 and 2
Output: JSON with the number checked, the number certified < T, and the largest certified bound."""
import sys, json, random
from fractions import Fraction as Fr
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

def cands(n, R, C):
    W, B = [], []
    for i in range(n):
        for j in range(n):
            d, a = i - j + n - 1, i + j
            if R[i] and C[j]: W.append((d, a))
            elif not R[i] and not C[j]: B.append((d, a))
    return W, B

def lp_bound(n, R, C):
    W, B = cands(n, R, C); nd = 2 * n - 1
    # variables: x_0..x_{nd-1}, y_0..y_{nd-1}, z (len W), u (len B), s
    ix = lambda d: d; iy = lambda a: nd + a
    iz = lambda k: 2 * nd + k; iu = lambda k: 2 * nd + len(W) + k; isv = 2 * nd + len(W) + len(B)
    nv = isv + 1
    rows, cols, vals, rhs = [], [], [], []
    def row(entries, b):
        r = len(rhs)
        for c, v in entries: rows.append(r); cols.append(c); vals.append(v)
        rhs.append(b)
    row([(isv, 1)] + [(iz(k), -1) for k in range(len(W))], 0)          # row 0
    row([(isv, 1)] + [(iu(k), -1) for k in range(len(B))], 0)          # row 1
    for k, (d, a) in enumerate(W):
        row([(iz(k), 1), (ix(d), -1)], 0); row([(iz(k), 1), (iy(a), -1)], 0)
    for k, (d, a) in enumerate(B):
        row([(iu(k), 1), (ix(d), 1)], 1); row([(iu(k), 1), (iy(a), 1)], 1)
    A = coo_matrix((vals, (rows, cols)), shape=(len(rhs), nv)).tocsr()
    c = np.zeros(nv); c[isv] = -1.0
    bounds = [(0, 1)] * (nv - 1) + [(0, None)]
    res = linprog(c, A_ub=A, b_ub=np.array(rhs, float), bounds=bounds, method='highs')
    assert res.status == 0, res.message
    y = -np.asarray(res.ineqlin.marginals)            # duals >= 0 for <= rows of a max problem
    # exact certificate
    Q = 1 << 30
    yq = [max(Fr(0), Fr(int(round(v * Q)), Q)) for v in y]
    lam = min(Fr(1), yq[0]); yq[0] = lam; yq[1] = 1 - lam                 # multipliers of s sum to 1
    # reduced requirement: for each variable v (except s), need A^T y + r >= c_v = 0 with r >= 0 (v <= 1)
    aty = [Fr(0)] * nv
    Acoo = A.tocoo()
    for r_, c_, v_ in zip(Acoo.row, Acoo.col, Acoo.data):
        if yq[r_]: aty[c_] += yq[r_] * int(v_)
    assert aty[isv] == 1
    bound = sum(yq[r_] * rhs[r_] for r_ in range(len(rhs)) if rhs[r_]) + sum(max(Fr(0), -aty[v]) for v in range(nv - 1))
    return -res.fun, bound

def from_board(path, n):
    """The first n x n board (rows of W/B/.) in FILE."""
    boards, cur = [], []
    for l in open(path):
        t = l.strip().replace(' ', '')
        if t and set(t) <= set('WB.') and len(t) > 1: cur.append(t)
        else:
            if cur: boards.append(cur)
            cur = []
    if cur: boards.append(cur)
    rows = [b for b in boards if len(b) == n and all(len(r) == n for r in b)][0]
    R = [int('W' in rows[i]) for i in range(n)]; C = [int(any(rows[i][j] == 'W' for i in range(n))) for j in range(n)]
    return n, R, C

def main():
    mode = sys.argv[1]
    if mode == 'board':
        n, T, path = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
        n0, R0, C0 = from_board(path, n); assert n0 == n
        base = R0 + C0; tests = [base]
        for i in range(2 * n):
            t = base[:]; t[i] ^= 1; tests.append(t)
            for j in range(i + 1, 2 * n):
                u = t[:]; u[j] ^= 1; tests.append(u)
        tests = [(t[:n], t[n:]) for t in tests]
    else:
        n, T, k, seed = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
        rng = random.Random(seed); tests = []; extra = n if mode == 'balanced' else 0
        while len(tests) < k:
            R = [rng.randint(0, 1) for _ in range(n)]; C = [rng.randint(0, 1) for _ in range(n)]
            a, b = sum(R), sum(C)
            if a * b >= T + extra and (n - a) * (n - b) >= T + extra: tests.append((R, C))
    checked = certified = 0; worst = None; worst_rc = None; skipped = 0
    for R, C in tests:
        a, b = sum(R), sum(C)
        if a * b < T or (n - a) * (n - b) < T: skipped += 1; continue      # count test already excludes it
        f, bd = lp_bound(n, R, C); checked += 1
        if bd < T: certified += 1
        if worst is None or bd > worst: worst, worst_rc = bd, (''.join(map(str, R)), ''.join(map(str, C)), f)
    print(json.dumps({'mode': mode, 'n': n, 'T': T, 'checked': checked, 'count_test_excluded': skipped,
                      'certified_below_T': certified, 'max_certified_bound': str(worst),
                      'max_certified_bound_float': float(worst) if worst is not None else None,
                      'max_at': worst_rc}))

if __name__ == '__main__':
    main()
