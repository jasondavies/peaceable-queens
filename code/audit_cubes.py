#!/usr/bin/env python3
"""Audit: re-run k random cubes of a finished run and compare their log lines (all fields except time).
usage: audit_cubes.py n T K RUNDIR k seed"""
import sys, os, random, subprocess
n, T, K, d, k, seed = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), int(sys.argv[6])
PQ2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build', 'pq2')
log = {int(l.split()[1]): l.split() for l in open(os.path.join(d, 'cubes.sorted.log'))}
ids = random.Random(seed).sample(sorted(log), k); bad = 0
for c in ids:
    out = subprocess.run(['nice', '-n', '10', PQ2, n, T, '-K', K, '-cube', f'{c}:{c+1}'], capture_output=True, text=True).stdout
    line = [l.split() for l in out.splitlines() if l.startswith('cube ')][0]
    strip = lambda p: [x for i, x in enumerate(p) if i != p.index('time') + 1]
    same = strip(line) == strip(log[c]); bad += not same
    print(f'cube {c}: {"identical" if same else "DIFFERENT"}')
print(f'audit {d}: {k} cubes re-run, {bad} differences')
