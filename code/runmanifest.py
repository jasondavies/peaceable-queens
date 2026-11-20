"""Run manifests for the resumable drivers (run_cubes.py, run_enum.py, run_torus.py, run_pqv_parts.py).

A driver that writes into OUTDIR first binds it to OUTDIR/run_manifest.json, which records everything that
determines the results (program, n, T and all options, SHA-256 of the source, SHA-256 of the work list).
The manifest is created once, before the first computation, and never changed.  A later run in the same
OUTDIR must present an identical manifest, or the driver refuses to start, so results computed for one T
can never be reused for another.

Concurrency.  Creation and comparison happen under an exclusive lock on OUTDIR/.manifest.lock (fcntl.flock).
The manifest is written to a uniquely named temporary file and published with os.link, which fails if the
manifest already exists, so a competing process can never replace a published manifest; after publishing,
the manifest is read back and compared again.  Single-writer drivers (run_cubes, run_enum, run_torus) also
hold an exclusive lock on OUTDIR/.driver.lock for their whole run, so a second driver in the same directory
is refused instead of interleaving its results; run_pqv_parts takes that lock shared, because several of
its drivers may fill disjoint slices of one directory.

Each session appends one line to OUTDIR/sessions.log with the binary's SHA-256, the machine type and the
number of result lines already present, so every result line can be attributed to the binary that produced
it.  A directory that already has results but no manifest (made by an older driver) is refused unless the
caller passes adopt=True, which writes a manifest for it after the fact (and says so in the manifest).

For tests, PQ_MANIFEST_PAUSE=<path> makes bind() wait, after writing its temporary file and before
publishing it, until <path> exists (it first creates <path>.reached.<pid>), so interleavings can be forced."""
import fcntl, hashlib, json, os, platform, sys, tempfile, time

_held = []          # lock files held for the life of the process


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


def _pause_hook():
    p = os.environ.get('PQ_MANIFEST_PAUSE')
    if p:
        open(p + '.reached.%d' % os.getpid(), 'w').close()
        while not os.path.exists(p):
            time.sleep(0.02)


def _core(m):
    return {k: v for k, v in m.items() if k != 'adopted'}


def bind(outdir, manifest, binary, results_file, adopt=False, exclusive=True):
    """Create or check OUTDIR/run_manifest.json and append a session line.  `manifest` is a dict of
    JSON-serialisable values; `results_file` is the driver's completion log (may not exist yet)."""
    os.makedirs(outdir, exist_ok=True)
    drv = open(os.path.join(outdir, '.driver.lock'), 'a+')
    try:
        fcntl.flock(drv, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except BlockingIOError:
        die('another driver is running in %s' % outdir)
    _held.append(drv)
    mp = os.path.join(outdir, 'run_manifest.json')
    with open(os.path.join(outdir, '.manifest.lock'), 'a+') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        has_results = os.path.exists(results_file) and os.path.getsize(results_file) > 0
        if not os.path.exists(mp):
            if has_results and not adopt:
                die('%s already holds results but has no run manifest; use a fresh directory' % outdir)
            m = dict(manifest)
            if has_results:
                m['adopted'] = 'manifest written after results existed (%s)' % time.ctime()
            fd, tmp = tempfile.mkstemp(prefix='.manifest-tmp.', dir=outdir)
            with os.fdopen(fd, 'w') as f:
                json.dump(m, f, indent=1, sort_keys=True); f.flush(); os.fsync(f.fileno())
            _pause_hook()
            try:
                os.link(tmp, mp)                 # atomic create-if-absent: never replaces a published manifest
            except FileExistsError:
                pass
            os.unlink(tmp)
        old = json.load(open(mp))
        if _core(old) != manifest:
            diff = sorted(k for k in set(_core(old)) | set(manifest) if _core(old).get(k) != manifest.get(k))
            die('%s was made by a different run (fields differ: %s); use a fresh directory' % (mp, ', '.join(diff)))
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


def require_work(n_items, what):
    """Defence in depth: an empty work list must never turn into an INFEASIBLE verdict."""
    if n_items < 1:
        die('empty work list (%s): refusing to compute a verdict' % what)
