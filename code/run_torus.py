#!/usr/bin/env python3
"""Resumable parallel driver for the torus program: runs `pqt n T -m M -j J` for J = 0..M-1 with W workers.
OUTDIR is bound to a run manifest (runmanifest.py: n, T, M, pqt.c SHA-256); a directory made for other
parameters is refused.  One line per finished part is appended to OUTDIR/parts.log (the part's 'torus ...'
line, prefixed by 'part J M'); logged lines are validated before they are trusted.  If a part is FEASIBLE
its full output (board, direct recheck) is saved to OUTDIR/found_J.txt and, with --stop-on-found, no further
parts are started.  The last line printed is the verdict: FEASIBLE, INFEASIBLE (all M parts logged, none
feasible) or INCOMPLETE (exit status 1).
usage: run_torus.py n T M W OUTDIR [--stop-on-found] [--adopt]"""
import sys, os, subprocess, threading
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runmanifest as rm
PQT = os.path.join(HERE, '..', 'build', 'pqt')
SRC = os.path.join(HERE, 'pqt.c')
if len(sys.argv) < 6: sys.exit(__doc__)
n, T, M, W, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
if M < 1 or W < 1: rm.die('need M >= 1 and W >= 1')
stop = '--stop-on-found' in sys.argv
logp = os.path.join(out, 'parts.log')
rm.bind(out, {'program': 'pqt', 'n': int(n), 'T': int(T), 'M': M, 'pqt_source_sha256': rm.sha_file(SRC)}, PQT, logp,
        adopt='--adopt' in sys.argv)


def check(p):
    ok = (len(p) >= 8 and p[0] == 'part' and p[1].isdigit() and int(p[1]) < M and p[2] == str(M) and p[3] == 'torus'
          and p[4] == 'n=%s' % n and p[5] == 'T=%s' % T and p[6] in ('FEASIBLE', 'INFEASIBLE'))
    return (int(p[1]) if len(p) > 1 and p[1].isdigit() else None), ok, 'format'


logged = rm.read_lines_checked(logp, check)
done = set(logged)
found = threading.Event(); lock = threading.Lock(); procs = set(); failed = []
if any(l.split()[6] == 'FEASIBLE' for l in logged.values()): found.set()


def run(j):
    if stop and found.is_set(): return
    pr = subprocess.Popen(['nice', '-n', '10', PQT, n, T, '-m', str(M), '-j', str(j)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    with lock: procs.add(pr)
    so, se = pr.communicate()
    with lock: procs.discard(pr)
    line = [l for l in so.splitlines() if l.startswith('torus ')]
    if pr.returncode != 0 or len(line) != 1:
        if not (stop and found.is_set()):
            failed.append(j); print(f'part {j}: exit {pr.returncode}\n{so[-500:]}{se[-500:]}', flush=True)
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
logged = rm.read_lines_checked(logp, check)
if any(l.split()[6] == 'FEASIBLE' for l in logged.values()):
    print('VERDICT FEASIBLE', flush=True)
elif len(logged) == M and not failed:
    print('VERDICT INFEASIBLE (all %d parts)' % M, flush=True)
else:
    print('VERDICT INCOMPLETE (%d of %d parts logged, %d failed)' % (len(logged), M, len(failed)), flush=True); sys.exit(1)
