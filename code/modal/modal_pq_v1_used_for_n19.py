"""Ephemeral Modal app: run pq2 cubes or pqv slices remotely; the local entrypoint is the single bookkeeper.

  modal run modal_pq.py --mode pq2 --n 19 --t 53 --outdir logs/n19_T53 --budget 1.0 [--limit k] [--target-sec 600]
  modal run modal_pq.py --mode pqv --n 19 --t 53 --outdir logs/pqv_n19_T53 --budget 1.0 --slice-sec 2600

pq2: cube ids still missing from OUTDIR/cubes.log (cube list OUTDIR/cubes.txt, made locally by `pq2 -list`) are
packed into calls of about --target-sec CPU seconds (predicted from a reference log), each call runs
`pq2 n T -K 4 -cube i:i+1` per cube and returns the stdout lines; every returned line is checked (cube id,
prefix, format, source hash) before it is appended to cubes.log.  pqv: each call runs one slice
`pqv n T 1 --part j 199` and the line is appended to OUTDIR/parts.log in run_pqv_parts.py's format.
Cost: every call returns its in-container wall time; the estimate (wall x (0.5 core x $0.0000131 + 0.25 GiB x
$0.00000222) per second, plus 60 s per container start/idle) is accumulated in modal_ledger.json, and no
further results are awaited (the app is stopped, cancelling queued inputs) once ledger + estimate >= budget."""
import modal, os, sys, json, time, hashlib, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'modal_src')
image = (modal.Image.from_registry('rust:1.75.0-bookworm', add_python='3.12')
         .add_local_file(os.path.join(SRC, 'pq2.c'), '/src/pq2.c', copy=True)
         .add_local_dir(os.path.join(SRC, 'verifier'), '/src/verifier', copy=True)
         .run_commands('gcc --version | head -1 > /opt/gcc_version',
                       'gcc -O3 -o /opt/pq2 /src/pq2.c',
                       'cd /src/verifier && cargo build --release --offline && cp target/release/pqv /opt/pqv',
                       'sha256sum /src/pq2.c /src/verifier/src/main.rs /opt/pq2 /opt/pqv > /opt/hashes'))
app = modal.App('pq-compute', tags={'project': 'peaceable-queens'}, image=image)
RATE = 0.5 * 0.0000131 + 0.25 * 0.00000222        # $ per container-second (cpu=0.5, memory=256 MiB)
OVERHEAD = 60.0                                    # s billed per container for start-up and idle tail (generous)


def _sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def _info():
    cpu = [l for l in open('/proc/cpuinfo') if l.startswith('model name')][:1]
    return {'task': os.environ.get('MODAL_TASK_ID', '?'), 'cpu': cpu[0].split(':', 1)[1].strip() if cpu else '?',
            'src_sha': _sha('/src/pq2.c'), 'pqv_src_sha': _sha('/src/verifier/src/main.rs'),
            'bin_sha': _sha('/opt/pq2'), 'pqv_bin_sha': _sha('/opt/pqv'), 'gcc': open('/opt/gcc_version').read().strip()}


@app.function(cpu=0.5, memory=256, timeout=3 * 3600, max_containers=100, scaledown_window=5, retries=1)
def run_cubes(n, T, K, ids):
    t0 = time.time(); out = []
    for cid in ids:
        r = subprocess.run(['/opt/pq2', str(n), str(T), '-K', str(K), '-cube', '%d:%d' % (cid, cid + 1)], capture_output=True, text=True)
        out.append((cid, r.returncode, r.stdout, r.stderr[-500:]))
    return {'results': out, 'wall': time.time() - t0, 'info': _info()}


@app.function(cpu=0.5, memory=256, timeout=4 * 3600, max_containers=100, scaledown_window=5, retries=0)
def run_slice(n, T, j, m):
    t0 = time.time()
    r = subprocess.run(['/opt/pqv', str(n), str(T), '1', '--part', str(j), str(m)], capture_output=True, text=True)
    return {'j': j, 'rc': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr[-500:], 'wall': time.time() - t0, 'info': _info()}


def ledger_path():
    return os.path.join(HERE, 'modal_ledger.json')


def load_ledger():
    p = ledger_path()
    return json.load(open(p)) if os.path.exists(p) else {'runs': [], 'total_estimate': 0.0}


