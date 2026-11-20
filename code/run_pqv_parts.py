#!/usr/bin/env python3
"""Resumable driver: run the independent verifier pqv on slices of the (R,C) search.

  run_pqv_parts.py n T m OUTDIR j1 j2 ...     (one single-threaded process at a time, nice -n 10)

Slice j of m is the set of canonical (R,C) with R % m == j (bit i of R = row i is W); the m slices partition
the full search.  One line per slice is appended to OUTDIR/parts.log:
  part j m leaves L pruned P searched S verdict V wall secs
A slice is done iff its line is present, so the driver can be killed and restarted."""
import os, subprocess, sys, time, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
PQV = os.path.join(HERE, '..', 'build', 'pqv')
n, T, m, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
js = [int(x) for x in sys.argv[5:]]
os.makedirs(out, exist_ok=True)
logp = os.path.join(out, 'parts.log')
done = set()
if os.path.exists(logp):
    for l in open(logp):
        p = l.split()
        if p and p[0] == 'part': done.add(int(p[1]))
with open(os.path.join(out, 'binary.sha256'), 'w') as f:
    f.write(hashlib.sha256(open(PQV, 'rb').read()).hexdigest() + '  pqv\n')
for j in js:
    if j in done: continue
    t0 = time.time()
    r = subprocess.run(['nice', '-n', '10', PQV, n, T, '1', '--part', str(j), str(m)], capture_output=True, text=True)
    last = [l for l in r.stdout.splitlines() if l.startswith('pqv ')]
    if r.returncode != 0 or len(last) != 1:
        sys.exit(f'part {j}: exit {r.returncode}\n{r.stdout}\n{r.stderr}')
    kv = dict(x.split('=') for x in last[0].split() if '=' in x)
    verdict = 'INFEASIBLE' if 'INFEASIBLE' in last[0] else 'FEASIBLE'
    with open(logp, 'a') as f:
        f.write(f"part {j} {m} leaves {kv['leaves']} pruned {kv['pruned']} searched {kv['searched']} "
                f"verdict {verdict} wall {time.time() - t0:.1f}\n")
    if verdict != 'INFEASIBLE':
        open(os.path.join(out, f'found_{j}.txt'), 'w').write(r.stdout)
