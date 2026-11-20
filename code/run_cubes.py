#!/usr/bin/env python3
"""Resumable parallel cube driver for src/pq2.

  run_cubes.py n T K workers OUTDIR [--batch b]

* lists the canonical stage-1 prefixes of K groups (cubes) with `pq2 n T -K K -list` -> OUTDIR/cubes.txt
* runs each not-yet-completed cube as `nice -n 10 pq2 n T -K K -cube a:b` (b-a = batch), with `workers`
  processes in parallel, appending each per-cube result line to OUTDIR/cubes.log (flushed per line);
  a cube is "completed" iff its line (with matching prefix) is in cubes.log, so the run can be killed and resumed.
* progress -> OUTDIR/progress.log ; on FOUND the full pq2 output is saved to OUTDIR/found_<id>.txt
* at the end writes OUTDIR/summary.txt with totals, sha256 of binary, source, cubes.txt and the sorted log.
"""
import sys, os, subprocess, hashlib, time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
PQ2 = os.path.join(HERE, '..', 'build', 'pq2')
SRC = os.path.join(HERE, 'pq2.c')

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f: h.update(f.read())
    return h.hexdigest()

def main():
    n, T, K, workers, out = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    batch = int(sys.argv[sys.argv.index('--batch') + 1]) if '--batch' in sys.argv else 1
    os.makedirs(out, exist_ok=True)
    cubes_txt = os.path.join(out, 'cubes.txt')
    r = subprocess.run([PQ2, str(n), str(T), '-K', str(K), '-list'], capture_output=True, text=True, check=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith('cube ')]
    cubes = {int(l.split()[1]): l.split()[2] for l in lines}
    if os.path.exists(cubes_txt):
        old = open(cubes_txt).read()
        if old != r.stdout:
            sys.exit('cube list changed since previous run -- refusing to resume')
    else:
        open(cubes_txt, 'w').write(r.stdout)
    logp = os.path.join(out, 'cubes.log')
    done = {}
    if os.path.exists(logp):
        for l in open(logp):
            p = l.split()
            if len(p) > 3 and p[0] == 'cube' and p[-1] in ('UNSAT', 'FOUND'):
                done[int(p[1])] = l
    todo = sorted(c for c in cubes if c not in done)
    prog = open(os.path.join(out, 'progress.log'), 'a')
    prog.write(f'{time.ctime()} start: {len(cubes)} cubes, {len(done)} done, {len(todo)} to do, workers={workers}\n'); prog.flush()
    logf = open(logp, 'a')
    batches = [todo[i:i + batch] for i in range(0, len(todo), batch)]
    t0 = time.time(); ndone = 0; found = []

    def run(b):
        # contiguous id range covering the batch (ids in a batch are consecutive in `todo` but may have gaps)
        res = []
        for cid in b:
            rr = subprocess.run(['nice', '-n', '10', PQ2, str(n), str(T), '-K', str(K), '-cube', f'{cid}:{cid + 1}'],
                                capture_output=True, text=True)
            if rr.returncode != 0:
                raise RuntimeError(f'cube {cid}: exit {rr.returncode}\n{rr.stderr}')
            cl = [l for l in rr.stdout.splitlines() if l.startswith('cube ')]
            if len(cl) != 1 or int(cl[0].split()[1]) != cid or cl[0].split()[2] != cubes[cid]:
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
                    found.append(cid)
                    open(os.path.join(out, f'found_{cid}.txt'), 'w').write(full)
                    prog.write(f'{time.ctime()} FOUND in cube {cid}\n'); prog.flush()
            if ndone % 50 < batch or ndone == len(todo):
                el = time.time() - t0
                prog.write(f'{time.ctime()} {ndone}/{len(todo)} cubes, elapsed {el:.0f}s, '
                           f'eta {el / max(ndone, 1) * (len(todo) - ndone):.0f}s\n'); prog.flush()
    logf.close()
    # summary
    done = {}
    for l in open(logp):
        p = l.split()
        if len(p) > 3 and p[0] == 'cube': done[int(p[1])] = l.rstrip('\n')
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
    with open(os.path.join(out, 'summary.txt'), 'w') as s:
        s.write(f'n={n} T={T} K={K}\ncubes={len(cubes)} completed={len(done)} missing={len(missing)}\n')
        s.write(f'results: {res}\ntotals: {tot}\n')
        s.write(f'VERDICT: {"FEASIBLE" if res["FOUND"] else ("INFEASIBLE" if not missing else "INCOMPLETE")}\n')
        s.write(f'sha256 pq2 binary {sha(PQ2)}\nsha256 pq2.c {sha(SRC)}\nsha256 cubes.txt {sha(cubes_txt)}\n')
        s.write(f'sha256 cubes.sorted.log {hashlib.sha256(sorted_log.encode()).hexdigest()}\n')
    prog.write(f'{time.ctime()} finished; see summary.txt\n'); prog.close()
    print(open(os.path.join(out, 'summary.txt')).read())

if __name__ == '__main__':
    main()
