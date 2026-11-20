#!/usr/bin/env python3
"""Resumable driver: run the independent verifier pqv on slices of the (R,C) search.

  run_pqv_parts.py n T m OUTDIR j1 j2 ... [--adopt]   (one single-threaded process at a time, nice -n 10)

Slice j of m is the set of canonical (R,C) with R % m == j (bit i of R = row i is W); the m slices partition
the full search.  OUTDIR is bound to a run manifest (runmanifest.py: n, T, m, main.rs SHA-256); several
drivers with disjoint slice lists may share one OUTDIR.  One line per slice is appended to OUTDIR/parts.log:
  part j m leaves L pruned P searched S verdict V wall secs
Every logged line is validated before it is trusted; a slice is done iff its line is present."""
import os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runmanifest as rm
PQV = os.path.join(HERE, '..', 'build', 'pqv')
SRC = os.path.join(HERE, 'verifier', 'src', 'main.rs')
args = [x for x in sys.argv[1:] if x != '--adopt']
if len(args) < 4: sys.exit(__doc__)
n, T, m, out = args[0], args[1], int(args[2]), args[3]
js = [int(x) for x in args[4:]]
if m < 1 or any(not 0 <= j < m for j in js): rm.die('need m >= 1 and 0 <= j < m')
rm.require_work(len(js), 'no slices given')
logp = os.path.join(out, 'parts.log')
rm.bind(out, {'program': 'pqv', 'n': int(n), 'T': int(T), 'm': m, 'pqv_source_sha256': rm.sha_file(SRC)}, PQV, logp,
        adopt='--adopt' in sys.argv, exclusive=False)


def check(p):
    ok = (len(p) == 13 and p[0] == 'part' and p[2] == str(m) and p[3::2][:5] == ['leaves', 'pruned', 'searched', 'verdict', 'wall']
          and p[1].isdigit() and int(p[1]) < m and p[10] in ('INFEASIBLE', 'FEASIBLE'))
    return (int(p[1]) if len(p) > 1 and p[1].isdigit() else None), ok, 'format'


done = set(rm.read_lines_checked(logp, check, repair=False))
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
