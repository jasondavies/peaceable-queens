#!/usr/bin/env python3
"""Referee check 2: a(n) by a direct CP-SAT model of placements (OR-Tools), independent of the line
labelling (Lemma 1) and of all project code.  Booleans w_c, b_c for each cell; w_c + b_c' <= 1 whenever
c and c' share a row, column, diagonal or antidiagonal (including c = c'); sum w >= T, sum b >= T.
For each n the model must be feasible at T = a(n) (the solution is re-checked directly) and infeasible
at T = a(n) + 1.  One search worker; no symmetry breaking is added by us.
usage: cpsat_direct.py n1 n2 ... (values a(n) given on the command line as n:a)"""
import sys, json, time
from ortools.sat.python import cp_model

def solve(n, T, tlimit):
    m = cp_model.CpModel()
    cells = [(i, j) for i in range(n) for j in range(n)]
    w = {c: m.NewBoolVar('w%d_%d' % c) for c in cells}
    b = {c: m.NewBoolVar('b%d_%d' % c) for c in cells}
    for (i, j) in cells:
        for (k, l) in cells:
            if i == k or j == l or i - j == k - l or i + j == k + l:
                m.AddBoolOr([w[(i, j)].Not(), b[(k, l)].Not()])
    m.Add(sum(w.values()) >= T); m.Add(sum(b.values()) >= T)
    s = cp_model.CpSolver(); s.parameters.num_search_workers = 1; s.parameters.max_time_in_seconds = tlimit
    s.parameters.random_seed = 1
    st = s.Solve(m)
    res = {cp_model.OPTIMAL: 'FEASIBLE', cp_model.FEASIBLE: 'FEASIBLE', cp_model.INFEASIBLE: 'INFEASIBLE'}.get(st, 'UNKNOWN')
    if res == 'FEASIBLE':
        W = [c for c in cells if s.Value(w[c])]; B = [c for c in cells if s.Value(b[c])]
        bad = [(x, y) for x in W for y in B if x[0] == y[0] or x[1] == y[1] or x[0] - x[1] == y[0] - y[1] or x[0] + x[1] == y[0] + y[1]]
        if bad or len(W) < T or len(B) < T: res = 'BAD-SOLUTION'
    return res, s.WallTime()

if __name__ == '__main__':
    tl = 3600.0; out = {}
    for arg in sys.argv[1:]:
        if arg.startswith('--tl='): tl = float(arg[5:]); continue
        n, a = map(int, arg.split(':'))
        r1 = solve(n, a, tl) if a > 0 else ('FEASIBLE', 0.0)
        r2 = solve(n, a + 1, tl)
        ok = r1[0] == 'FEASIBLE' and r2[0] == 'INFEASIBLE'
        out[n] = {'a': a, 'at_a': r1[0], 'at_a_plus_1': r2[0], 'seconds': round(r1[1] + r2[1], 2), 'ok': ok}
        print(n, out[n], flush=True)
    print(json.dumps(out))
