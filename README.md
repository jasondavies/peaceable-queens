# Peaceable queens on boards of size 16 to 20

This repository holds a paper and its verification material. The paper concerns OEIS
[A250000](https://oeis.org/A250000): a(n) is the largest m such that m white and m black queens can be placed on an
n × n board with no queen attacking a queen of the other colour. The values a(1), …, a(15) were known.

## Results

- **a(16) = 37, a(17) = 42, a(18) = 47, a(19) = 52, a(20) = 58.** Each equals ⌊7n²/48⌋, so the constructions Ainley
  gave in 1977 are optimal on these boards. The lower bounds are known boards (Ainley; the OEIS file of best known
  solutions by D. Kamenetsky), each checked directly for attacks. The upper bounds come from an exhaustive,
  computer-assisted search.
- **Method.** Label every row, column, diagonal and antidiagonal white or black. Then a(n) is the maximum over
  labellings of min(#white cells, #black cells) (Lemma 2.1). For fixed rows and columns this is bounded by Lagrangian
  duality, and each Lagrangian subproblem is a minimum cut on the 4n − 2 diagonals. Symmetry breaking uses
  D4 × colour swap. For every n ≤ 20 the bound at the root prunes every (rows, columns) orbit, so no diagonal
  search is ever needed. The n = 20 search meets 5.7 × 10¹⁰ orbits.
- **Side results, each from a single implementation.** They reproduce all the known terms of their sequences:
  - A260680 (inequivalent optimal configurations): 696, 4, 2155, 579, 2298, 26 for n = 11, …, 16;
  - A279405 (torus): the values at n = 20 and n = 22 are 51 and 64.

## What was checked, for each n

| n | main search (C, `pq2`) | second implementation (Rust, `pqv`) | other checks |
|---|---|---|---|
| ≤ 15 | complete; reproduces OEIS | complete; same verdicts and orbit counts | search from the definition (n ≤ 8), direct CP-SAT (n ≤ 7), SAT + drat-trim (n ≤ 8), no-symmetry and no-bound runs (n ≤ 11) |
| 16 | complete | complete; identical orbit count | Burnside orbit count; 400 SAT + DRAT leaves; exact LP certificates on samples; cube replays |
| 17 | complete | complete; identical orbit count | Burnside; LP certificates; cube replays |
| 18 | complete | complete (199 slices, all pruned; same orbit count) | Burnside; LP certificates; cube replays |
| 19 | complete | not run | Burnside; LP certificates; cloud cubes rerun locally |
| 20 | complete | not run | Burnside; LP certificates; cloud cubes rerun locally |

The paper's Section 6 and Table 2 give the exact numbers, and `claims.json` holds them. For n = 19 and 20 most cubes
were run on Modal cloud containers with the dispatcher in `code/modal/` (the same `code/pq2.c`, compiled there with
gcc 12.2). Every returned line was checked before it was logged, and `data/runs/n19_T53/provenance.txt` and
`data/runs/n20_T59/provenance.txt` say which cubes ran where.

## Read

- [Manuscript](paper/peaceable-queens.pdf) and its [LaTeX source](paper/peaceable-queens.tex).

## Reproduce

You need:
- Python 3.12 with the pinned packages in `requirements.txt` (PySAT, OR-Tools, SciPy, NumPy);
- gcc, cargo/rustc (tested with 1.75; the verifier has no dependencies), `curl`, `sha256sum`, `latexmk`/`pdflatex`;
- drat-trim at commit `2e3b2dc0`. It is not included here: `scripts/get_tools.sh` downloads the GitHub tarball,
  checks its SHA-256 (`a75e5a20…b227b58c`) and builds it in `tools/` (git-ignored). Set `DRATTRIM_TARBALL` to use a
  local copy.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/verify.py                       # default: about 10 minutes, 2 processes
.venv/bin/python scripts/verify.py --only build,logs     # any subset of the steps below
.venv/bin/python scripts/verify.py --full 16 --jobs 8    # rerun every n = 16 cube and compare (~25 CPU min)
.venv/bin/python scripts/verify.py --full-pqv 16         # the second implementation on all of n = 16 (~2 CPU h)
.venv/bin/python scripts/verify.py --tamper              # perturbed copies of claims/logs must fail
```

`--full N` works for N = 16, …, 20 (about 0.4, 1.8, 9.7, 41 and 160 local CPU hours). `scripts/verify.py` writes a JSON file and a
log for every step to `verification/`, and a summary with input and PDF hashes to `verification/summary.json`.
Each gate compares a recomputed value, or a value parsed from the recorded logs in `data/`, exactly with
[claims.json](claims.json). The SHA-256 hashes of those logs are checked against `data/MANIFEST.sha256`. The paper
takes its numbers from `claims.json` through the generated macros in `paper/claims.tex`
(`scripts/make_claims_tex.py`). The script exits nonzero if any gate fails, or if the LaTeX log has a warning or a bad
box.

The default run covers these steps.
- **build:** compiles `code/pq2.c`, `code/pqenum.c` and `code/pqt.c` with `gcc -O3 -march=native`, builds the Rust
  verifier and drat-trim, and checks the sources against `data/provenance/` (the exact sources used for the
  recorded runs; the current sources differ from them only by input validation and, for `pqt.c`, unsigned masks).
- **unit:** the min-cut evaluation of both programs against brute force over all completions (18,000 + 1,220
  random instances).
- **robust:** regression tests for the defects found by review: the drivers refuse a directory made for other
  parameters (including the reviewer's repro, `run_cubes.py 8 10` then `8 9` in the same directory) or with
  corrupted lines; every solver rejects out-of-range arguments; UBSan/ASan runs of the C programs are clean
  (and catch the old defects in the pre-fix sources); the Rust verifier runs with overflow checks; a failed or
  truncated leaf sampler is rejected; misspelled `--only` stages are rejected; drat-trim builds under GCC-14 rules.
- **small:** both programs at T = a(n) and a(n) + 1 for n ≤ 13, with symmetry breaking off (pq2) and the bound off
  (pqv) for n ≤ 10. Witness boards are checked for attacks, and the orbit counts are compared with Burnside's lemma.
- **referee:** the independent checks in `code/referee/`. The definition-level search runs for n ≤ 7, the 3^(n²)
  blocking-rule enumeration for n ≤ 4, and the direct CP-SAT model for n ≤ 6. Burnside orbit counts for
  n = 16, …, 20 must equal the recorded leaf totals. Exact LP certificates are rerun on a prefix of each recorded
  sample.
- **sat:** placement and line encodings with drat-trim for n ≤ 7, and ten random n = 16 leaves.
- **certificates:** the Ainley board for n = 16 and all boards of Kamenetsky's file, checked directly for attacks.
- **logs:** manifest hashes. For each n = 16, …, 20, the cube list is regenerated and compared, and the cube log is
  checked: one line per cube, all UNSAT, and totals equal to the claims. The complete pqv runs and the pqv slices are
  checked too (for n = 18 all 199 slices, with the Burnside total).
- **replay:** random cubes of each n are rerun, and their log lines must be identical apart from the time.
- **side:** A260680 for n ≤ 9 and the torus for n ≤ 12 are rerun; the A260680 enumerations are checked like the main
  runs (manifest, every cube line, totals) and recounted from the recorded optimal boards; the torus runs with the
  corrected program are checked against the original counters.
- **paper:** the claims macros, a clean reproducible LaTeX build in `build/paper/`, identical to the committed PDF.

## What is proved, and what is computed

**Proved in the paper:** the line-labelling reformulation (Lemma 2.1); the count bound; the Lagrangian bound and its
min-cut evaluation (Lemmas 3.1, 3.2). Corollary 3.3 shows that pruning is sound whenever *some* feasible flow
certifies it, so neither max-flow optimality nor the choice of λ affects correctness. The symmetry reduction is
Lemma 4.1.

**By exact computation:** the upper bounds a(n) ≤ ⌊7n²/48⌋ for n = 16, …, 20; the side results.

**Main residual risks:**
- the correctness of `code/pq2.c`. For n ≤ 17 a separately written program (different canonical form, network, max-flow
  algorithm and language) repeats the whole search with identical orbit counts. For n = 18 it repeats part of the
  search, and for n = 19 and 20 it was not run;
- the two programs share the method (Lemmas 2.1–4.1). The SAT/DRAT and exact LP checks avoid Lemmas 3.1–4.1, and the
  definition-level checks avoid all of them, but these checks cover only samples or small n;
- the side results (A260680 n = 11…16, torus n = 20 and 22) have a single implementation.

No independent human review has been recorded.

## Layout

- `paper/`: the manuscript and the generated `claims.tex`.
- `code/`:
  - `pq2.c`: the main search;
  - `verifier/`: the second implementation (Rust, `pqv`);
  - `pqenum.c`, `count_configs.py`: A260680;
  - `pqt.c`, `check_torus.py`: the torus;
  - `run_cubes.py`, `run_pqv_parts.py`, `run_enum.py`, `run_torus.py`: resumable drivers;
  - `modal/`: the ephemeral Modal dispatcher used for most n = 19 and 20 cubes (`modal_pq_v1_used_for_n19.py` is the
    version used for n = 19);
  - `sat_check.py`: SAT encodings and drat-trim;
  - `check_placement.py`: the direct attack check;
  - `referee/`: the referee's independent checks (`brute.py`, `cpsat_direct.py`, `burnside.py`, `lp_leaves.py`).
- `scripts/`: `verify.py`, `make_claims_tex.py`, `get_tools.sh`.
- `data/`:
  - `runs/nN_TT/`: the cube list, the sorted per-cube log and the summary of each main run;
  - `pqv/`: the second implementation's runs and slices, and `part_option.diff`. The diff is the only change to the
    verifier since the complete n = 16, 17 runs: it adds `--part`;
  - `validation/`, `sat_samples/`, `referee/`, `side/`: the recorded outputs;
  - `certificates/`: the lower-bound boards;
  - `MANIFEST.sha256`.
- `verification/` (git-ignored): the outputs of the last verification run. A run of `scripts/verify.py` does not
  modify any tracked file: the paper is rebuilt in `build/paper/` and compared byte for byte with the committed PDF.

## Authorship and AI disclosure

Author: Jason Davies. AI systems produced the mathematics, the code and the manuscript: Claude Opus 5.5 (Anthropic),
via Claude Code, under the author's direction. The author started some of the cloud runs with commands prepared by
the AI system. The author has not read the manuscript or checked the arguments; see
the declaration in the paper.

## License

Apache License 2.0; see [LICENSE](LICENSE). The board file `data/certificates/kamenetsky_best_known_12-30.txt` is
D. Kamenetsky's file from the OEIS (oeis.org/A250000/a250000_3.txt), included unchanged under the OEIS licence
(CC BY-SA 4.0). drat-trim, which is downloaded separately, has its own licence (MIT).
