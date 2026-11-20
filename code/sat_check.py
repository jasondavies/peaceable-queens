#!/usr/bin/env python3
"""SAT cross-checks for peaceable queens with DRUP proofs checked by drat-trim.

  sat_check.py queens n T           direct placement encoding (independent of the line-labelling lemma):
                                    vars w_c, b_c; w_c & b_c' forbidden whenever c,c' share a line (incl. c=c');
                                    sum w >= T, sum b >= T.
  sat_check.py lines n T            line-labelling encoding over all 6n-2 lines.
  sat_check.py leaf n T R C         line-labelling encoding with rows/cols fixed: R,C are 0/1 strings
                                    (index i = row i / column i, '1' = W).
  sat_check.py cube n T PREFIX      rows/cols in pq2's stage-1 order fixed by PREFIX (a pq2 cube).
  sat_check.py leaves n T FILE      as 'leaf' for every 'R C' pair in FILE.
Prints SAT/UNSAT and, for UNSAT, the drat-trim verdict.  Uses Glucose4 (pysat) for proofs.
"""
import sys, os, subprocess, tempfile
from pysat.solvers import Solver
from pysat.card import CardEnc, EncType
from pysat.formula import CNF, IDPool

HERE = os.path.dirname(os.path.abspath(__file__))
DRAT = os.path.join(HERE, '..', 'tools', 'drat-trim')

def lines_of(n, i, j):
    return [('r', i), ('c', j), ('d', i - j), ('a', i + j)]

def enc_queens(n, T):
    pool = IDPool(); cnf = CNF()
    W = {(i, j): pool.id(('w', i, j)) for i in range(n) for j in range(n)}
    B = {(i, j): pool.id(('b', i, j)) for i in range(n) for j in range(n)}
    cells = list(W)
    for c in cells:
        for c2 in cells:
            if set(lines_of(n, *c)) & set(lines_of(n, *c2)):   # same line (or same cell)
                cnf.append([-W[c], -B[c2]])
    for vs in (list(W.values()), list(B.values())):
        cnf.extend(CardEnc.atleast(lits=vs, bound=T, vpool=pool, encoding=EncType.seqcounter).clauses)
    return cnf

def cube_fixings(n, prefix):
    """pq2 stage-1 order: for e = 0,1,...: row e, row n-1-e, col e, col n-1-e (middle group: row m, col m)."""
    order = []
    for e in range((n + 1) // 2):
        a, b = e, n - 1 - e
        order.append(('r', a))
        if b != a: order.append(('r', b))
        order.append(('c', a))
        if b != a: order.append(('c', b))
    return {order[k]: prefix[k] == '1' for k in range(len(prefix))}

def enc_lines(n, T, R=None, C=None, fix=None):
    pool = IDPool(); cnf = CNF()
    L = {}
    for i in range(n):
        for j in range(n):
            for l in lines_of(n, i, j):
                if l not in L: L[l] = pool.id(l)          # true = W
    wv, bv = [], []
    for i in range(n):
        for j in range(n):
            ls = [L[l] for l in lines_of(n, i, j)]
            w = pool.id(('w', i, j)); b = pool.id(('b', i, j))
            for x in ls:
                cnf.append([-w, x]); cnf.append([-b, -x])
            wv.append(w); bv.append(b)
    if R is not None:
        for i in range(n):
            cnf.append([L[('r', i)] if R[i] == '1' else -L[('r', i)]])
            cnf.append([L[('c', i)] if C[i] == '1' else -L[('c', i)]])
    if fix:
        for l, v in fix.items():
            cnf.append([L[l] if v else -L[l]])
    for vs in (wv, bv):
        cnf.extend(CardEnc.atleast(lits=vs, bound=T, vpool=pool, encoding=EncType.seqcounter).clauses)
    return cnf

def solve_and_check(cnf, tag=''):
    with Solver(name='glucose4', bootstrap_with=cnf.clauses, with_proof=True) as s:
        sat = s.solve()
        if sat:
            return 'SAT', None
        proof = s.get_proof()
    d = tempfile.mkdtemp()
    fc = os.path.join(d, 'f.cnf'); fp = os.path.join(d, 'f.drup')
    cnf.to_file(fc)
    with open(fp, 'w') as f:
        for line in proof: f.write(line + '\n')
    r = subprocess.run([DRAT, fc, fp, '-t', '20000'], capture_output=True, text=True)
    verdict = 'VERIFIED' if 's VERIFIED' in r.stdout else 'NOT-VERIFIED'
    for p in (fc, fp): os.remove(p)
    os.rmdir(d)
    return 'UNSAT', verdict

def main():
    mode = sys.argv[1]; n = int(sys.argv[2]); T = int(sys.argv[3])
    if mode == 'queens':
        print(mode, n, T, *solve_and_check(enc_queens(n, T)))
    elif mode == 'lines':
        print(mode, n, T, *solve_and_check(enc_lines(n, T)))
    elif mode == 'leaf':
        print(mode, n, T, sys.argv[4], sys.argv[5], *solve_and_check(enc_lines(n, T, sys.argv[4], sys.argv[5])))
    elif mode == 'cube':      # sat_check.py cube n T PREFIX   (prefix in pq2 stage-1 order)
        print(mode, n, T, sys.argv[4], *solve_and_check(enc_lines(n, T, fix=cube_fixings(n, sys.argv[4]))))
    elif mode == 'leaves':
        for line in open(sys.argv[4]):
            p = line.split()
            if len(p) < 2: continue
            R, C = p[0], p[1]
            print('leaf', n, T, R, C, *solve_and_check(enc_lines(n, T, R, C)), flush=True)

if __name__ == '__main__':
    main()
