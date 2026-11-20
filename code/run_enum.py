#!/usr/bin/env python3
"""Resumable parallel driver for pqenum (A260680): runs every cube of `pqenum n a -K K` and keeps
  OUTDIR/cubes.log   one 'cube ...' line per finished cube (the completion record), and
  OUTDIR/boards.txt  every 'S W B board' line, prefixed by the cube id ('<id> S W B board').
OUTDIR is bound to a run manifest (runmanifest.py: n, a, K, pqenum.c and cube-list SHA-256); a directory
made for other parameters is refused.  Every logged cube line is validated (id, prefix, fields) before it
is trusted.  A cube is done iff its line is in cubes.log; its board lines are written before its cube
line, and on restart the board lines of unfinished cubes are dropped.
usage: run_enum.py n a K workers OUTDIR [--adopt]"""
import sys, os, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runmanifest as rm
PQE = os.environ.get('PQ_PQENUM_BIN') or os.path.join(HERE, '..', 'build', 'pqenum')   # override only for tests
SRC = os.path.join(HERE, 'pqenum.c')
FIELDS = ['n1', 'leaves', 'searched', 'n2', 'flows', 'time']
if len(sys.argv) < 6: sys.exit(__doc__)
n, a, K, W, out = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
if W < 1: rm.die('workers must be >= 1')
r = subprocess.run([PQE, n, a, '-K', K, '-list'], capture_output=True, text=True)
if r.returncode != 0: rm.die('pqenum -list failed: ' + r.stderr.strip())
lst = r.stdout
cubes = {int(l.split()[1]): l.split()[2] for l in lst.splitlines() if l.startswith('cube ')}
ids = [int(l.split()[1]) for l in lst.splitlines() if l.startswith('cube ')]
if ids != list(range(len(ids))) or [l for l in lst.splitlines() if l.startswith('cubes ')] != ['cubes %d' % len(ids)]:
    rm.die('malformed cube list from pqenum -list')
rm.require_work(len(cubes), 'pqenum -list gave no cubes')
logp, bp = os.path.join(out, 'cubes.log'), os.path.join(out, 'boards.txt')
rm.bind(out, {'program': 'pqenum', 'n': int(n), 'a': int(a), 'K': int(K), 'pqenum_source_sha256': rm.sha_file(SRC),
              'cube_list_sha256': rm.sha_text(lst), 'cubes': len(cubes)}, PQE, logp, adopt='--adopt' in sys.argv)
cp = os.path.join(out, 'cubes.txt')
if os.path.exists(cp) and open(cp).read() != lst: rm.die('cube list changed')
open(cp, 'w').write(lst)


def check(p):
    if len(p) != 16 or p[0] != 'cube': return None, False, 'fields'
    try: cid = int(p[1])
    except ValueError: return None, False, 'id'
    if cubes.get(cid) != p[2]: return cid, False, 'id/prefix not in the cube list'
    if p[3:15:2] != FIELDS or p[15] not in ('UNSAT', 'FOUND'): return cid, False, 'format'
    return cid, True, ''


done = set(rm.read_lines_checked(logp, check))
if os.path.exists(bp):                                   # drop boards of unfinished cubes
    keep = [l for l in open(bp) if l.endswith('\n') and int(l.split()[0]) in done]
    open(bp, 'w').writelines(keep)
todo = [c for c in sorted(cubes) if c not in done]
print(f'{len(cubes)} cubes, {len(done)} done, {len(todo)} to do', flush=True)
logf, bf = open(logp, 'a'), open(bp, 'a')


def run(c):
    r = subprocess.run(['nice', '-n', '10', PQE, n, a, '-K', K, '-cube', f'{c}:{c + 1}'], capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(f'cube {c}: exit {r.returncode} {r.stderr[-300:]}')
    cl = [l for l in r.stdout.splitlines() if l.startswith('cube ')]
    if len(cl) != 1 or check(cl[0].split())[:2] != (c, True): raise RuntimeError(f'cube {c}: bad output')
    return c, cl[0], [l for l in r.stdout.splitlines() if l.startswith('S ')]


k = 0
with ThreadPoolExecutor(W) as ex:
    for f in as_completed([ex.submit(run, c) for c in todo]):
        c, line, S = f.result()
        for s in S: bf.write(f'{c} {s}\n')
        bf.flush(); logf.write(line + '\n'); logf.flush(); k += 1
        if k % 2000 == 0: print(f'{k}/{len(todo)}', flush=True)
print('finished', flush=True)
