#!/usr/bin/env python3
"""Resumable parallel driver for pqenum (A260680): runs every cube of `pqenum n a -K K` and keeps
  OUTDIR/cubes.log   one 'cube ...' line per finished cube (the completion record), and
  OUTDIR/boards.txt  every 'S W B board' line, prefixed by the cube id ('<id> S W B board').
A cube is done iff its line is in cubes.log; its board lines are written before its cube line, and on
restart the board lines of unfinished cubes are dropped.
usage: run_enum.py n a K workers OUTDIR"""
import sys, os, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
HERE = os.path.dirname(os.path.abspath(__file__))
PQE = os.path.join(HERE, '..', 'build', 'pqenum')
n, a, K, W, out = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
os.makedirs(out, exist_ok=True)
lst = subprocess.run([PQE, n, a, '-K', K, '-list'], capture_output=True, text=True, check=True).stdout
cubes = {int(l.split()[1]): l.split()[2] for l in lst.splitlines() if l.startswith('cube ')}
cp = os.path.join(out, 'cubes.txt')
if os.path.exists(cp) and open(cp).read() != lst: sys.exit('cube list changed')
open(cp, 'w').write(lst)
logp, bp = os.path.join(out, 'cubes.log'), os.path.join(out, 'boards.txt')
done = set()
if os.path.exists(logp):
    for l in open(logp):
        p = l.split()
        if len(p) > 3 and p[0] == 'cube': done.add(int(p[1]))
if os.path.exists(bp):                                   # drop boards of unfinished cubes
    keep = [l for l in open(bp) if int(l.split()[0]) in done]
    open(bp, 'w').writelines(keep)
todo = [c for c in sorted(cubes) if c not in done]
print(f'{len(cubes)} cubes, {len(done)} done, {len(todo)} to do', flush=True)
logf, bf = open(logp, 'a'), open(bp, 'a')
def run(c):
    r = subprocess.run(['nice', '-n', '10', PQE, n, a, '-K', K, '-cube', f'{c}:{c + 1}'], capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(f'cube {c}: exit {r.returncode} {r.stderr[-300:]}')
    cl = [l for l in r.stdout.splitlines() if l.startswith('cube ')]
    if len(cl) != 1 or int(cl[0].split()[1]) != c or cl[0].split()[2] != cubes[c]: raise RuntimeError(f'cube {c}: bad output')
    return c, cl[0], [l for l in r.stdout.splitlines() if l.startswith('S ')]
k = 0
with ThreadPoolExecutor(W) as ex:
    for f in as_completed([ex.submit(run, c) for c in todo]):
        c, line, S = f.result()
        for s in S: bf.write(f'{c} {s}\n')
        bf.flush(); logf.write(line + '\n'); logf.flush(); k += 1
        if k % 2000 == 0: print(f'{k}/{len(todo)}', flush=True)
print('finished', flush=True)
