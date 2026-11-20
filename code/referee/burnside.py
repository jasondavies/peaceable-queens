#!/usr/bin/env python3
"""Referee check 3: the number of G-orbits of row/column labellings (R, C) that pass the count test
|R||C| >= T and (n-|R|)(n-|C|) >= T, by Burnside's lemma (G = D4 x colour swap, order 16).

Both search programs claim to visit exactly one (R, C) per orbit; their leaf counts must equal this
number.  pq2 keeps x iff its row/column sequence is lexicographically <= each of its 16 images (checked
at the end of the last group too), so it keeps at most one labelling per orbit; equality with the
Burnside count then shows that it keeps exactly one, i.e. that the symmetry breaking is complete.

Action of D4 on (R, C), with rev = reversal of an n-bit mask (i -> n-1-i):
  id (R,C); flip rows (rev R, C); flip cols (R, rev C); rot180 (rev R, rev C);
  transpose (C, R); antitranspose (rev C, rev R); rot90 (C, rev R); rot270 (rev C, R);
and the colour swap complements both masks.  These 8 maps are derived from the cell maps in
fixed_pairs_check() below and checked against them for small n.
usage: burnside.py n T [n T ...]"""
import sys, json
from math import comb

def rev(x, n):
    return int(format(x, '0%db' % n)[::-1], 2)

def elements():
    # (swap, revFirst, revSecond): image = (f(A), g(B)) where (A,B) = (R,C) if not swap else (C,R)
    return [(0, 0, 0), (0, 1, 0), (0, 0, 1), (0, 1, 1), (1, 0, 0), (1, 1, 1), (1, 0, 1), (1, 1, 0)]

def image(e, comp, R, C, n):
    sw, r1, r2 = e
    A, B = (C, R) if sw else (R, C)
    A = rev(A, n) if r1 else A; B = rev(B, n) if r2 else B
    if comp: full = (1 << n) - 1; A ^= full; B ^= full
    return A, B

def fixed_pairs_check(n):
    """Brute-force check (small n) that the 8 maps above are exactly the action of D4 on cells:
    a cell (i,j) is in R x C iff its image is in image(R) x image(C)."""
    m = n - 1
    cellmaps = {(0, 0, 0): lambda i, j: (i, j), (0, 1, 0): lambda i, j: (m - i, j), (0, 0, 1): lambda i, j: (i, m - j),
                (0, 1, 1): lambda i, j: (m - i, m - j), (1, 0, 0): lambda i, j: (j, i), (1, 1, 1): lambda i, j: (m - j, m - i),
                (1, 0, 1): lambda i, j: (j, m - i), (1, 1, 0): lambda i, j: (m - j, i)}
    for e, f in cellmaps.items():
        for R in range(1 << n):
            for C in range(0, 1 << n, 3):
                A, B = image(e, 0, R, C, n)
                for i in range(n):
                    for j in range(n):
                        k, l = f(i, j)
                        if ((R >> i & 1) and (C >> j & 1)) != bool((A >> k & 1) and (B >> l & 1)):
                            return False
    return True

def ok_sizes(a, b, n, T):
    return a * b >= T and (n - a) * (n - b) >= T

def orbits(n, T):
    full = (1 << n) - 1
    # popcount histograms of masks fixed by id / rev / rev+complement / complement
    fix = {'id': [0] * (n + 1), 'rev': [0] * (n + 1), 'revc': [0] * (n + 1), 'c': [0] * (n + 1)}
    revs = [rev(x, n) for x in range(1 << n)]
    for x in range(1 << n):
        k = x.bit_count(); fix['id'][k] += 1
        if revs[x] == x: fix['rev'][k] += 1
        if revs[x] ^ full == x: fix['revc'][k] += 1
        # complement never fixes a mask (n >= 1)
    total = 0
    for e in elements():
        sw, r1, r2 = e
        for comp in (0, 1):
            cnt = 0
            if not sw:
                # R fixed by (rev^r1, comp), C fixed by (rev^r2, comp)
                key = lambda r: ('rev' if r else 'id') if not comp else ('revc' if r else 'c')
                hr, hc = fix[key(r1)], fix[key(r2)]
                cnt = sum(hr[a] * hc[b] for a in range(n + 1) for b in range(n + 1) if ok_sizes(a, b, n, T))
            else:
                # image = (f(C), g(R)) [with complement]; fixed iff R = f(C), C = g(R)  => C determined by R
                for R in range(1 << n):
                    C = revs[R] if r2 else R
                    if comp: C ^= full
                    A = revs[C] if r1 else C
                    if comp: A ^= full
                    if A == R and ok_sizes(R.bit_count(), C.bit_count(), n, T): cnt += 1
            total += cnt
    assert total % 16 == 0
    return total // 16

def orbits_brute(n, T):
    seen = set(); k = 0
    for R in range(1 << n):
        for C in range(1 << n):
            if not ok_sizes(R.bit_count(), C.bit_count(), n, T): continue
            o = min(image(e, cp, R, C, n) for e in elements() for cp in (0, 1))
            if o not in seen: seen.add(o); k += 1
    return k

if __name__ == '__main__':
    out = {'action_check_n<=6': all(fixed_pairs_check(n) for n in range(1, 7)),
           'brute_vs_burnside_n<=8': all(orbits_brute(n, T) == orbits(n, T) for n in range(1, 9) for T in (1, n * n // 7 + 1, n * n // 6))}
    a = sys.argv[1:]
    for i in range(0, len(a), 2):
        n, T = int(a[i]), int(a[i + 1])
        out['n%d_T%d' % (n, T)] = orbits(n, T)
    print(json.dumps(out, indent=1))
