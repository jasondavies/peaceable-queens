#!/usr/bin/env python3
"""Resumable parallel cube driver for pq2.

  run_cubes.py n T K workers OUTDIR [--batch b] [--adopt]

* lists the canonical stage-1 prefixes of K groups (cubes) with `pq2 n T -K K -list` -> OUTDIR/cubes.txt
* binds OUTDIR to a run manifest (runmanifest.py): n, T, K, the pq2.c and cube-list SHA-256.  A directory
  made for other parameters is refused, so logged results are never reused for a different run.
* runs each not-yet-completed cube as `nice -n 10 pq2 n T -K K -cube i:i+1` with `workers` processes,
  appending each per-cube result line to OUTDIR/cubes.log (flushed per line).  Every line already in the
  log is validated (cube id, prefix, fields, verdict) before it is trusted.
* progress -> OUTDIR/progress.log ; on FOUND the full pq2 output is saved to OUTDIR/found_<id>.txt
* at the end writes OUTDIR/summary.txt with totals, the hashes bound in the manifest and every session's
  binary hash (sessions.log).
"""
import sys, os, subprocess, hashlib, time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runmanifest as rm

PQ2 = os.path.join(HERE, '..', 'build', 'pq2')
SRC = os.path.join(HERE, 'pq2.c')
FIELDS = ['n1', 'leaves', 'searched', 'n2', 'flows', 'time']


def check_line(p, cubes):
    """(id, ok, why) for one split cube line."""
    if len(p) != 16 or p[0] != 'cube': return None, False, 'wrong number of fields'
    try: cid = int(p[1])
    except ValueError: return None, False, 'bad id'
    if cid not in cubes: return cid, False, 'id not in the cube list'
    if p[2] != cubes[cid]: return cid, False, 'prefix differs from the cube list'
    if p[3:15:2] != FIELDS: return cid, False, 'field names'
    try:
        [int(x) for x in p[4:13:2]]; float(p[14])
    except ValueError: return cid, False, 'non-numeric field'
    if p[15] not in ('UNSAT', 'FOUND'): return cid, False, 'verdict'
    return cid, True, ''


def main():
    a = sys.argv[1:]
    if len(a) < 5: sys.exit(__doc__)
    n, T, K, workers, out = int(a[0]), int(a[1]), int(a[2]), int(a[3]), a[4]
    batch = int(a[a.index('--batch') + 1]) if '--batch' in a else 1
    if workers < 1 or batch < 1: rm.die('workers and batch must be >= 1')
    r = subprocess.run([PQ2, str(n), str(T), '-K', str(K), '-list'], capture_output=True, text=True)
    if r.returncode != 0: rm.die('pq2 -list failed: ' + r.stderr.strip())
    lines = [l for l in r.stdout.splitlines() if l.startswith('cube ')]
    cubes = {int(l.split()[1]): l.split()[2] for l in lines}
    logp = os.path.join(out, 'cubes.log')
    rm.bind(out, {'program': 'pq2', 'n': n, 'T': T, 'K': K, 'pq2_source_sha256': rm.sha_file(SRC),
                  'cube_list_sha256': rm.sha_text(r.stdout), 'cubes': len(cubes)}, PQ2, logp, adopt='--adopt' in a)
    cubes_txt = os.path.join(out, 'cubes.txt')
    if os.path.exists(cubes_txt) and open(cubes_txt).read() != r.stdout:
        rm.die('cube list changed since the previous run')
    open(cubes_txt, 'w').write(r.stdout)
    done = rm.read_lines_checked(logp, lambda p: check_line(p, cubes))
    todo = sorted(c for c in cubes if c not in done)
    prog = open(os.path.join(out, 'progress.log'), 'a')
    prog.write(f'{time.ctime()} start: {len(cubes)} cubes, {len(done)} done, {len(todo)} to do, workers={workers}\n'); prog.flush()
    logf = open(logp, 'a')
    batches = [todo[i:i + batch] for i in range(0, len(todo), batch)]
    t0 = time.time(); ndone = 0

    def run(b):
        res = []
        for cid in b:
            rr = subprocess.run(['nice', '-n', '10', PQ2, str(n), str(T), '-K', str(K), '-cube', f'{cid}:{cid + 1}'],
                                capture_output=True, text=True)
            if rr.returncode != 0:
                raise RuntimeError(f'cube {cid}: exit {rr.returncode}\n{rr.stderr}')
            cl = [l for l in rr.stdout.splitlines() if l.startswith('cube ')]
            if len(cl) != 1 or check_line(cl[0].split(), cubes)[:2] != (cid, True):
                raise RuntimeError(f'cube {cid}: unexpected output\n{rr.stdout}')
            res.append((cid, cl[0], rr.stdout))
        return res

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run, b) for b in batches]
        for f in as_completed(futs):
            for cid, line, full in f.result():
                logf.write(line + '\n'); logf.flush()
                ndone += 1
                if line.endswith('FOUND'):
                    open(os.path.join(out, f'found_{cid}.txt'), 'w').write(full)
                    prog.write(f'{time.ctime()} FOUND in cube {cid}\n'); prog.flush()
            if ndone % 50 < batch or ndone == len(todo):
                el = time.time() - t0
                prog.write(f'{time.ctime()} {ndone}/{len(todo)} cubes, elapsed {el:.0f}s, '
                           f'eta {el / max(ndone, 1) * (len(todo) - ndone):.0f}s\n'); prog.flush()
    logf.close()
    done = rm.read_lines_checked(logp, lambda p: check_line(p, cubes))
    missing = [c for c in cubes if c not in done]
    tot = {'n1': 0, 'leaves': 0, 'searched': 0, 'n2': 0, 'flows': 0, 'time': 0.0}
    res = {'UNSAT': 0, 'FOUND': 0}
    for l in done.values():
        p = l.split()
        kv = dict(zip(p[3::2], p[4::2]))
        for k in tot: tot[k] += float(kv[k]) if k == 'time' else int(kv[k])
        res[p[-1]] += 1
    sorted_log = '\n'.join(done[c] for c in sorted(done)) + '\n'
    open(os.path.join(out, 'cubes.sorted.log'), 'w').write(sorted_log)
    sess = sorted({l.split()[2] for l in open(os.path.join(out, 'sessions.log'))})
    with open(os.path.join(out, 'summary.txt'), 'w') as s:
        s.write(f'n={n} T={T} K={K}\ncubes={len(cubes)} completed={len(done)} missing={len(missing)}\n')
        s.write(f'results: {res}\ntotals: {tot}\n')
        s.write(f'VERDICT: {"FEASIBLE" if res["FOUND"] else ("INFEASIBLE" if not missing else "INCOMPLETE")}\n')
        s.write(f'sha256 pq2.c {rm.sha_file(SRC)} (bound in run_manifest.json)\n')
        s.write(f'sha256 pq2 binaries of the sessions {" ".join(sess)}\nsha256 cubes.txt {rm.sha_file(cubes_txt)}\n')
        s.write(f'sha256 cubes.sorted.log {hashlib.sha256(sorted_log.encode()).hexdigest()}\n')
    prog.write(f'{time.ctime()} finished; see summary.txt\n'); prog.close()
    print(open(os.path.join(out, 'summary.txt')).read())


if __name__ == '__main__':
    main()
