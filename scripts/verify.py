#!/usr/bin/env python3
"""Reproduce the computations and check every number of the paper against claims.json.

  .venv/bin/python scripts/verify.py                  # default (fast) mode, ~10 minutes, at most --jobs processes
  .venv/bin/python scripts/verify.py --only STEP[,STEP] # build, unit, small, referee, sat, certificates, logs,
                                                       # replay, side, paper
  .venv/bin/python scripts/verify.py --full N          # also rerun the complete search for n = N (16..20) and compare
                                                       # every cube line with data/runs/  (n=16: ~25 CPU min,
                                                       # n=17: ~2 CPU h, n=18: ~10 CPU h, n=19: ~41 CPU h, n=20: ~170 CPU h)
  .venv/bin/python scripts/verify.py --full-pqv N      # also run the second implementation on the complete search for
                                                       # n = N (n=16: ~2 CPU h, n=17: ~9 CPU h, ...)
  .venv/bin/python scripts/verify.py --tamper          # tamper test: perturbed copies of claims.json and of a log must fail
Options: --jobs J (default 2) processes for the parallel steps; --thorough runs larger variants of the small (n <= 15),
referee (definition search n <= 8, CP-SAT n <= 7, all recorded LP samples), sat (n <= 8, 50 leaves), replay and side
steps (a few CPU hours).

Each step writes verification/<step>.json and verification/<step>.log.  Every gate compares a recomputed
value, or a value parsed from the recorded logs in data/ (whose SHA-256 hashes are checked against
data/MANIFEST.sha256), exactly with claims.json.  paper/claims.tex is generated from claims.json by
scripts/make_claims_tex.py, so the paper and the gates share one source.  A summary with input and PDF
hashes goes to verification/summary.json.  The exit status is nonzero if any gate fails, or if the LaTeX
log has a warning or a bad box.
"""
import argparse, hashlib, json, os, random, re, shutil, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE, DATA, BUILD, OUT = ROOT / 'code', ROOT / 'data', ROOT / 'build', ROOT / 'verification'
PY = sys.executable
PQ2, PQENUM, PQT, PQV = BUILD / 'pq2', BUILD / 'pqenum', BUILD / 'pqt', BUILD / 'pqv'
ENV = dict(os.environ, PYTHONHASHSEED='0', OMP_NUM_THREADS='1')
CLAIMS = json.loads((ROOT / 'claims.json').read_text())
A = [int(x) for x in CLAIMS['a_known'].split(',')]          # a(1..15) from OEIS
JOBS = 2
WORD = {16: 'Sixteen', 17: 'Seventeen', 18: 'Eighteen', 19: 'Nineteen', 20: 'Twenty'}
NMAX = max(int(k) for k in CLAIMS['runs'])          # largest n settled by the main search
BIG = list(range(16, NMAX + 1))                        # the cube runs
LPN = sorted(int(k) for k in CLAIMS['lp'])           # n with recorded LP certificates
PQVN = sorted(int(k) for k in CLAIMS['pqv_parts'])   # n with recorded verifier slices


def a_of(n):
    return A[n - 1] if n <= 15 else int(CLAIMS['a' + WORD[n]])