def save_ledger(L):
    json.dump(L, open(ledger_path() + '.tmp', 'w'), indent=1); os.replace(ledger_path() + '.tmp', ledger_path())


def predicted_times(n, cubes, scale):
    """Predict per-cube local CPU time from the reference log of n-1, scaled by `scale`."""
    ref = {16: None, 17: 'n16_T38', 18: 'n17_T43', 19: '../../peaceable-queens/logs/n18_T48', 20: 'n19_T53'}[n]
    p = os.path.join(HERE, 'logs', ref, 'cubes.sorted.log') if ref else None
    if not p or not os.path.exists(p):
        p = os.path.join(HERE, 'logs', ref, 'cubes.log')
    t = {}
    for l in open(p):
        s = l.split()
        if s and s[0] == 'cube': t[int(s[1])] = scale * float(s[s.index('time') + 1])
    return {c: t.get(c, 60.0) for c in cubes}


@app.local_entrypoint()
def main(mode: str, n: int, t: int, outdir: str, budget: float, limit: int = 0, target_sec: float = 600.0, k: int = 4,
         scale: float = 4.7, slice_sec: float = 600.0, slowdown: float = 1.35):
    # Pre-commit: only calls whose predicted cost (local CPU-s x slowdown x RATE, +OVERHEAD) fits under `budget`
    # (a cumulative cap on the ledger) are submitted, so cancelled in-flight work cannot push spending past it.
    outdir = os.path.join(HERE, outdir); os.makedirs(outdir, exist_ok=True)
    L = load_ledger(); spent0 = L['total_estimate']
    run = {'mode': mode, 'n': n, 'T': t, 'start': time.ctime(), 'calls': 0, 'wall': 0.0, 'containers': [], 'estimate': 0.0}
    L['runs'].append(run); save_ledger(L)
    src_sha = _sha(os.path.join(SRC, 'pq2.c')); pqv_sha = _sha(os.path.join(SRC, 'verifier', 'src', 'main.rs'))
    prov = open(os.path.join(outdir, 'modal_provenance.txt'), 'a')

    def account(res):
        run['calls'] += 1; run['wall'] += res['wall']
        if res['info']['task'] not in run['containers']: run['containers'].append(res['info']['task'])
        run['estimate'] = run['wall'] * RATE + len(run['containers']) * OVERHEAD * RATE
        L['total_estimate'] = spent0 + run['estimate']; save_ledger(L)
        return L['total_estimate']

    if mode == 'pq2':
        cubes = {}
        for l in open(os.path.join(outdir, 'cubes.txt')):
            s = l.split()
            if s and s[0] == 'cube': cubes[int(s[1])] = s[2]
        done = set()
        logp = os.path.join(outdir, 'cubes.log')
        if os.path.exists(logp):
            for l in open(logp):
                s = l.split()
                if len(s) > 3 and s[0] == 'cube' and s[-1] in ('UNSAT', 'FOUND'): done.add(int(s[1]))
        todo = sorted(c for c in cubes if c not in done)
        if limit: todo = todo[:limit]
        pred = predicted_times(n, todo, scale)
        # pack: longest first, greedy into batches of ~target_sec
        batches, cur, cs = [], [], 0.0
        for c in sorted(todo, key=lambda c: -pred[c]):
            if cur and cs + pred[c] > target_sec:
                batches.append(cur); cur, cs = [], 0.0
            cur.append(c); cs += pred[c]
        if cur: batches.append(cur)
        room = budget - spent0; keep = []; acc = 0.0
        for b in sorted(batches, key=lambda b: min(b)):            # low cube ids first
            c = (sum(pred[x] for x in b) * slowdown + OVERHEAD) * RATE
            if acc + c > room: break
            keep.append(b); acc += c
        if len(keep) < len(batches):
            print(f'budget allows {len(keep)} of {len(batches)} calls (predicted ${acc:.2f} of ${room:.2f} room)', flush=True)
        batches = keep; todo = [x for b in batches for x in b]
        print(f'predicted cost of this run ${acc:.2f}', flush=True)
        print(f'{len(todo)} cubes to do in {len(batches)} calls; predicted {sum(pred.values()) / 3600:.1f} CPU-h; ledger ${spent0:.3f}', flush=True)
        logf = open(logp, 'a'); nd = 0
        for res in run_cubes.starmap([(n, t, k, b) for b in batches], order_outputs=False, return_exceptions=True):
            if isinstance(res, Exception):
                print('call failed:', repr(res)[:300], flush=True); continue
            tot = account(res)
            inf = res['info']
            assert inf['src_sha'] == src_sha, 'remote pq2.c differs'
            prov.write(json.dumps({k2: inf[k2] for k2 in ('task', 'cpu', 'bin_sha', 'gcc')}) + '\n'); prov.flush()
            for cid, rc, so, se in res['results']:
                cl = [x for x in so.splitlines() if x.startswith('cube ')]
                p = cl[0].split() if len(cl) == 1 else []
                ok = (rc == 0 and len(p) == 16 and int(p[1]) == cid and p[2] == cubes[cid] and p[3::2][:6] == ['n1', 'leaves', 'searched', 'n2', 'flows', 'time']
                      and p[-1] in ('UNSAT', 'FOUND'))
                if not ok:
                    print(f'BAD result for cube {cid}: rc={rc} {so[-300:]} {se}', flush=True); continue
                logf.write(cl[0] + '\n'); logf.flush(); nd += 1
                if p[-1] == 'FOUND':
                    open(os.path.join(outdir, f'found_{cid}.txt'), 'w').write(so)
                    print(f'FOUND in cube {cid}', flush=True)
                if p[8] != '0':
                    print(f'NOTE cube {cid} searched={p[5]}', flush=True)
            print(f'{time.strftime("%H:%M:%S")} {nd}/{len(todo)} cubes, run est ${run["estimate"]:.3f}, total est ${tot:.3f}', flush=True)
            if tot >= budget:
                print('BUDGET REACHED: stopping', flush=True); break
    elif mode == 'pqv':
        import random
        js = list(range(199)); random.Random(n).shuffle(js)       # the seeded slice order used throughout
        logp = os.path.join(outdir, 'parts.log')
        done = set()
        if os.path.exists(logp):
            for l in open(logp):
                s = l.split()
                if s and s[0] == 'part': done.add(int(s[1]))
        js = [j for j in js if j not in done]
        c1 = (slice_sec * slowdown + OVERHEAD) * RATE
        nfit = max(0, int((budget - spent0) // c1))
        if limit: nfit = min(nfit, limit)
        print(f'{len(js)} slices to do; budget allows {min(nfit, len(js))} at a predicted ${c1:.3f} each; ledger ${spent0:.3f}', flush=True)
        js = js[:nfit]
        logf = open(logp, 'a')
        for res in run_slice.starmap([(n, t, j, 199) for j in js], order_outputs=False, return_exceptions=True):
            if isinstance(res, Exception):
                print('call failed:', repr(res)[:300], flush=True); continue
            tot = account(res); inf = res['info']
            assert inf['pqv_src_sha'] == pqv_sha, 'remote main.rs differs'
            prov.write(json.dumps({k2: inf[k2] for k2 in ('task', 'cpu', 'pqv_bin_sha')}) + '\n'); prov.flush()
            last = [l for l in res['stdout'].splitlines() if l.startswith('pqv ')]
            part = [l for l in res['stdout'].splitlines() if l.startswith('part ')]
            if res['rc'] != 0 or len(last) != 1 or part != ['part %d of 199 (rows masks r with r %% 199 == %d)' % (res['j'], res['j'])]:
                print('BAD slice', res['j'], res['stdout'][-300:], res['stderr'], flush=True); continue
            kv = dict(x.split('=') for x in last[0].split() if '=' in x)
            verdict = 'INFEASIBLE' if 'INFEASIBLE' in last[0] else 'FEASIBLE'
            logf.write(f"part {res['j']} 199 leaves {kv['leaves']} pruned {kv['pruned']} searched {kv['searched']} verdict {verdict} wall {res['wall']:.1f}\n"); logf.flush()
            if verdict != 'INFEASIBLE': print('SLICE FEASIBLE?!', res['j'], flush=True)
            print(f"{time.strftime('%H:%M:%S')} slice {res['j']}: {verdict} leaves {kv['leaves']} wall {res['wall']:.0f}s, total est ${tot:.3f}", flush=True)
            if tot >= budget:
                print('BUDGET REACHED: stopping', flush=True); break
    run['end'] = time.ctime(); save_ledger(L)
    print(f'run estimate ${run["estimate"]:.3f}; ledger total ${L["total_estimate"]:.3f}', flush=True)
