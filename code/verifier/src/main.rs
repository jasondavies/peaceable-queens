// pqv -- independent verifier for peaceable queens (OEIS A250000), written separately from src/pq2.c.
//
// Decides whether some labelling of the 6n-2 lines (W/B) has >= T W-cells and >= T B-cells.
// Differences from pq2.c (on purpose):
//  * rows/columns are enumerated as two n-bit masks (R, C); symmetry reduction keeps (R,C) iff its
//    integer code R<<n|C is minimal among the 16 images (R or rev R, C or rev C, possibly swapped,
//    possibly both complemented) -- a different canonical form from pq2's lex-prefix rule;
//  * the Lagrangian bound uses the generic max-closure network with one auxiliary node per candidate
//    cell (no pairwise reduction), solved with a FIFO push-relabel max-flow (pq2 uses Dinic);
//  * lambda = p/1000 with its own search; any (R,C) not pruned is searched by a plain DFS over the
//    diagonal/antidiagonal labels with only the counting bound (no min cut at all).
// Multi-threaded over R (std::thread only).
// usage: pqv n T [threads] [--nosym] [--nobound] [--part j m] [--sample k seed]   (sample: test only k random canonical (R,C))
use std::env;
use std::sync::atomic::{AtomicU64, AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;

const QP: i64 = 1000;

fn rev(x: u32, n: usize) -> u32 { let mut r = 0; for i in 0..n { if x >> i & 1 == 1 { r |= 1 << (n - 1 - i); } } r }

struct Inst { n: usize, t: i64 }

// candidate cells for the diag/anti subproblem
struct Sub {
    nd: usize,
    wc: Vec<(usize, usize)>, // W-candidate cells as (diag, anti)
    bc: Vec<(usize, usize)>,
}

fn build_sub(inst: &Inst, r: u32, c: u32) -> Sub {
    let n = inst.n;
    let mut wc = Vec::new(); let mut bc = Vec::new();
    for i in 0..n { for j in 0..n {
        let ri = r >> i & 1 == 1; let cj = c >> j & 1 == 1;
        let d = i + n - 1 - j; let a = i + j;
        if ri && cj { wc.push((d, a)); } else if !ri && !cj { bc.push((d, a)); }
    }}
    Sub { nd: 2 * n - 1, wc, bc }
}

// ---------- FIFO push-relabel ----------
struct Net { n: usize, head: Vec<usize>, to: Vec<usize>, cap: Vec<i64>, nxt: Vec<usize> }
const NIL: usize = usize::MAX;
impl Net {
    fn new(n: usize) -> Net { Net { n, head: vec![NIL; n], to: vec![], cap: vec![], nxt: vec![] } }
    fn add(&mut self, u: usize, v: usize, c: i64) {
        if c <= 0 { return; }
        self.to.push(v); self.cap.push(c); self.nxt.push(self.head[u]); self.head[u] = self.to.len() - 1;
        self.to.push(u); self.cap.push(0); self.nxt.push(self.head[v]); self.head[v] = self.to.len() - 1;
    }
    // exact distance-to-sink labels in the residual graph (n = unreachable)
    fn global_relabel(&self, t: usize, h: &mut Vec<usize>) {
        let n = self.n; for x in h.iter_mut() { *x = n; }
        let mut q = std::collections::VecDeque::new(); h[t] = 0; q.push_back(t);
        while let Some(v) = q.pop_front() { let mut e = self.head[v];
            // residual edge u->v exists iff cap of the reverse of edge (v->u) is > 0, i.e. cap[e^1] > 0
            while e != NIL { let u = self.to[e]; if self.cap[e ^ 1] > 0 && h[u] == n { h[u] = h[v] + 1; q.push_back(u); } e = self.nxt[e]; } }
    }
    // First phase of FIFO push-relabel (Goldberg-Tarjan) with global relabelling: computes the value of a
    // maximum preflow = max flow value = min cut capacity.  Nodes with label >= n are inactive.
    fn maxflow(&mut self, s: usize, t: usize) -> i64 {
        let n = self.n;
        let mut h = vec![0usize; n]; let mut ex = vec![0i64; n];
        let mut cur: Vec<usize> = self.head.clone();
        let mut q = std::collections::VecDeque::new(); let mut inq = vec![false; n];
        let mut e = self.head[s];
        while e != NIL { let v = self.to[e]; let c = self.cap[e];
            if c > 0 { self.cap[e] -= c; self.cap[e ^ 1] += c; ex[v] += c; ex[s] -= c; }
            e = self.nxt[e]; }
        self.global_relabel(t, &mut h); h[s] = n;
        for v in 0..n { if v != s && v != t && ex[v] > 0 && h[v] < n { inq[v] = true; q.push_back(v); } }
        let mut relabels = 0usize;
        while let Some(u) = q.pop_front() {
            inq[u] = false;
            while ex[u] > 0 && h[u] < n {
                if cur[u] == NIL {
                    let mut mh = n; let mut e = self.head[u];
                    while e != NIL { if self.cap[e] > 0 { mh = mh.min(h[self.to[e]] + 1); } e = self.nxt[e]; }
                    h[u] = mh.min(n); cur[u] = self.head[u]; relabels += 1;
                    if relabels % n == 0 { self.global_relabel(t, &mut h); h[s] = n;
                        for v in 0..n { cur[v] = self.head[v]; if v != s && v != t && ex[v] > 0 && h[v] < n && !inq[v] && v != u { inq[v] = true; q.push_back(v); } } }
                    continue;
                }
                let e = cur[u]; let v = self.to[e];
                if self.cap[e] > 0 && h[u] == h[v] + 1 {
                    let d = ex[u].min(self.cap[e]);
                    self.cap[e] -= d; self.cap[e ^ 1] += d; ex[u] -= d; ex[v] += d;
                    if v != s && v != t && !inq[v] && h[v] < n { inq[v] = true; q.push_back(v); }
                } else { cur[u] = self.nxt[e]; }
            }
        }
        ex[t]
    }
    // source side of a minimum cut: nodes that cannot reach t in the residual graph
    fn source_side(&self, _s: usize) -> Vec<bool> {
        let n = self.n; let mut h = vec![0usize; n]; self.global_relabel(self.n - 1, &mut h);
        (0..n).map(|v| h[v] == n).collect()
    }
}

// max over labellings x of diag/anti: p*W(x) + (QP-p)*B(x), via max closure:
// W-cell node w (gain p) requires both its lines W; B-cell node b (gain QP-p) requires both its lines B.
// Network: line node in source side <=> line W.  W-cell: s->w (p), w->d (inf), w->a (inf).
// B-cell: b->t (QP-p), d->b (inf), a->b (inf).   value = total gains - mincut.
// Also returns the W,B counts of the labelling read off the cut.
fn upper(sub: &Sub, p: i64) -> (i64, i64, i64) {
    let nd = sub.nd; let nl = 2 * nd;
    let nw = sub.wc.len(); let nb = sub.bc.len();
    let s = nl + nw + nb; let t = s + 1;
    let mut net = Net::new(t + 1);
    let inf = 1i64 << 40;
    let (a, b) = (p, QP - p);
    let mut gains = 0;
    if a > 0 { for (k, &(d, an)) in sub.wc.iter().enumerate() { let w = nl + k; net.add(s, w, a); net.add(w, d, inf); net.add(w, nd + an, inf); gains += a; } }
    if b > 0 { for (k, &(d, an)) in sub.bc.iter().enumerate() { let v = nl + nw + k; net.add(v, t, b); net.add(d, v, inf); net.add(nd + an, v, inf); gains += b; } }
    let f = net.maxflow(s, t);
    let side = net.source_side(s);
    let mut w = 0; let mut bb = 0;
    for &(d, an) in &sub.wc { if side[d] && side[nd + an] { w += 1; } }
    for &(d, an) in &sub.bc { if !side[d] && !side[nd + an] { bb += 1; } }
    (gains - f, w, bb)
}

// returns Some(true) if a solution was found, Some(false) if pruned
fn lagrange_prune(sub: &Sub, t: i64) -> Option<bool> {
    // golden-section-free: integer ternary-ish search using the subgradient (W - B)
    let (mut lo, mut hi) = (0i64, QP);
    for _ in 0..30 {
        let p = (lo + hi) / 2;
        let (u, w, b) = upper(sub, p);
        if w >= t && b >= t { return Some(true); }
        if u < QP * t { return Some(false); }
        if w > b { hi = p - 1; } else if w < b { lo = p + 1; } else { return None; }
        if lo > hi { return None; }
    }
    None
}

// plain DFS over diag/anti labels with counting bound only
fn plain_dfs(sub: &Sub, t: i64) -> bool {
    let nd = sub.nd; let nl = 2 * nd;
    let mut lab = vec![-1i8; nl];
    // order: by number of candidate cells, descending
    let mut deg = vec![0usize; nl];
    for &(d, a) in sub.wc.iter().chain(sub.bc.iter()) { deg[d] += 1; deg[nd + a] += 1; }
    let mut ord: Vec<usize> = (0..nl).collect(); ord.sort_by(|x, y| deg[*y].cmp(&deg[*x]));
    fn count(sub: &Sub, lab: &Vec<i8>, nd: usize) -> (i64, i64) {
        let mut w = 0; let mut b = 0;
        for &(d, a) in &sub.wc { if lab[d] != 0 && lab[nd + a] != 0 { w += 1; } }
        for &(d, a) in &sub.bc { if lab[d] != 1 && lab[nd + a] != 1 { b += 1; } }
        (w, b)
    }
    fn rec(sub: &Sub, lab: &mut Vec<i8>, ord: &Vec<usize>, k: usize, t: i64, nd: usize) -> bool {
        let (w, b) = count(sub, lab, nd);
        if w < t || b < t { return false; }
        if k == ord.len() { return true; }
        for v in [1i8, 0i8] { lab[ord[k]] = v; if rec(sub, lab, ord, k + 1, t, nd) { return true; } }
        lab[ord[k]] = -1; false
    }
    rec(sub, &mut lab, &ord, 0, t, nd)
}

fn bits(x: u32, n: usize) -> String { (0..n).map(|i| if x >> i & 1 == 1 { '1' } else { '0' }).collect() }

fn canonical(r: u32, c: u32, n: usize) -> bool {
    let code = |a: u32, b: u32| -> u64 { ((a as u64) << n) | b as u64 };
    let me = code(r, c); let full = (1u32 << n) - 1;
    let rr = rev(r, n); let rc = rev(c, n);
    for &(x, y) in &[(r, c), (rr, c), (r, rc), (rr, rc)] {
        for &(u, v) in &[(x, y), (y, x)] {
            if code(u, v) < me { return false; }
            if code(!u & full, !v & full) < me { return false; }
        }
    }
    true
}

fn fail(msg: &str) -> ! { eprintln!("pqv: {}", msg); std::process::exit(2) }

fn num<T: std::str::FromStr>(args: &[String], i: usize, what: &str) -> T {
    match args.get(i).map(|s| s.parse::<T>()) { Some(Ok(v)) => v, _ => fail(&format!("missing or invalid {}", what)) }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 { fail("usage: pqv n T [threads] [options]"); }
    let n: usize = num(&args, 1, "n"); let t: i64 = num(&args, 2, "T");
    if !(1..=30).contains(&n) { fail("n must be in 1..=30"); }
    if t < 0 { fail("T must be >= 0"); }
    let threads: usize = if args.len() > 3 && !args[3].starts_with("--") { num(&args, 3, "threads") } else { 1 };
    if threads == 0 || threads > 1024 { fail("threads must be in 1..=1024"); }
    let known = ["--nosym", "--nobound", "--part", "--sample", "--minprod", "--selftest"];
    let mut i = if args.len() > 3 && !args[3].starts_with("--") { 4 } else { 3 };
    while i < args.len() {
        match args[i].as_str() {
            "--nosym" | "--nobound" => i += 1,
            "--part" | "--sample" => i += 3,
            "--minprod" | "--selftest" => i += 2,
            a => fail(&format!("unknown option {} (known: {:?})", a, known)),
        }
    }
    if i > args.len() { fail("incomplete option"); }
    let nosym = args.iter().any(|a| a == "--nosym");
    let nobound = args.iter().any(|a| a == "--nobound");
    let mut sample: Option<(u64, u64)> = None;
    // --part j m : only the rows-masks r with r % m == j (a slice of the full search; the slices j = 0..m-1 partition it)
    let part: Option<(u32, u32)> = match args.iter().position(|a| a == "--part") { Some(i) => Some((num(&args, i + 1, "slice index"), num(&args, i + 2, "slice modulus"))), None => None };
    if let Some((pj, pm)) = part {
        if pm == 0 || pj >= pm { fail("--part j m needs m >= 1 and 0 <= j < m"); }
        if (pj as u64) >= (1u64 << n) { fail("--part: slice j contains no row mask r < 2^n (empty slice)"); }
    }
    let minprod: i64 = match args.iter().position(|a| a == "--minprod") { Some(i) => num(&args, i + 1, "minprod"), None => 0 };
    if let Some(i) = args.iter().position(|a| a == "--sample") { sample = Some((num(&args, i + 1, "sample size"), num(&args, i + 2, "sample seed"))); }
    let inst = Arc::new(Inst { n, t });
    if let Some(i) = args.iter().position(|a| a == "--selftest") {
        // compare upper() with brute force over all diagonal labellings, random (R,C), random p
        let k: u64 = num(&args, i + 1, "selftest trials"); let mut s: u64 = 99991; let mut bad = 0;
        if n > 7 { fail("--selftest enumerates all diagonal labellings: n must be <= 7"); }
        let full = (1u32 << n) - 1; let nd = 2 * n - 1;
        for _ in 0..k {
            s ^= s << 13; s ^= s >> 7; s ^= s << 17;
            let r = (s as u32) & full; let c = ((s >> 20) as u32) & full; let p = ((s >> 40) % (QP as u64 + 1)) as i64;
            let sub = build_sub(&inst, r, c);
            let (u, w, b) = upper(&sub, p);
            let mut best = i64::MIN;
            for m in 0u64..(1u64 << (2 * nd)) {
                let x = |l: usize| (m >> l) & 1 == 1;
                let ww = sub.wc.iter().filter(|&&(d, a)| x(d) && x(nd + a)).count() as i64;
                let bb = sub.bc.iter().filter(|&&(d, a)| !x(d) && !x(nd + a)).count() as i64;
                best = best.max(p * ww + (QP - p) * bb);
            }
            if best != u || p * w + (QP - p) * b != u { bad += 1; println!("MISMATCH r={} c={} p={} u={} brute={} w={} b={}", r, c, p, u, best, w, b); }
        }
        println!("pqv selftest n={} trials={} mismatches={}", n, k, bad); return;
    }
    let leaves = Arc::new(AtomicU64::new(0)); let pruned = Arc::new(AtomicU64::new(0));
    let searched = Arc::new(AtomicU64::new(0)); let found = Arc::new(AtomicBool::new(false));
    let full = (1u32 << n) - 1;
    if let Some((k, seed)) = sample {
        // test k random canonical (R,C) with count condition: report pruned / searched / found
        let mut s = seed | 1; let mut done = 0;
        while done < k {
            s ^= s << 13; s ^= s >> 7; s ^= s << 17;
            let r = (s as u32) & full; let c = ((s >> 32) as u32) & full;
            let (pr, pc) = (r.count_ones() as i64, c.count_ones() as i64);
            if pr * pc < t || (n as i64 - pr) * (n as i64 - pc) < t || !canonical(r, c, n) { continue; }
            if pr * pc < minprod || (n as i64 - pr) * (n as i64 - pc) < minprod { continue; }
            done += 1;
            let sub = build_sub(&inst, r, c);
            let lp = if nobound { None } else { lagrange_prune(&sub, t) };
            let res = match lp { Some(x) => if x { "FOUND" } else { "PRUNED" }, None => if plain_dfs(&sub, t) { "FOUND" } else { "SEARCHED-UNSAT" } };
            println!("{} {} {}", bits(r, n), bits(c, n), res);
        }
        return;
    }
    let mut hs = vec![];
    for th in 0..threads {
        let (inst, leaves, pruned, searched, found) = (inst.clone(), leaves.clone(), pruned.clone(), searched.clone(), found.clone());
        hs.push(thread::spawn(move || {
            let n = inst.n; let t = inst.t;
            let mut r = th as u32;
            while r <= full {
                if let Some((pj, pm)) = part { if r % pm != pj { r += threads as u32; continue; } }
                let pr = r.count_ones() as i64;
                for c in 0..=full {
                    let pc = c.count_ones() as i64;
                    if pr * pc < t || (n as i64 - pr) * (n as i64 - pc) < t { continue; }
                    if !nosym && !canonical(r, c, n) { continue; }
                    leaves.fetch_add(1, Ordering::Relaxed);
                    let sub = build_sub(&inst, r, c);
                    let lp = if nobound { None } else { lagrange_prune(&sub, t) };
                    match lp {
                        Some(false) => { pruned.fetch_add(1, Ordering::Relaxed); }
                        Some(true) => { found.store(true, Ordering::Relaxed); println!("FOUND (bound completion) R={} C={}", bits(r, n), bits(c, n)); }
                        None => { searched.fetch_add(1, Ordering::Relaxed);
                            if plain_dfs(&sub, t) { found.store(true, Ordering::Relaxed); println!("FOUND (dfs) R={} C={}", bits(r, n), bits(c, n)); } }
                    }
                    if found.load(Ordering::Relaxed) { return; }
                }
                r += threads as u32;
            }
        }));
    }
    for h in hs { h.join().unwrap(); }
    if let Some((pj, pm)) = part { println!("part {} of {} (rows masks r with r % {} == {})", pj, pm, pm, pj); }
    println!("pqv n={} T={} {} leaves={} pruned={} searched={}", n, t,
             if found.load(Ordering::Relaxed) { "FEASIBLE" } else { "INFEASIBLE" },
             leaves.load(Ordering::Relaxed), pruned.load(Ordering::Relaxed), searched.load(Ordering::Relaxed));
}