def sh(cmd, timeout=None, nice=True, cwd=ROOT):
    cmd = [str(c) for c in cmd]
    if nice:
        cmd = ['nice', '-n', '10'] + cmd
    r = subprocess.run(cmd, capture_output=True, text=True, env=ENV, timeout=timeout, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


def sanitize(t):
    return t.replace(str(ROOT), '.').replace(str(Path.home()), '~')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def pmap(f, xs):
    with ThreadPoolExecutor(max_workers=JOBS) as ex:
        return list(ex.map(f, xs))


class Step:
    def __init__(self, name):
        self.name, self.gates, self.log, self.data, self.t0 = name, [], [], {}, time.time()

    def gate(self, ok, text):
        self.gates.append((bool(ok), text))

    def note(self, s):
        self.log.append(sanitize(str(s)))

    def finish(self):
        ok = all(g for g, _ in self.gates) and bool(self.gates)
        OUT.mkdir(exist_ok=True)
        (OUT / (self.name + '.json')).write_text(json.dumps(self.data, indent=1, sort_keys=True) + '\n')
        (OUT / (self.name + '.log')).write_text('\n'.join(self.log) + ''.join(
            '\n[gate] %s %s' % ('ok  ' if g else 'FAIL', t) for g, t in self.gates) + '\n')
        print('%-14s %s  (%d gates, %.0fs)' % (self.name, 'PASS' if ok else 'FAIL', len(self.gates), time.time() - self.t0), flush=True)
        for g, t in self.gates:
            if not g:
                print('    gate failed:', t)
        return {'name': self.name, 'ok': ok, 'seconds': round(time.time() - self.t0, 1),
                'gates': [{'ok': g, 'check': t} for g, t in self.gates]}


def kv(line):
    p = line.split()
    return dict(zip(p[3::2], p[4::2]))


def parse_pq2(out):
    m = re.search(r'^n=(\d+) T=(\d+) K=(-?\d+) (FEASIBLE|INFEASIBLE) (.*)$', out, re.M)
    d = {k: v for k, v in re.findall(r'(\w+)=([\d.]+)', m.group(5))}
    d['verdict'] = m.group(4)
    return d


def parse_pqv(out):
    m = re.search(r'^pqv n=(\d+) T=(\d+) (FEASIBLE|INFEASIBLE) leaves=(\d+) pruned=(\d+) searched=(\d+)', out, re.M)
    return {'verdict': m.group(3), 'leaves': int(m.group(4)), 'pruned': int(m.group(5)), 'searched': int(m.group(6))}


def check_boards(text):
    p = subprocess.run([PY, str(CODE / 'check_placement.py')], input=text, capture_output=True, text=True)
    res = re.findall(r'n=(\d+) white=(\d+) black=(\d+) min=(\d+) attacks=(\d+) (OK|INVALID)', p.stdout)
    return [(int(n), int(w), int(b), int(m), int(at), s) for n, w, b, m, at, s in res]


def fmt_time(t):
    if t < 0.01: return '$<0.01$\\,s'
    if t < 10: return '$%.2f$\\,s' % t
    if t < 100: return '$%.1f$\\,s' % t
    if t < 7200: return '$%d$\\,s' % round(t)
    return '$%.1f$\\,h' % (t / 3600)


# ------------------------------------------------------------------ steps
def step_build():
    s = Step('build')
    BUILD.mkdir(exist_ok=True)
    for prog in ('pq2', 'pqenum', 'pqt'):
        rc, o, e = sh(['gcc', '-O3', '-march=native', '-o', BUILD / prog, CODE / (prog + '.c')], nice=False)
        s.note('gcc %s: rc=%d %s' % (prog, rc, e.strip()))
        s.gate(rc == 0 and os.access(BUILD / prog, os.X_OK), '%s compiled from code/%s.c' % (prog, prog))
    rc, o, e = sh(['cargo', 'build', '--release', '--offline', '--target-dir', BUILD / 'cargo'], nice=False, cwd=CODE / 'verifier')
    s.note('cargo: rc=%d %s' % (rc, e.strip()[-300:]))
    if rc == 0:
        shutil.copy2(BUILD / 'cargo' / 'release' / 'pqv', PQV)
    s.gate(rc == 0 and PQV.exists(), 'pqv (Rust) built from code/verifier/')
    rc, o, e = sh(['sh', ROOT / 'scripts' / 'get_tools.sh'], nice=False)
    s.note(o + e)
    s.gate(rc == 0 and (ROOT / 'tools' / 'drat-trim').exists(), 'drat-trim built (tarball SHA-256 checked)')
    for f in ('pq2.c', 'pqenum.c', 'pqt.c', 'verifier/src/main.rs'):
        s.data['sha256 code/' + f] = sha(CODE / f)
    s.gate(s.data['sha256 code/pq2.c'] == CLAIMS['sha_pq2c'], 'code/pq2.c is the source used for the recorded runs')
    s.gate(s.data['sha256 code/verifier/src/main.rs'] == CLAIMS['sha_pqv'], 'code/verifier/src/main.rs is the source used for the slice runs')
    return s.finish()


def step_unit():
    s = Step('unit')
    tot = 0; bad = 0
    for n in range(3, 9):
        rc, o, e = sh([PQ2, n, 1, '-selftest', 3000])
        m = re.search(r'selftest n=(\d+) iters=(\d+) mismatches=(\d+)', o); s.note(o.strip())
        tot += int(m.group(2)); bad += int(m.group(3))
    s.data['pq2_selftest'] = {'trials': tot, 'mismatches': bad}
    s.gate(tot == int(CLAIMS['SelftestTrials']) and bad == 0, 'pq2 min-cut vs brute force: %d trials, 0 mismatches' % tot)
    tot = 0; bad = 0
    for n, k in ((2, 300), (3, 300), (4, 300), (5, 300), (6, 20)):
        rc, o, e = sh([PQV, n, 1, '--selftest', k])
        m = re.search(r'pqv selftest n=(\d+) trials=(\d+) mismatches=(\d+)', o); s.note(o.strip())
        tot += int(m.group(2)); bad += int(m.group(3))
    s.data['pqv_selftest'] = {'trials': tot, 'mismatches': bad}
    s.gate(bad == 0 and tot == 1220, 'pqv closure network vs brute force: %d trials, 0 mismatches' % tot)
    return s.finish()


def burnside(ns_T):
    args = [x for n, T in ns_T for x in (n, T)]
    rc, o, e = sh([PY, CODE / 'referee' / 'burnside.py'] + args)
    return json.loads(o)


def step_small(nmax):
    s = Step('small')
    jobs = []
    for n in range(1, nmax + 1):
        a = a_of(n)
        for T in ([a] if a > 0 else []) + [a + 1]:
            jobs.append(('pq2', n, T, [PQ2, n, T]))
            jobs.append(('pqv', n, T, [PQV, n, T, 1]))
            if n <= 10:
                jobs.append(('pq2nosym', n, T, [PQ2, n, T, '-nosym']))
                jobs.append(('pqvnobound', n, T, [PQV, n, T, 1, '--nobound']))
    res = {}
    outs = pmap(lambda j: sh(j[3])[1], jobs)
    for (p, n, T, c), o in zip(jobs, outs):
        res[(p, n, T)] = o
        s.note('$ %s\n%s' % (' '.join([Path(c[0]).name] + [str(x) for x in c[1:]]), o.strip()[:2000]))
    bs = burnside([(n, a_of(n) + 1) for n in range(3, nmax + 1)])
    s.gate(bs['action_check_n<=6'] and bs['brute_vs_burnside_n<=8'], 'Burnside script: action and brute-force self-checks')
    table = {}
    for n in range(1, nmax + 1):
        a = a_of(n)
        for T in ([a] if a > 0 else []) + [a + 1]:
            feas = T <= a
            for p in ('pq2', 'pqv', 'pq2nosym', 'pqvnobound'):
                if (p, n, T) not in res:
                    continue
                o = res[(p, n, T)]
                v = (parse_pq2(o) if p.startswith('pq2') else parse_pqv(o))['verdict']
                s.gate(v == ('FEASIBLE' if feas else 'INFEASIBLE'), '%s n=%d T=%d %s' % (p, n, T, v))
            if feas:
                b = check_boards(res[('pq2', n, T)])
                s.gate(b and all(x[5] == 'OK' for x in b) and max(x[3] for x in b) >= T, 'pq2 witness n=%d has %d+%d queens, no attack' % (n, T, T))
            elif n >= 3:
                l2 = int(parse_pq2(res[('pq2', n, T)])['leaves']); lv = parse_pqv(res[('pqv', n, T)])['leaves']
                bn = bs['n%d_T%d' % (n, T)]
                table[n] = l2
                s.gate(l2 == lv == bn, 'n=%d T=%d orbit counts pq2=%d pqv=%d Burnside=%d' % (n, T, l2, lv, bn))
                if str(n) in CLAIMS['runs']:
                    s.gate(str(l2) == CLAIMS['runs'][str(n)]['leaves'], 'n=%d orbit count matches claims.json' % n)
                    s.gate(parse_pq2(res[('pq2', n, T)])['leafSearched'] == '0', 'n=%d no diagonal search needed' % n)
    s.data['orbits'] = table
    return s.finish()


def step_referee(fast=True):
    s = Step('referee')
    nb = int(CLAIMS['BruteN']) if not fast else 7
    rc, o, e = sh([PY, CODE / 'referee' / 'brute.py', nb, 4]); s.note(o)
    d = json.loads(o.strip().splitlines()[-1])
    s.gate(all(d['line_sharing'][str(n)] == a_of(n) for n in range(1, nb + 1)), 'definition search: a(1..%d) = OEIS' % nb)
    s.gate(all(d['blocking'][str(n)] == a_of(n) for n in range(1, 5)), 'all placements with the blocking rule, n <= 4')
    nc = int(CLAIMS['CpsatN']) if not fast else 6
    rc, o, e = sh([PY, CODE / 'referee' / 'cpsat_direct.py'] + ['%d:%d' % (n, a_of(n)) for n in range(1, nc + 1)]); s.note(o)
    d = json.loads(o.strip().splitlines()[-1])
    s.gate(all(d[str(n)]['ok'] for n in range(1, nc + 1)), 'direct CP-SAT model: a(1..%d) = OEIS' % nc)
    # Burnside counts for the main runs
    bs = burnside([(n, a_of(n) + 1) for n in BIG])
    for n in BIG:
        s.gate(str(bs['n%d_T%d' % (n, a_of(n) + 1)]) == CLAIMS['runs'][str(n)]['leaves'],
               'Burnside orbit count n=%d equals the recorded leaf total %s' % (n, CLAIMS['runs'][str(n)]['leaves']))
    s.data['burnside'] = bs
    # LP certificates: rerun a prefix of each recorded sample (same seeds) and check against the record
    rec = json.loads((DATA / 'referee' / 'lp.json').read_text())
    k = 10 if fast else None
    for n in LPN:
        T = a_of(n) + 1; L = CLAIMS['lp'][str(n)]
        for mode, seed, key in (('random', 1000 + n, 'uniform'), ('balanced', 2000 + n, 'balanced')):
            r = rec['%s_%d' % (mode, n)]
            s.gate(r['checked'] == int(CLAIMS['Lp' + key.capitalize()]) == r['certified_below_T'], 'recorded LP %s n=%d: %d of %d certified < %d' % (mode, n, r['certified_below_T'], r['checked'], T))
            rc, o, e = sh([PY, CODE / 'referee' / 'lp_leaves.py', mode, n, T, k or r['checked'], seed])
            d = json.loads(o)
            s.gate(d['certified_below_T'] == d['checked'] == (k or r['checked']) and float(d['max_certified_bound_float']) <= r['max_certified_bound_float'] + 1e-12,
                   'rerun LP %s n=%d (%d pairs): all certified < %d' % (mode, n, d['checked'], T))
        rb = rec['board_%d' % n]
        if not fast:
            rc, o, e = sh([PY, CODE / 'referee' / 'lp_leaves.py', 'board', n, T, DATA / 'certificates' / 'kamenetsky_best_known_12-30.txt'])
            d = json.loads(o)
            s.gate(d['checked'] == d['certified_below_T'] == rb['checked'] and d['max_certified_bound'] == rb['max_certified_bound'],
                   'rerun LP board neighbourhood n=%d: %d pairs certified, same largest bound' % (n, d['checked']))
        s.gate(rb['checked'] == rb['certified_below_T'] and str(rb['checked']) == L['board_checked'], 'recorded LP board neighbourhood n=%d: %d pairs certified' % (n, rb['checked']))
        mx = max(rec['%s_%d' % (m, n)]['max_certified_bound_float'] for m in ('random', 'balanced', 'board'))
        s.gate(abs(mx - float(L['max_bound_float'])) < 1e-9 and mx < T, 'largest certified LP bound n=%d is %.4f < %d' % (n, mx, T))
    s.gate(CLAIMS['LpNbSixteen'] == CLAIMS['lp']['16']['board_checked'] and CLAIMS['LpNbNineteen'] == CLAIMS['lp']['19']['board_checked'],
           'neighbourhood sizes quoted in the paper')
    return s.finish()


def step_sat(fast=True):
    s = Step('sat')
    nm = 7 if fast else 8
    jobs = [(mode, n, T) for n in range(2, nm + 1) for T in (a_of(n), a_of(n) + 1) if T > 0 for mode in ('queens', 'lines')]
    outs = pmap(lambda j: sh([PY, CODE / 'sat_check.py', j[0], j[1], j[2]])[1], jobs)
    for (mode, n, T), o in zip(jobs, outs):
        s.note(o.strip())
        want = 'SAT' if T <= a_of(n) else 'UNSAT VERIFIED'
        s.gate(o.strip().endswith(want) if want != 'SAT' else o.strip().endswith(' SAT') or o.strip().endswith('SAT None'),
               'SAT %s n=%d T=%d: %s' % (mode, n, T, want))
    # a few random n = 16 leaves (canonical, via pqv --sample), SAT + drat-trim
    k = 10 if fast else 50
    rc, o, e = sh([PQV, 16, 38, 1, '--sample', k, 4711])
    pairs = [l.split()[:2] for l in o.splitlines() if len(l.split()) == 3]
    outs = pmap(lambda p: sh([PY, CODE / 'sat_check.py', 'leaf', 16, 38, p[0], p[1]])[1], pairs)
    for p, o in zip(pairs, outs):
        s.note(o.strip())
        s.gate(o.strip().endswith('UNSAT VERIFIED'), 'n=16 leaf R=%s C=%s UNSAT, proof verified' % tuple(p))
    rec = (DATA / 'sat_samples' / 'results.txt').read_text()
    tags = [' '.join(l.split()[:2]) for l in rec.splitlines() if l.startswith('n1')]
    cubes = re.findall(r'sat: cube (\d+) \d+ ([01]+) UNSAT VERIFIED', rec)
    s.gate((str(tags.count('n16 uniform')), str(tags.count('n16 balanced')), str(tags.count('n12 cube')), str(tags.count('n13 cube'))) ==
           (CLAIMS['SatUniform'], CLAIMS['SatBalanced'], CLAIMS['SatCubesTwelve'], CLAIMS['SatCubesThirteen'])
           and len(cubes) == 11 and all(len(p) == 12 for _, p in cubes) and 'minprod' not in rec,
           'recorded SAT samples: %s uniform + %s balanced n=16 leaves, %s n=12 and %s n=13 cubes with 12 lines fixed' %
           (CLAIMS['SatUniform'], CLAIMS['SatBalanced'], CLAIMS['SatCubesTwelve'], CLAIMS['SatCubesThirteen']))
    m = re.search(r'ALL UNSAT AND VERIFIED: True \((\d+) checks\)', rec)
    s.gate(int(CLAIMS['SatUniform']) + int(CLAIMS['SatBalanced']) == int(CLAIMS['SatSixteenLeaves']), 'n=16 SAT leaves: %s in all' % CLAIMS['SatSixteenLeaves'])
    s.gate(m and m.group(1) == CLAIMS['SatSamples'] and rec.count('UNSAT VERIFIED') == int(CLAIMS['SatSamples']),
           'recorded SAT samples: %s checks, all UNSAT with verified proofs' % CLAIMS['SatSamples'])
    return s.finish()


def step_certificates():
    s = Step('certificates')
    b = check_boards((DATA / 'certificates' / 'ainley_n16_37.txt').read_text())
    s.gate(len(b) == 1 and b[0][:4] == (16, 37, 37, 37) and b[0][5] == 'OK', 'Ainley board n=16: 37 + 37, no attack')
    kb = check_boards((DATA / 'certificates' / 'kamenetsky_best_known_12-30.txt').read_text())
    s.data['kamenetsky'] = [x[:5] for x in kb]
    s.gate(len(kb) == 20 and sorted({x[0] for x in kb}) == list(range(12, 31)) and all(x[5] == 'OK' for x in kb),
           'all 20 boards of the best-known file (n = 12..30, two for n = 13) are peaceable')
    for n in range(12, NMAX + 1):
        mn = max(x[3] for x in kb if x[0] == n)
        s.gate(mn == a_of(n), 'best-known board n=%d has min(W,B) = %d = a(n)' % (n, mn))
    ain = [int(x) for x in CLAIMS['ainley_1_30'].split(',')]          # Ainley's values (OEIS comment), n = 1..30
    best = {n: max(x[3] for x in kb if x[0] == n) for n in range(12, 31)}
    s.gate(all(best[n] == ain[n - 1] for n in range(16, 31) if n != 27) and (best[27], ain[26]) == (106, 105),
           'best-known boards equal Ainley\'s values for 16 <= n <= 30 except n = 27 (106 vs 105)')
    s.gate(all(ain[n - 1] == 7 * n * n // 48 for n in range(14, 31) if n != 27), "Ainley's values equal floor(7n^2/48) for 14 <= n <= 30 except n = 27")
    for n in range(1, NMAX + 1):
        s.gate(a_of(n) == 7 * n * n // 48 + (1 if n in (5, 9) else 0), 'a(%d) = floor(7n^2/48)%s' % (n, ' + 1' if n in (5, 9) else ''))
    return s.finish()


def read_cubes(n):
    T = a_of(n) + 1
    d = DATA / 'runs' / ('n%d_T%d' % (n, T))
    return d, [l.split() for l in (d / 'cubes.sorted.log').read_text().splitlines()]


def step_logs():
    s = Step('logs')
    man = (DATA / 'MANIFEST.sha256').read_text().split('\n')
    bad = []
    for l in man:
        if not l.strip():
            continue
        h, f = l.split(None, 1)
        f = f.strip()
        if not (DATA / f).exists() or sha(DATA / f) != h:
            bad.append(f)
    listed = {l.split(None, 1)[1].strip() for l in man if l.strip()}
    present = {str(p.relative_to(DATA)) for p in DATA.rglob('*') if p.is_file() and p.name != 'MANIFEST.sha256'}
    s.gate(not bad and listed == present, 'data/MANIFEST.sha256: %d files, all hashes match, no unlisted files%s' % (len(listed), (' (bad: %s)' % bad[:5]) if bad else ''))
    for n in BIG:
        T = a_of(n) + 1; R = CLAIMS['runs'][str(n)]
        d, lines = read_cubes(n)
        rc, o, e = sh([PQ2, n, T, '-K', 4, '-list'], nice=False)
        cl = [l.split() for l in o.splitlines() if l.startswith('cube ')]
        s.gate(len(cl) == int(CLAIMS['Cubes']) and o == (d / 'cubes.txt').read_text(), 'n=%d: pq2 -list gives the recorded %d cubes' % (n, len(cl)))
        ok_ids = [int(x[1]) for x in lines] == list(range(len(cl))) and all(x[2] == c[2] for x, c in zip(lines, cl))
        s.gate(ok_ids, 'n=%d: one log line per cube, ids and prefixes match the cube list' % n)
        s.gate(all(x[-1] == 'UNSAT' for x in lines), 'n=%d: every cube UNSAT' % n)
        tot = {k: sum(int(kv(' '.join(x))[k]) for x in lines) for k in ('leaves', 'searched', 'flows', 'n1', 'n2')}
        cpu = sum(float(kv(' '.join(x))['time']) for x in lines)
        s.data['n%d' % n] = dict(tot, cpu_seconds=round(cpu, 3))
        s.gate(str(tot['leaves']) == R['leaves'] and str(tot['flows']) == R['flows'] and str(tot['searched']) == R['searched'] == '0',
               'n=%d: totals leaves=%d flows=%d searched=%d match claims' % (n, tot['leaves'], tot['flows'], tot['searched']))
        s.gate('%.3f' % cpu == R['cpu_seconds'], 'n=%d: CPU time %.3f s matches claims' % (n, cpu))
        summ = (d / 'summary.txt').read_text()
        s.gate('VERDICT: INFEASIBLE' in summ and 'sha256 pq2.c %s' % CLAIMS['sha_pq2c'] in summ and
               'sha256 cubes.sorted.log %s' % hashlib.sha256((d / 'cubes.sorted.log').read_bytes()).hexdigest() in summ,
               'n=%d: summary.txt says INFEASIBLE, names the pq2.c source hash and the hash of the cube log' % n)
    # Table rows n <= 15 (recorded monolithic runs) and the time column for every n
    for n in range(3, 16):
        T = a_of(n) + 1; R = CLAIMS['runs'][str(n)]
        p = parse_pq2((DATA / 'validation' / ('pq2_n%d_T%d.out' % (n, T))).read_text())
        q = parse_pqv((DATA / 'validation' / ('pqv_n%d_T%d.out' % (n, T))).read_text())
        s.gate(p['verdict'] == 'INFEASIBLE' and p['leaves'] == R['leaves'] and p['leafSearched'] == R['searched'] == '0' and p['time'] == R['cpu_seconds']
               and q['verdict'] == 'INFEASIBLE' and str(q['leaves']) == R['leaves'],
               'table row n=%d: recorded runs of both programs INFEASIBLE, %s orbits, %s s' % (n, p['leaves'], p['time']))
    for n in range(3, NMAX + 1):
        R = CLAIMS['runs'][str(n)]
        s.gate(R['time_tex'] == fmt_time(float(R['cpu_seconds'])) and R['T'] == str(a_of(n) + 1) and R['a'] == str(a_of(n)), 'table row n=%d: a, T and time formatted from the record' % n)
    tab = (DATA / 'validation' / 'TABLE.txt').read_text()
    rows = [l.split('|') for l in tab.splitlines() if l.startswith('n=')]
    filled = lambda col: sorted({int(re.match(r'n=\s*(\d+)', r[0]).group(1)) for r in rows if r[col].strip() != '-'})
    s.gate('ALL CONSISTENT WITH OEIS: True' in tab and filled(3) == filled(4) == list(range(1, int(CLAIMS['NosymN']) + 1))
           and filled(5) == filled(6) == list(range(1, int(CLAIMS['SatN']) + 1)) and filled(1) == filled(2) == list(range(1, 16)),
           'recorded validation table: pq2/pqv n <= 15, -nosym/--nobound n <= %s, SAT+DRUP n <= %s, all consistent' % (CLAIMS['NosymN'], CLAIMS['SatN']))
    ws = [int(x) for n in BIG for x in re.findall(r'workers=(\d+)', (read_cubes(n)[0] / 'progress.log').read_text())]
    s.gate(str(max(ws)) == CLAIMS['WorkersMax'], 'local cube runs used at most %d processes' % max(ws))
    for n, key in ((19, 'ReplayNineteen'), (20, 'ReplayTwenty')):
        if n > NMAX: continue
        t = (read_cubes(n)[0] / 'local_replay_of_modal_cubes.txt').read_text()
        k = t.count(' identical '); m = re.search(r'replayed (\d+) Modal-computed cubes locally: (\d+) differences', t)
        s.gate(m and int(m.group(1)) == k == int(CLAIMS[key]) and m.group(2) == '0' and 'DIFFERENT' not in t,
               'n=%d: %d cloud-computed cubes rerun locally, all identical apart from time' % (n, k))
    # second implementation, complete runs
    for n in (16, 17):
        p = parse_pqv((DATA / 'pqv' / ('pqv_n%d_T%d.out' % (n, a_of(n) + 1))).read_text())
        s.gate(p['verdict'] == 'INFEASIBLE' and str(p['leaves']) == CLAIMS['runs'][str(n)]['leaves'] == str(p['pruned']) and p['searched'] == 0,
               'pqv complete run n=%d: INFEASIBLE, %d orbits (= pq2), all pruned at the root' % (n, p['leaves']))
    # second implementation, slices
    for n in PQVN:
        P = CLAIMS['pqv_parts'][str(n)]; m = int(P['m'])
        rows = [l.split() for l in (DATA / 'pqv' / ('pqv_n%d_T%d_parts.log' % (n, a_of(n) + 1))).read_text().splitlines() if l.startswith('part ')]
        js = [int(r[1]) for r in rows]
        s.gate(len(set(js)) == len(js) and all(0 <= j < m for j in js) and sorted(js) == sorted(int(x) for x in P['parts']) and all(int(r[2]) == m for r in rows),
               'pqv slices n=%d: %d distinct slices of the %d' % (n, len(js), m))
        s.gate(all(r[r.index('verdict') + 1] == 'INFEASIBLE' and r[r.index('searched') + 1] == '0' and r[r.index('leaves') + 1] == r[r.index('pruned') + 1] for r in rows),
               'pqv slices n=%d: every slice INFEASIBLE, every orbit pruned at the root' % n)
        lv = sum(int(r[r.index('leaves') + 1]) for r in rows)
        s.gate(str(lv) == P['leaves'], 'pqv slices n=%d cover %d orbits (claims %s)' % (n, lv, P['leaves']))
        if len(js) == m:
            s.gate(str(lv) == CLAIMS['runs'][str(n)]['leaves'], 'pqv n=%d: all %d slices done, %d orbits = the pq2 and Burnside count' % (n, m, lv))
    # pqv slices are disjoint subsets of the orbit set, so their total cannot exceed it
    for n in PQVN:
        s.gate(int(CLAIMS['pqv_parts'][str(n)]['leaves']) <= int(CLAIMS['runs'][str(n)]['leaves']), 'n=%d slice total <= orbit total' % n)
    return s.finish()


def step_replay(fast=True):
    s = Step('replay')
    rng = random.Random(20261119)
    picks = []
    for n, k in [(16, 12 if fast else 60), (17, 3 if fast else 20)] + [(m, 2 if fast else 10) for m in BIG if m >= 18]:
        d, lines = read_cubes(n)
        # sample among the cheaper cubes (by recorded time) so that the default run stays short
        cheap = sorted(lines, key=lambda x: float(kv(' '.join(x))['time']))[:len(lines) // (8 if fast else 2)]
        for x in rng.sample(cheap, k):
            picks.append((n, x))

    def go(p):
        n, x = p
        rc, o, e = sh([PQ2, n, a_of(n) + 1, '-K', 4, '-cube', '%s:%d' % (x[1], int(x[1]) + 1)])
        return [l.split() for l in o.splitlines() if l.startswith('cube ')]
    outs = pmap(go, picks)
    strip = lambda p: [v for i, v in enumerate(p) if i != p.index('time') + 1]
    for (n, x), o in zip(picks, outs):
        same = len(o) == 1 and strip(o[0]) == strip(x)
        s.note('n=%d cube %s: %s' % (n, x[1], 'identical' if same else 'DIFFERENT %s' % o))
        s.gate(same, 'n=%d cube %s rerun: identical log line' % (n, x[1]))
    return s.finish()


def step_side(fast=True):
    s = Step('side')
    known = [int(x) for x in CLAIMS['a260680_known'].split(',')]          # n = 1..10
    nmax = 9 if fast else 10
    for n in range(3, nmax + 1):
        p1 = subprocess.Popen(['nice', '-n', '10', str(PQENUM), str(n), str(a_of(n))], stdout=subprocess.PIPE)
        o = subprocess.run([PY, str(CODE / 'count_configs.py'), str(n), str(a_of(n))], stdin=p1.stdout, capture_output=True, text=True).stdout
        p1.wait()
        m = re.search(r'inequivalent configurations=(\d+) non-peaceful=(\d+)', o); s.note(o.strip())
        s.gate(m and int(m.group(1)) == known[n - 1] and m.group(2) == '0', 'A260680(%d) = %d reproduced' % (n, known[n - 1]))
    for n in range(11, 16):
        o = (DATA / 'side' / ('a260680_n%d.txt' % n)).read_text()
        m = re.search(r'n=%d a=%d .*inequivalent configurations=(\d+) non-peaceful=0' % (n, a_of(n)), o)
        s.gate(m and m.group(1) == CLAIMS['Enum' + ['Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen'][n - 11]], 'recorded A260680(%d) = %s' % (n, m.group(1) if m else '?'))
    sd = DATA / 'side' / 'a260680_n16'
    summ = (sd / 'summary.txt').read_text()
    s.gate('65536 cube lines, ids 0..65535 each once: True' in summ and str(65536) == CLAIMS['EnumCubesSixteen'], 'A260680(16): all %s cubes of the enumeration completed' % CLAIMS['EnumCubesSixteen'])
    lst = subprocess.run([str(PQENUM), '16', '37', '-K', '4', '-list'], capture_output=True, text=True).stdout
    s.gate('sha256 cubes.txt (pqenum 16 37 -K 4 -list) %s' % hashlib.sha256(lst.encode()).hexdigest() in summ, 'A260680(16): the cube list is regenerated identically')
    boards = '\n'.join(l.split(None, 1)[1] for l in (sd / 'boards.txt').read_text().splitlines()) + '\n'
    o = subprocess.run([PY, str(CODE / 'count_configs.py'), '16', '37'], input=boards, capture_output=True, text=True).stdout
    m = re.search(r'labellings=(\d+) distinct cell-boards=(\d+) inequivalent configurations=(\d+) non-peaceful=(\d+)', o); s.note(o.strip())
    s.gate(m and (m.group(1), m.group(3), m.group(4)) == (CLAIMS['EnumLabSixteen'], CLAIMS['EnumSixteen'], '0') and o.strip() == (sd / 'count.txt').read_text().strip()
           and int(CLAIMS['EnumLabSixteen']) == 16 * int(CLAIMS['EnumSixteen']),
           'A260680(16) recounted from the recorded boards: %s labellings, %s inequivalent configurations, all peaceful' % (CLAIMS['EnumLabSixteen'], CLAIMS['EnumSixteen']))
    tv = (DATA / 'side' / 'torus_valid' / 'summary.txt').read_text()
    p52 = re.findall(r'^n20_T52 part \d+ 60 torus n=20 T=52 INFEASIBLE reps=\d+ pairs=(\d+) leaves=\d+ searched=(\d+)', tv, re.M)
    s.gate(len(p52) == 60 and str(sum(int(a) for a, b in p52)) == CLAIMS['TorusPairs'] and str(sum(int(b) for a, b in p52)) == CLAIMS['TorusSearched'],
           'split torus program reproduces n=20, T=52 exactly (60 parts: %s orbits, %s searched)' % (CLAIMS['TorusPairs'], CLAIMS['TorusSearched']))
    tk = [int(x) for x in CLAIMS['a279405_known'].split(',')]              # n = 1..18
    for n in range(4, 13 if fast else 15):
        for T in (tk[n - 1], tk[n - 1] + 1):
            rc, o, e = sh([PQT, n, T]); s.note(o.strip()[:300])
            want = 'FEASIBLE' if T == tk[n - 1] else 'INFEASIBLE'
            s.gate(re.search(r'torus n=%d T=%d %s ' % (n, T, want), o) and 'BAD' not in o, 'torus n=%d T=%d %s' % (n, T, want))
    o51 = (DATA / 'side' / 'pqt_n20_T51.out').read_text(); o52 = (DATA / 'side' / 'pqt_n20_T52.out').read_text()
    m = re.search(r'torus n=20 T=52 INFEASIBLE reps=\d+ pairs=(\d+) leaves=\d+ searched=(\d+)', o52)
    s.gate('torus n=20 T=51 FEASIBLE' in o51 and m and m.group(1) == CLAIMS['TorusPairs'] and m.group(2) == CLAIMS['TorusSearched'],
           'recorded torus n=20: 51 feasible, 52 infeasible (%s orbits, %s searched)' % (CLAIMS['TorusPairs'], CLAIMS['TorusSearched']))
    tm = re.search(r'time=([\d.]+)s', o52)
    s.gate(str(round(float(tm.group(1)) / 60)) == CLAIMS['TorusMinutes'], 'torus n=20 T=52 took %s CPU minutes' % CLAIMS['TorusMinutes'])
    p = subprocess.run([PY, str(CODE / 'check_torus.py'), str(DATA / 'side' / 'pqt_n20_T51.out')], capture_output=True, text=True).stdout
    s.gate('torus n=20 white=51 black=51 attacks=0 OK' in p, 'torus n=20 board: 51 + 51, no toroidal attack (direct check)')
    return s.finish()


def step_paper():
    s = Step('paper')
    rc, o, e = sh([PY, ROOT / 'scripts' / 'make_claims_tex.py', '--check'], nice=False)
    s.gate(rc == 0, 'paper/claims.tex is in sync with claims.json')
    tex = (ROOT / 'paper' / 'peaceable-queens.tex').read_text()
    body = re.sub(r'%.*', '', tex.split(r'\begin{document}')[1].split(r'\begin{thebibliography}')[0])
    used = set(re.findall(r'\\cl([A-Za-z]+)', body))
    defined = set(re.findall(r'\\newcommand\{\\cl([A-Za-z]+)\}', (ROOT / 'paper' / 'claims.tex').read_text()))
    s.gate(used <= defined, 'every \\cl macro used in the paper is defined in claims.tex')
    fig = re.search(r'\\begin\{tabular\}\{l\}\n(.*?)\\end\{tabular\}', tex, re.S).group(1)
    figrows = [r.replace('\\\\', '').replace(' ', '') for r in fig.strip().splitlines()]
    cert = [l.replace(' ', '') for l in (DATA / 'certificates' / 'ainley_n16_37.txt').read_text().splitlines() if l and not l.startswith('#')]
    s.gate(figrows == cert, 'Figure 1 is the checked n=16 certificate board')
    rc, o, e = sh(['latexmk', '-pdf', '-interaction=nonstopmode', '-halt-on-error', 'peaceable-queens.tex'], nice=False, cwd=ROOT / 'paper')
    log = (ROOT / 'paper' / 'peaceable-queens.log').read_text(errors='replace')
    warn = [l for l in log.splitlines() if re.search(r'Warning|Overfull|Underfull', l)]
    s.note('\n'.join(warn))
    s.gate(rc == 0, 'paper builds with latexmk')
    s.gate(not warn, 'no LaTeX warnings or bad boxes (%d found)' % len(warn))
    m = re.search(r'Output written on peaceable-queens.pdf \((\d+) pages', log)
    s.data['pages'] = int(m.group(1)) if m else None
    s.gate(m and m.group(1) == CLAIMS['pages'], 'the PDF has %s pages' % (m.group(1) if m else '?'))
    return s.finish()


def step_full(n):
    s = Step('full_n%d' % n)
    T = a_of(n) + 1
    out = OUT / ('full_n%d_T%d' % (n, T))
    rc, o, e = sh([PY, CODE / 'run_cubes.py', n, T, 4, JOBS, out], nice=False)
    s.note(o + e)
    d, lines = read_cubes(n)
    new = [l.split() for l in (out / 'cubes.sorted.log').read_text().splitlines()]
    strip = lambda p: [v for i, v in enumerate(p) if i != p.index('time') + 1]
    diff = [x[1] for x, y in zip(lines, new) if strip(x) != strip(y)]
    s.gate(len(new) == len(lines) and not diff, 'n=%d: all %d cubes rerun, every log line identical apart from time' % (n, len(lines)))
    return s.finish()


def step_full_pqv(n):
    s = Step('full_pqv_n%d' % n)
    rc, o, e = sh([PQV, n, a_of(n) + 1, JOBS]); s.note(o)
    p = parse_pqv(o)
    s.gate(p['verdict'] == 'INFEASIBLE' and str(p['leaves']) == CLAIMS['runs'][str(n)]['leaves'] and p['searched'] == 0,
           'pqv n=%d complete: INFEASIBLE, %d orbits (= pq2)' % (n, p['leaves']))
    return s.finish()


def step_tamper():
    s = Step('tamper')
    files = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True).stdout.split()
    with tempfile.TemporaryDirectory() as td:
        def copy():
            dst = Path(td) / ('r%d' % len(list(Path(td).iterdir())))
            for f in files:
                (dst / f).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ROOT / f, dst / f)
            shutil.copytree(BUILD, dst / 'build', symlinks=True, ignore=shutil.ignore_patterns('cargo'))
            return dst

        def run(dst, only):
            r = subprocess.run([PY, str(dst / 'scripts' / 'verify.py'), '--only', only], cwd=dst, capture_output=True, text=True, env=ENV)
            return r.returncode
        base = copy()
        s.gate(run(base, 'logs,certificates') == 0, 'untouched copy passes the logs and certificates gates')
        cases = []
        c = json.loads((base / 'claims.json').read_text())
        dst = copy(); c2 = json.loads(json.dumps(c)); c2['runs']['19']['leaves'] = str(int(c2['runs']['19']['leaves']) + 1)
        (dst / 'claims.json').write_text(json.dumps(c2, indent=1)); cases.append(('claims.json: n=19 orbit count + 1', dst, 'logs'))
        dst = copy(); c2 = json.loads(json.dumps(c)); c2['aNineteen'] = '53'
        (dst / 'claims.json').write_text(json.dumps(c2, indent=1)); cases.append(('claims.json: a(19) = 53', dst, 'certificates'))
        dst = copy(); f = dst / 'data' / 'runs' / 'n19_T53' / 'cubes.sorted.log'
        t = f.read_text().splitlines(); t[1234] = t[1234].replace('UNSAT', 'FOUND'); f.write_text('\n'.join(t) + '\n')
        cases.append(('cube log n=19: one cube UNSAT -> FOUND', dst, 'logs'))
        dst = copy(); f = dst / 'data' / 'runs' / 'n18_T48' / 'cubes.sorted.log'
        t = f.read_text().splitlines(); del t[77]; f.write_text('\n'.join(t) + '\n')
        cases.append(('cube log n=18: one cube line deleted', dst, 'logs'))
        dst = copy(); f = dst / 'data' / 'certificates' / 'ainley_n16_37.txt'
        f.write_text(f.read_text().replace('B . . . . . . . B B B B . . . .', 'B . . . . . . . B B B B . . . W', 1))
        cases.append(('Ainley board: one white queen added in an attacked cell', dst, 'certificates'))
        for name, dst, only in cases:
            rc = run(dst, only)
            s.note('%s -> exit %d' % (name, rc))
            s.gate(rc != 0, 'tampered copy fails (%s)' % name)
    return s.finish()


def main():
    global JOBS
    ap = argparse.ArgumentParser()
    ap.add_argument('--only'); ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--full', type=int, action='append', default=[]); ap.add_argument('--full-pqv', type=int, action='append', default=[])
    ap.add_argument('--tamper', action='store_true')
    ap.add_argument('--thorough', action='store_true', help='larger variants of the small, referee, sat, replay and side steps')
    a = ap.parse_args(); JOBS = a.jobs
    fast = not a.thorough
    steps = ['build', 'unit', 'small', 'referee', 'sat', 'certificates', 'logs', 'replay', 'side', 'paper']
    sel = a.only.split(',') if a.only else steps
    OUT.mkdir(exist_ok=True)
    fns = {'build': step_build, 'unit': step_unit, 'small': lambda: step_small(13 if fast else 15),
           'referee': lambda: step_referee(fast), 'sat': lambda: step_sat(fast), 'certificates': step_certificates,
           'logs': step_logs, 'replay': lambda: step_replay(fast), 'side': lambda: step_side(fast), 'paper': step_paper}
    need_build = any(x in sel for x in ('unit', 'small', 'sat', 'logs', 'replay', 'side')) or a.full or a.full_pqv
    if need_build and 'build' not in sel and not (PQ2.exists() and PQV.exists()):
        sel = ['build'] + sel
    def guarded(name, f):
        try:
            return f()
        except Exception as exc:                  # a crash in a step is a failed gate, not a pass
            print('%-14s FAIL  (exception %r)' % (name, exc), flush=True)
            return {'name': name, 'ok': False, 'gates': [{'ok': False, 'check': 'exception: %r' % exc}]}
    res = [guarded(x, fns[x]) for x in steps if x in sel]
    for n in a.full:
        res.append(step_full(n))
    for n in a.full_pqv:
        res.append(step_full_pqv(n))
    if a.tamper:
        res.append(step_tamper())
    ok = all(r['ok'] for r in res)
    if not a.only:
        pdf = ROOT / 'paper' / 'peaceable-queens.pdf'
        summary = {'ok': ok, 'steps': res, 'claims_sha256': sha(ROOT / 'claims.json'),
                   'manifest_sha256': sha(DATA / 'MANIFEST.sha256'), 'pdf_sha256': sha(pdf) if pdf.exists() else None,
                   'python': sys.version.split()[0]}
        (OUT / 'summary.json').write_text(json.dumps(summary, indent=1) + '\n')
    print('ALL GATES PASSED' if ok else 'SOME GATES FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
