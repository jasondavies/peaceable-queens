"""Run manifests for the resumable drivers (run_cubes.py, run_enum.py, run_torus.py, run_pqv_parts.py).

A driver that writes into OUTDIR first creates OUTDIR/run_manifest.json, which records everything that
determines the results (program, n, T and all options, SHA-256 of the source, SHA-256 of the work list).
It is written once, before the first computation, and never changed.  A later run in the same OUTDIR must
present an identical manifest, or the driver refuses to start (so results computed for one T can never be
reused for another).  Each session (start of a driver) appends one line to OUTDIR/sessions.log with the
binary's SHA-256, the machine type and the number of result lines already present, so every result line can
be attributed to the binary that produced it.
A directory that already has results but no manifest (made by an older driver) is refused unless the
caller passes adopt=True, which writes a manifest for it after the fact (and says so in the manifest)."""
import hashlib, json, os, platform, sys, time


def sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()


def sha_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def die(msg):
    sys.stderr.write('REFUSED: ' + msg + '\n')
    sys.exit(3)


def bind(outdir, manifest, binary, results_file, adopt=False):
    """Create or check OUTDIR/run_manifest.json and append a session line.  `manifest` is a dict of
    JSON-serialisable values; `results_file` is the driver's completion log (may not exist yet)."""
    os.makedirs(outdir, exist_ok=True)
    mp = os.path.join(outdir, 'run_manifest.json')
    has_results = os.path.exists(results_file) and os.path.getsize(results_file) > 0
    if os.path.exists(mp):
        old = json.load(open(mp))
        old_core = {k: v for k, v in old.items() if k != 'adopted'}
        if old_core != manifest:
            diff = sorted(k for k in set(old_core) | set(manifest) if old_core.get(k) != manifest.get(k))
            die('%s was made by a different run (fields differ: %s); use a fresh directory' % (mp, ', '.join(diff)))
    else:
        if has_results and not adopt:
            die('%s already holds results but has no run manifest; use a fresh directory' % outdir)
        m = dict(manifest)
        if has_results:
            m['adopted'] = 'manifest written after results existed (%s)' % time.ctime()
        tmp = mp + '.tmp'
        json.dump(m, open(tmp, 'w'), indent=1, sort_keys=True)
        os.replace(tmp, mp)
    nres = sum(1 for _ in open(results_file)) if os.path.exists(results_file) else 0
    with open(os.path.join(outdir, 'sessions.log'), 'a') as f:
        f.write('%s binary_sha256 %s machine %s results_before %d argv %s\n' %
                (time.strftime('%Y-%m-%dT%H:%M:%S'), sha_file(binary), platform.machine(), nres, ' '.join(sys.argv[1:])))


def read_lines_checked(path, check, repair=True):
    """Read a completion log; `check(fields)` returns (key, ok, why).  An unterminated final line (an
    interrupted write) is ignored with a warning, and removed from the file if `repair` (single-writer
    drivers); any other bad or duplicate line stops the driver."""
    done = {}
    if not os.path.exists(path):
        return done
    data = open(path).read()
    lines = data.split('\n')
    if lines and lines[-1] != '':
        sys.stderr.write('warning: ignoring unterminated last line of %s: %r\n' % (path, lines[-1][:80]))
        if repair:
          with open(path, 'w') as f:
            f.write('\n'.join(lines[:-1]) + ('\n' if len(lines) > 1 else ''))
    for i, l in enumerate(lines[:-1]):
        if not l.strip():
            continue
        key, ok, why = check(l.split())
        if not ok:
            die('%s line %d is not a valid result line (%s): %r' % (path, i + 1, why, l[:120]))
        if key in done:
            die('%s line %d repeats result %r' % (path, i + 1, key))
        done[key] = l
    return done
