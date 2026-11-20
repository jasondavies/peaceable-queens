#!/usr/bin/env python3
"""Resumable parallel driver for the torus program: runs `pqt n T -m M -j J` for J = 0..M-1 with W workers.
One line per finished part is appended to OUTDIR/parts.log (the part's 'torus ...' line, prefixed by
'part J M').  If a part is FEASIBLE its full output (board, direct recheck) is saved to OUTDIR/found_J.txt and,
with --stop-on-found, no further parts are started (a feasibility search needs only one witness).
usage: run_torus.py n T M W OUTDIR [--stop-on-found]"""
import sys, os, subprocess, threading
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
PQT = os.path.join(HERE, '..', 'build', 'pqt')
n, T, M, W, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
stop = '--stop-on-found' in sys.argv
os.makedirs(out, exist_ok=True)
logp = os.path.join(out, 'parts.log')
done = set()
if os.path.exists(logp):
    for l in open(logp):
        p = l.split()
        if p and p[0] == 'part': done.add(int(p[1]))
found = threading.Event(); lock = threading.Lock(); procs = set()
if any('FEASIBLE' in l.split() for l in open(logp)) if os.path.exists(logp) else False: found.set()
def run(j):
    if stop and found.is_set(): return
    pr = subprocess.Popen(['nice', '-n', '10', PQT, n, T, '-m', str(M), '-j', str(j)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    with lock: procs.add(pr)
    so, se = pr.communicate()
    with lock: procs.discard(pr)
    line = [l for l in so.splitlines() if l.startswith('torus ')]
    if pr.returncode != 0 or len(line) != 1:
        if not (stop and found.is_set()): print(f'part {j}: exit {pr.returncode}\n{so[-500:]}{se[-500:]}', flush=True)
        return
    with lock:
        open(logp, 'a').write(f'part {j} {M} {line[0]}\n')
        if ' FEASIBLE ' in line[0]:
            open(os.path.join(out, f'found_{j}.txt'), 'w').write(so); found.set()
            print(f'FEASIBLE in part {j}', flush=True)
            if stop:
                for q in procs: q.terminate()                  # unfinished parts are not logged
with ThreadPoolExecutor(W) as ex:
    list(ex.map(run, [j for j in range(M) if j not in done]))
print('finished', flush=True)
