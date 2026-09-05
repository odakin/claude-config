"""GPT / POVM の間主観性・sharpness・極値性を定義から検査する library (有限 outcome の certificate/LP、連続 Husimi POVM の有限 anchor + foil、--selftest; 無限次元の証明境界は physics-verification-cycle.md#continuous-rank-one-povm-extremality)

Layer-1 hoist (2026-09-05) of a helper first written for a verify-to-learn reading of
Umekawa–Ono–Arai, arXiv:2603.01575 (intersubjectivity in generalized probabilistic theories; the
definitions below follow that paper's Def. 1-3) and Arai–Hayashi, arXiv:2411.01873.  The per-paper
check scripts live in a private verification repo (personal layer) and import this module through a
thin shim; this file is the SoT for the mathematics and the numerical recipe.

Everything here is built from the *definitions* — never from the papers' theorems — so that a
check script using it is an independent derivation (conventions/scientific-computing.md
#verify-independent-derivation).

Definitions (finite outcome set X; "1" = unit effect):
  measurement A = (a_x)_x : effects, sum_x a_x = 1
  JM(A,B)  = joint measurements (c_{x,y}) with marginals A and B
  alpha_IS(A) := min_{B in JM(A,A)} min_state sum_x b_{xx}(state)   (degree of intersubjectivity)
      A is alpha-intersubjective  <=>  alpha <= alpha_IS(A);   intersubjective (IS) <=> alpha_IS = 1
      <=> every joint of A with itself is the canonical one (off-diagonal blocks vanish)
  common lower bound of (a,b): 0 <= c <= a, c <= b.  A is "sharp" iff no pair x != x' has a
      nonzero common lower bound; alpha_sharp(A) = 1 - max_{x != x'} max ||c||.
      IS <=> sharp (an off-diagonal block of a joint is a common lower bound, and a common lower
      bound c builds the joint b_xx = a_x - c (x in {x1,x2}), b_{x1x2} = b_{x2x1} = c).
      For 2 outcomes exactly alpha_IS = 1 - 2 max||c||.
  coarse-graining = merging outcomes along a set partition; completely intersubjective (CIS) <=>
      every coarse-graining is IS.  Quantum: CIS <=> PVM; IS <=> pairwise supp(a_x) ∩ supp(a_x') = {0}
      (finite dimension only — in infinite dimension the criterion is ran(a^{1/2}) ∩ ran(b^{1/2})).
  extremal: A is an extreme point of the measurement space  <=>  no delta != 0 with A ± delta
      measurements; quantum: <=> {delta_x = P_x delta_x P_x Hermitian, sum delta_x = 0} = {0}
      (lemma: a ± eps delta >= 0 for some eps > 0  <=>  supp delta ⊆ supp a).

Continuous-outcome addendum (standard countably additive POVMs on the Borel space C):
  The single-mode Husimi observable is A(U)=∫_U |z><z| d^2z/pi.  Its minimal Naimark
  dilation is (V psi)(z)=<z|psi> in L^2(C,d^2z/pi), P(U)=M_{1_U}; minimality follows
  already from the vacuum wavefunction, which is nowhere zero.  The extremality criterion
  therefore asks whether V* M_h V=0 for bounded measurable h forces h=0 a.e.  Matrix
  elements in the Fock basis say that every mixed moment of the finite signed measure
  h(z) exp(-|z|^2)d^2z/pi vanishes.  Gaussian exponential integrability plus uniqueness
  of the Fourier--Stieltjes transform gives h=0 a.e.; hence the Husimi POVM is extremal.
  For a self-joint B, the commuting dilation effects for its second marginal have the same
  compression as P(U); extremality makes them equal to P(U).  Thus B is uniquely the
  diagonal pushforward B(U1 x U2)=A(U1 ∩ U2), first on rectangles and then on all Borel
  sets by scalar pi-lambda uniqueness and polarization.  Statewise, weak, strong, and
  ultraweak countable-additivity formulations give the same result.  A merely finitely
  additive extension is outside this conclusion.

  `coherent_resolution_matrix` and `coherent_bounded_moment_map` below are deliberately
  finite machine anchors for normalization and a bounded test family.  No Fock truncation,
  quadrature rank, or finite moment family proves the infinite-dimensional extremality
  statement; that load-bearing step is the analytic Gaussian/Fourier argument above.

  Second, independent route (blind second-eye pass, same day) that needs neither Radon–Nikodym
  nor Fourier uniqueness: a self-joint B is canonical iff B vanishes off the diagonal, and for
  Borel U1, U2 at positive distance every block X = B(E), E ⊆ U1×U2, obeys the FINITE-DIMENSIONAL
  inequality  Tr X (1 - |<u|v>|) <= Tr(Q_u X) + Tr(Q_v Y)  for any common lower bound X of
  (X', Y) = (A(V), A(W)) and unit vectors u, v (Q_u = 1 - |u><u|).  With u, v the coherent states at
  the centres of square cells of side s, the right-hand side is O(s^4) per cell while Tr A(V) is
  O(s^2), so partitioning U1, U2 into cells and summing gives Tr B(E) <= O(s^2) -> 0.  The
  inequality is itself the value of the explicit dual point (Y, Z) = t (Q_u, Q_v), t = 1/(1-|<u|v>|)
  of the common-lower-bound SDP (Y + Z >= 1 because ||p_u + p_v|| = 1 + |<u|v>|), so it is the
  rigorous upper bound to quote when the generic dual solver is loose (~ Tr X' + Tr Y).  Helpers:
  `coherent_cell_matrix` (truncated Husimi square cell, Gauss–Legendre), `nearly_rank_one_clb_bound`
  (the certificate), `symmetrised_coherent_cell` (foil model with a.e. rank-2 density, whose cells V
  and -V keep a common lower bound A(V)/2 — the mechanism visibly fails there).  Same caveat: these
  are finite anchors for the *mechanism* of the continuous proof, not a proof of it.

Infinite-dimensional addendum (second-eye campaign on the finite-outcome criterion, 2026-09):
  * Exact criterion (dimension-free, proof needs only Cauchy–Schwarz and the easy half of Douglas'
    lemma):  a nonzero c with 0 <= c <= a, c <= b exists  <=>  ran(a^{1/2}) ∩ ran(b^{1/2}) != {0}.
    In finite dimension ran = supp (closed), so this is the support criterion; in infinite dimension
    the two differ whenever a range is not closed.  Explicit pair on L^2(S^1) with p_supp(a) ∧ p_supp(b) != 0
    but no common lower bound:  a = sum_n e^{-2|n|}|e_n><e_n| (ran a^{1/2} = real-analytic class R),
    b = P_I = multiplication by 1_I for a proper arc I (ran = L^2(I));  R ∩ L^2(I) = {0} by the identity
    theorem.  The step "e_{a,eps} ∧ e_{b,eps} -> p_a ∧ p_b strongly" is FALSE for this pair: e_{a,eps} is the
    projector onto trig polynomials of degree <= N(eps), and e_N ∧ P_I = 0 for every N (`fourier_arc_gram`
    positive definite) while 1 ∧ P_I = P_I.  The projection lattice meet does not commute with increasing
    strong limits.
  * The distinction is visible at the POVM level with 3 outcomes:  a_1 = a/2, d = 1 - a_1 (invertible),
    a_2 = d^{1/2} P_I d^{1/2}, a_3 = d^{1/2} (1 - P_I) d^{1/2}.  Pairwise ran(a_x^{1/2}) intersect trivially
    (so the POVM is IS by the criterion above) although the closed supports of a_1 (= H) and a_2 overlap.
    With 2 outcomes this cannot happen (a and 1-a commute; a^{1/2}(1-a)^{1/2} != 0 unless a is a
    projection).  `analytic_class_arc_povm` gives Fourier truncations of this family; truncations cannot
    show the infinite-dimensional statement (finite dimension always has the support criterion) — they
    only anchor that the construction behaves as the proof says.
  * Solver-free bracket for the largest common lower bound:  a:b <= c-max <= 2 (a:b) in the sense
    ||a:b|| <= max ||c|| <= 2||a:b||  (`common_lower_bound_sandwich`).  Proof: a:b is itself a common lower
    bound; and for any common lower bound c, <xi,c xi> = <x+y,c(x+y)> <= 2(<x,cx>+<y,cy>) <= 2(<x,ax>+<y,by>),
    inf over x+y = xi gives c <= 2 a:b.
  * Certifying "e_N ∧ P_I = 0" numerically: lambda_min of the arc Gram matrix decays super-exponentially
    (prolate-type, ~1e-19 at N = 8, ~1e-38 at N = 16), far below double precision — use mpmath at
    ~100 digits, never a 1e-12 tolerance on a float eigenvalue.
  * Compressing a projection to a truncation gives a NON-projection whose complement shares a large common
    lower bound with it (P_N(1-P_N) != 0); truncate the *decomposition* instead (spectral cut of the
    compression at 1/2), otherwise the truncated pair (a_2, a_3) shows a spurious O(1) common lower bound.
  * Husimi coarse-graining onto cells U_k: ran(A(U)^{1/2}) = V*(L^2(U)) and |psi><psi|/||f||^2 <= A(U) for
    psi = V*f, f in L^2(U).  For two cells that alone fill a disc D up to null sets (0 < |D ∩ U_k| < |D|),
    h = e^{|z|^2/2} dbar(phi) with phi in C_c^inf(D) has V*h = 0 (Stokes against entire functions), so
    psi = V*(1_{U_k} h) = -V*(1_{U_l} h) is a common element of both ranges, nonzero for some phi because an
    indicator cannot be antiholomorphic on D (dbar hypoellipticity).  Fock components need no Gaussian:
    psi_n = (1/pi) ∫_{U_k} dbar(phi) z^n/sqrt(n!) d^2z  (`husimi_dbar_witness`, half-plane cells; the half-plane
    Husimi matrix elements are closed form, `husimi_halfplane_matrix`).  Distance between cells is NOT the
    criterion: a bounded cell always has a common lower bound with any cell containing an annulus around it
    (subharmonicity of |F|^2 + Poisson bound gives A(U_k) <= C A(U_j)).

Two model families:
  * quantum (finite dim d): Hermitian effects 0 <= a <= I.  Small convex programs are solved with
    scipy SLSQP on eigenvalue constraints and, where load-bearing, sandwiched by an explicit dual
    certificate (weak duality), so the interval [primal, dual] is rigorous up to float tolerance
    whatever the local solver did.  Qualitative verdicts (IS / CIS / extremal) never trust the
    solver: non-IS is shown by an explicit witness joint, IS by the support-projector dual
    certificate Y = t P_ker(a), Z = t P_ker(b) (see `max_common_lower_bound`, `support_projector`).
  * polytope GPTs (state space = convex hull of a vertex list, effects = affine functionals with
    values in [0,1] on the vertices; coordinates include a normalisation coordinate): every quantity
    is an exact LP (`Polytope.is_degree`, `.max_common_lower_bound_norm`, `.is_extremal`,
    `.is_indecomposable`).  Vertex enumeration for small H-polytopes: `polytope_vertices_from_halfspaces`.

Numerical gotchas learned on this code (conventions/scientific-computing.md#small-sdp-without-solver):
  * SLSQP with the smooth 2x2 PSD form (diag >= 0, det >= 0) STALLS on convex instances (det's
    linearisation is poor) — eigenvalue constraints + random restarts work; keep the best feasible
    iterate and fall back to a feasible x0.
  * equality constraints (joint-measurement marginals) make SLSQP's QP rank-deficient — eliminate
    them by a null-space parametrisation of the affine space (`_joint_nullspace`).
  * start strictly inside the cone: c = 0 and the canonical joint are degenerate points of the PSD
    constraints (zero gradient) — use the parallel sum a:b = (a^-1 + b^-1)^-1 <= a, b as interior
    start (`parallel_sum`, `interior_joint`).
  * alpha_IS is a MIN of a concave function (lambda_min) over a convex set: it is NOT a convex
    program.  Decompose as min over pure states v of a convex inner program, scan v (Bloch grid +
    Nelder–Mead refine for qubits) — the outer scan is evidence, not a certificate; say so.
"""
from __future__ import annotations

import itertools
import math
import numpy as np
from numpy.polynomial.hermite import hermgauss
from numpy.polynomial.legendre import leggauss
from scipy.optimize import minimize, linprog

TOL = 1e-7
BOX = 1e3   # box bound for LP coefficient variables (see Polytope.is_extremal)


# ----------------------------------------------------------------------------
# Hermitian parametrisation
# ----------------------------------------------------------------------------
def herm_from_vec(v, d):
    """d*d real numbers -> d x d Hermitian matrix (diag, then re/im of upper triangle)."""
    v = np.asarray(v, dtype=float)
    H = np.zeros((d, d), dtype=complex)
    k = 0
    for i in range(d):
        H[i, i] = v[k]
        k += 1
    for i in range(d):
        for j in range(i + 1, d):
            H[i, j] = v[k] + 1j * v[k + 1]
            H[j, i] = v[k] - 1j * v[k + 1]
            k += 2
    return H


def vec_from_herm(H):
    d = H.shape[0]
    out = [H[i, i].real for i in range(d)]
    for i in range(d):
        for j in range(i + 1, d):
            out += [H[i, j].real, H[i, j].imag]
    return np.array(out)


def nherm(d):
    return d * d


def eigmin(H):
    return float(np.linalg.eigvalsh((H + H.conj().T) / 2)[0])


def eigmax(H):
    return float(np.linalg.eigvalsh((H + H.conj().T) / 2)[-1])


def is_psd(H, tol=TOL):
    return eigmin(H) >= -tol


def is_effect(a, tol=TOL):
    d = a.shape[0]
    return is_psd(a, tol) and is_psd(np.eye(d) - a, tol)


def is_measurement(A, tol=TOL):
    d = A[0].shape[0]
    return all(is_psd(a, tol) for a in A) and np.allclose(sum(A), np.eye(d), atol=tol)


# ----------------------------------------------------------------------------
# random objects (seeded by caller)
# ----------------------------------------------------------------------------
def random_unit(d, rng):
    v = rng.normal(size=d) + 1j * rng.normal(size=d)
    return v / np.linalg.norm(v)


def random_povm(d, n, rng, ranks=None):
    """Random n-outcome POVM on C^d built from random Kraus-like operators,
    a_x = S^{-1/2} K_x^dag K_x S^{-1/2},  S = sum_x K_x^dag K_x  (so sum = I exactly)."""
    if ranks is None:
        ranks = [d] * n
    Ks = []
    for r in ranks:
        K = rng.normal(size=(r, d)) + 1j * rng.normal(size=(r, d))
        Ks.append(K)
    S = sum(K.conj().T @ K for K in Ks)
    w, U = np.linalg.eigh(S)
    Sinv = U @ np.diag(w ** -0.5) @ U.conj().T
    A = [Sinv @ K.conj().T @ K @ Sinv for K in Ks]
    A = [(a + a.conj().T) / 2 for a in A]
    return A


def random_pvm(d, rng, sizes):
    """Random PVM with block sizes `sizes` (sum = d), in a Haar-random basis."""
    assert sum(sizes) == d
    G = rng.normal(size=(d, d)) + 1j * rng.normal(size=(d, d))
    Q, _ = np.linalg.qr(G)
    A, k = [], 0
    for s in sizes:
        P = Q[:, k:k + s] @ Q[:, k:k + s].conj().T
        A.append(P)
        k += s
    return A


def coarse_grain(A, blocks):
    """blocks = list of lists of outcome indices (a set partition of range(len(A)))."""
    return [sum(A[i] for i in blk) for blk in blocks]


def set_partitions(n):
    """All set partitions of range(n) (as lists of lists)."""
    def rec(i, blocks):
        if i == n:
            yield [list(b) for b in blocks]
            return
        for b in blocks:
            b.append(i)
            yield from rec(i + 1, blocks)
            b.pop()
        blocks.append([i])
        yield from rec(i + 1, blocks)
        blocks.pop()
    return list(rec(0, []))


def support_projector(a, tol=1e-9):
    w, U = np.linalg.eigh((a + a.conj().T) / 2)
    keep = w > tol
    V = U[:, keep]
    return V @ V.conj().T, V


def supports_intersect_trivially(a, b, tol=1e-9):
    """supp(a) ∩ supp(b) = {0}  <=>  dim(supp a + supp b) = dim supp a + dim supp b."""
    _, Va = support_projector(a, tol)
    _, Vb = support_projector(b, tol)
    if Va.shape[1] == 0 or Vb.shape[1] == 0:
        return True
    M = np.hstack([Va, Vb])
    return np.linalg.matrix_rank(M, tol=1e-8) == Va.shape[1] + Vb.shape[1]


# ----------------------------------------------------------------------------
# generic SLSQP driver for small convex programs with PSD constraints
# ----------------------------------------------------------------------------
def _psd_cons(M):
    """Vector g(M) >= 0  <=>  M >= 0. Smooth closed form for 2x2 (diag + det),
    eigenvalues otherwise."""
    # NOTE: the smooth 2x2 form (diag + det) made SLSQP stall on convex instances
    # (det's linearisation is poor); eigenvalues + random restarts work better.
    return np.linalg.eigvalsh((M + M.conj().T) / 2)


def _solve(obj, x0, psd_blocks, eqs=None, ineqs=None, restarts=2, rng=None, maxiter=150):
    """minimise obj(x) subject to blk(x) >= 0 for blk in psd_blocks,
    eqs(x) == 0 (vector), ineqs(x) >= 0 (vector). Returns best feasible x found
    (x0 itself if it is feasible and nothing better is found).
    Local solver; the caller must certify the value by other means."""
    cons = []
    for blk in psd_blocks:
        cons.append({"type": "ineq", "fun": (lambda x, blk=blk: _psd_cons(blk(x)))})
    if eqs is not None:
        cons.append({"type": "eq", "fun": eqs})
    if ineqs is not None:
        cons.append({"type": "ineq", "fun": ineqs})

    def feasible(x):
        ok = all(eigmin(blk(x)) >= -1e-7 for blk in psd_blocks)
        if eqs is not None:
            ok = ok and np.max(np.abs(eqs(x))) < 1e-7
        if ineqs is not None:
            ok = ok and np.min(ineqs(x)) > -1e-7
        return ok

    x0 = np.asarray(x0, dtype=float)
    best = (obj(x0), x0) if feasible(x0) else None
    rng = rng or np.random.default_rng(0)
    for r in range(restarts):
        start = x0 if r == 0 else x0 + 0.2 * rng.normal(size=len(x0))
        res = minimize(obj, start, constraints=cons, method="SLSQP",
                       options={"maxiter": maxiter, "ftol": 1e-13})
        if feasible(res.x) and (best is None or res.fun < best[0]):
            best = (res.fun, res.x)
    if best is None:
        raise RuntimeError("no feasible point found")
    return best[1]


# ----------------------------------------------------------------------------
# common lower bounds (sharpness), with dual certificate
#   primal:  max Tr c   s.t. c >= 0, a - c >= 0, b - c >= 0
#   dual  :  min Tr(aY + bZ)   s.t. Y >= 0, Z >= 0, Y + Z >= I      (weak duality: primal <= dual)
# ----------------------------------------------------------------------------
def max_common_lower_bound(a, b, rng=None, restarts=6):
    """Returns dict with primal value (Tr c), c, dual value, and the certified interval."""
    d = a.shape[0]
    n = nherm(d)
    I = np.eye(d)

    def C(x):
        return herm_from_vec(x[:n], d)

    x0 = vec_from_herm(0.5 * parallel_sum(a, b))   # interior start (det constraints degenerate at c = 0)
    xp = _solve(lambda x: -np.trace(C(x)).real, x0,
                [C, lambda x: a - C(x), lambda x: b - C(x)], rng=rng, restarts=restarts)
    c = C(xp)
    # clean-up: make c exactly feasible by shrinking slightly if needed
    primal = float(np.trace(c).real)

    def Y(x):
        return herm_from_vec(x[:n], d)

    def Z(x):
        return herm_from_vec(x[n:2 * n], d)

    y0 = np.concatenate([vec_from_herm(I), vec_from_herm(I)])
    xd = _solve(lambda x: np.trace(a @ Y(x) + b @ Z(x)).real, y0,
                [Y, Z, lambda x: Y(x) + Z(x) - I], rng=rng, restarts=restarts)
    # make dual strictly feasible by pushing eigenvalues up by the violation
    Yv, Zv = Y(xd), Z(xd)
    sh = max(0.0, -eigmin(Yv), -eigmin(Zv), -eigmin(Yv + Zv - I) / 2)
    Yv, Zv = Yv + sh * I, Zv + sh * I
    dual = float(np.trace(a @ Yv + b @ Zv).real)
    return {"primal": primal, "c": c, "dual": dual, "Y": Yv, "Z": Zv}


def max_common_lower_bound_norm(a, b, rng=None, restarts=6, directions=None):
    """max ||c||_inf over common lower bounds c of (a,b) = max_v max_c <v|c|v>.
    Outer max over unit vectors v is non-convex; for the qubit we scan the Bloch
    sphere and refine. Returns (value, v, c) — a LOWER bound on the true max
    (the inner problems are convex, the outer is a finite scan + local refine)."""
    d = a.shape[0]
    n = nherm(d)
    rng = rng or np.random.default_rng(1)
    if directions is None:
        directions = [random_unit(d, rng) for _ in range(24)]
        # include eigenvectors of a, b, a-b, a+b as natural candidates
        for M in (a, b, a - b, a + b):
            w, U = np.linalg.eigh(M)
            directions += [U[:, k] for k in range(d)]
    best = (-1.0, None, None)
    for v in directions:
        P = np.outer(v, v.conj())

        def C(x):
            return herm_from_vec(x[:n], d)
        xp = _solve(lambda x: -np.trace(P @ C(x)).real, vec_from_herm(0.5 * parallel_sum(a, b)),
                    [C, lambda x: a - C(x), lambda x: b - C(x)], rng=rng, restarts=2)
        val = np.trace(P @ C(xp)).real
        if val > best[0]:
            best = (float(val), v, C(xp))
    return best


# ----------------------------------------------------------------------------
# degree of intersubjectivity
#   alpha_IS(A) = min_{B in JM(A,A)} lambda_min(sum_x b_xx) = min_{pure v} f(v),
#   f(v) := min_{B in JM(A,A)} <v| sum_x b_xx |v>          (inner problem convex)
#   inner dual: max sum_x Tr((Y_x+Z_x) a_x)  s.t.  Y_x + Z_x' <= delta_xx' |v><v|
#               (weak duality: dual <= f(v)); outer min over v is a scan + local refine
#   (f is concave on the state space, so the min is at a pure state; the scan is
#    not a certificate for the outer min — see report of each check).
# ----------------------------------------------------------------------------
def _joint_nullspace(n, d):
    """Basis (columns) of {delta in R^{n*n*m}: all marginal sums of the Hermitian
    blocks vanish}, i.e. the directions along which JM(A,A) is an affine space."""
    from scipy.linalg import null_space
    m = nherm(d)
    rows = []
    for i in range(n):
        for which in (0, 1):
            for k in range(m):
                row = np.zeros(n * n * m)
                for j in range(n):
                    blk = (i * n + j) if which == 0 else (j * n + i)
                    row[blk * m + k] = 1.0
                rows.append(row)
    return null_space(np.array(rows))


def is_degree_fixed_state(A, v, rng=None, restarts=2):
    """Returns (primal f(v) from an explicit B in JM(A,A), dual lower bound, B)."""
    n = len(A)
    d = A[0].shape[0]
    m = nherm(d)
    P = np.outer(v, v.conj())
    N = _joint_nullspace(n, d)
    B0 = interior_joint(A)
    x0full = np.concatenate([vec_from_herm(B0[i][j]) for i in range(n) for j in range(n)])

    def full(t):
        return x0full + N @ t

    def blocks(t):
        x = full(t)
        return [[herm_from_vec(x[(i * n + j) * m:(i * n + j + 1) * m], d) for j in range(n)] for i in range(n)]

    def obj(t):
        Bm = blocks(t)
        return sum(np.trace(P @ Bm[i][i]).real for i in range(n))

    psd = [(lambda t, i=i, j=j: blocks(t)[i][j]) for i in range(n) for j in range(n)]
    tp = _solve(obj, np.zeros(N.shape[1]), psd, rng=rng, restarts=restarts)
    Bm = blocks(tp)
    primal = float(obj(tp))

    def Ys(x):
        return [herm_from_vec(x[i * m:(i + 1) * m], d) for i in range(n)]

    def Zs(x):
        return [herm_from_vec(x[(n + i) * m:(n + i + 1) * m], d) for i in range(n)]

    dpsd = [(lambda x, i=i, j=j: (P if i == j else 0) - Ys(x)[i] - Zs(x)[j]) for i in range(n) for j in range(n)]

    def dobj(x):
        return -sum(np.trace((Y + Z) @ a).real for Y, Z, a in zip(Ys(x), Zs(x), A))

    y0 = np.zeros(2 * n * m)
    for i in range(2 * n):
        y0[i * m:(i + 1) * m] = vec_from_herm(-0.5 * np.eye(d))
    xd = _solve(dobj, y0, dpsd, rng=rng, restarts=restarts)
    Yv, Zv = Ys(xd), Zs(xd)
    viol = max(0.0, max(eigmax(Yv[i] + Zv[j] - (P if i == j else 0)) for i in range(n) for j in range(n)))
    Yv = [Y - viol / 2 * np.eye(d) for Y in Yv]
    Zv = [Z - viol / 2 * np.eye(d) for Z in Zv]
    dual = float(sum(np.trace((Y + Z) @ a).real for Y, Z, a in zip(Yv, Zv, A)))
    return primal, dual, Bm


def parallel_sum(a, b, delta=1e-9):
    """a:b = (a^-1 + b^-1)^-1 (regularised). Satisfies a:b <= a and a:b <= b."""
    d = a.shape[0]
    ai = np.linalg.inv(a + delta * np.eye(d))
    bi = np.linalg.inv(b + delta * np.eye(d))
    c = np.linalg.inv(ai + bi)
    return (c + c.conj().T) / 2


def interior_joint(A, eps=None):
    """An element of JM(A,A) with all off-diagonal blocks nonzero when common
    lower bounds exist: b_xx' = eps * (a_x : a_x') for x != x', diagonal fixed by
    the marginals. Definition-level construction (a_x : a_x' <= a_x, a_x')."""
    n = len(A)
    d = A[0].shape[0]
    if eps is None:
        eps = 0.5 / max(1, n - 1)
    B = [[None] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                B[i][j] = eps * parallel_sum(A[i], A[j])
    for i in range(n):
        B[i][i] = A[i] - sum(B[i][j] for j in range(n) if j != i)
    # symmetric construction => both marginals hold
    return B


def bloch_grid(N):
    """Fibonacci points on the sphere, returned as qubit state vectors."""
    out = []
    ga = np.pi * (3 - np.sqrt(5))
    for k in range(N):
        z = 1 - 2 * (k + 0.5) / N
        r = np.sqrt(1 - z * z)
        th = ga * k
        nx, ny, nz = r * np.cos(th), r * np.sin(th), z
        # state with Bloch vector (nx,ny,nz)
        ang = np.arccos(np.clip(nz, -1, 1))
        phi = np.arctan2(ny, nx)
        out.append(np.array([np.cos(ang / 2), np.exp(1j * phi) * np.sin(ang / 2)]))
    return out


def is_degree(A, rng=None, grid=None, refine=True):
    """alpha_IS estimate for a qubit (or any d with a user grid).
    Returns dict lo/hi: hi = min over scanned v of the primal value (an upper
    bound on alpha_IS achieved by an explicit B); lo = min over scanned v of
    the dual value (a lower bound on f(v) for those v only)."""
    d = A[0].shape[0]
    if grid is None:
        assert d == 2, "supply a grid of states for d != 2"
        grid = bloch_grid(8)
    vals = []
    for v in grid:
        p, du, B = is_degree_fixed_state(A, v, rng=rng, restarts=1)
        vals.append((p, du, v, B))
    vals.sort(key=lambda t: t[0])
    best = vals[0]
    if refine and d == 2:
        # local refinement of the outer minimisation on the Bloch sphere
        def f(ang):
            th, ph = ang
            v = np.array([np.cos(th / 2), np.exp(1j * ph) * np.sin(th / 2)])
            return is_degree_fixed_state(A, v, rng=rng, restarts=1)[0]
        v0 = best[2]
        th0 = 2 * np.arccos(np.clip(abs(v0[0]), 0, 1))
        ph0 = np.angle(v0[1]) - np.angle(v0[0]) if abs(v0[1]) > 1e-12 else 0.0
        res = minimize(f, [th0, ph0], method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 1e-7, "maxiter": 30, "maxfev": 40})
        th, ph = res.x
        v = np.array([np.cos(th / 2), np.exp(1j * ph) * np.sin(th / 2)])
        p, du, B = is_degree_fixed_state(A, v, rng=rng, restarts=3)
        if p < best[0]:
            best = (p, du, v, B)
    return {"hi": float(best[0]), "lo_at_v": float(best[1]), "v": best[2], "B": best[3],
            "scan": [(p, du) for p, du, _, _ in vals]}


def witness_joint_from_common_lower_bound(A, x1, x2, c):
    """Given a common lower bound c of a_{x1}, a_{x2}, build the explicit
    B in JM(A,A) that moves c off the diagonal (definition-level construction)."""
    n = len(A)
    d = A[0].shape[0]
    B = [[np.zeros((d, d), dtype=complex) for _ in range(n)] for _ in range(n)]
    for i in range(n):
        B[i][i] = A[i].copy()
    B[x1][x1] = A[x1] - c
    B[x2][x2] = A[x2] - c
    B[x1][x2] = c
    B[x2][x1] = c
    return B


def check_joint(A, B, tol=1e-7):
    n = len(A)
    ok = all(is_psd(B[i][j], tol) for i in range(n) for j in range(n))
    for i in range(n):
        ok = ok and np.allclose(sum(B[i][j] for j in range(n)), A[i], atol=tol)
        ok = ok and np.allclose(sum(B[j][i] for j in range(n)), A[i], atol=tol)
    return ok


# ----------------------------------------------------------------------------
# coherent-state POVM: finite numerical anchors for the continuous outcome case
# ----------------------------------------------------------------------------
def coherent_resolution_matrix(
    n_fock=8,
    quadrature_order=24,
    amplitude_exponent=0.5,
):
    """Truncated integral of |z><z| d^2z/pi by product Gauss--Hermite quadrature.

    ``amplitude_exponent`` is ``a`` in the coherent amplitude
    exp(-a |z|^2).  The physical value is a=1/2.  Hermite weights already
    contain exp(-x^2-y^2), so only exp((1-2a)(x^2+y^2)) remains.

    This checks a finite normalization identity only; it is not an
    extremality or joint-uniqueness proof.
    """
    nodes, weights = hermgauss(quadrature_order)
    factorials = np.sqrt(np.array([math.factorial(n) for n in range(n_fock)]))
    out = np.zeros((n_fock, n_fock), dtype=np.complex128)
    for x, wx in zip(nodes, weights):
        for y, wy in zip(nodes, weights):
            z = x + 1j * y
            r2 = x * x + y * y
            monomials = np.array([z**n for n in range(n_fock)]) / factorials
            residual_weight = math.exp((1.0 - 2.0 * amplitude_exponent) * r2)
            out += (wx * wy / math.pi) * residual_weight * np.outer(
                monomials, monomials.conjugate()
            )
    return out


def coherent_bounded_moment_map(
    n_fock=6,
    polynomial_degree=3,
    beta=0.35,
    quadrature_order=28,
):
    """Finite matrix for h -> integral h(z)|z><z| d^2z/pi.

    Columns use the bounded real test functions
    h_ab(x,y)=x^a y^b exp(-beta |z|^2), a+b<=polynomial_degree.  Operator
    entries are flattened into real coordinates.  Full numerical column rank
    excludes a kernel only in this displayed finite family, not in L-infinity.
    """
    labels = [
        (a, total - a)
        for total in range(polynomial_degree + 1)
        for a in range(total + 1)
    ]
    nodes, weights = hermgauss(quadrature_order)
    factorials = np.sqrt(np.array([math.factorial(n) for n in range(n_fock)]))
    operators = [np.zeros((n_fock, n_fock), dtype=np.complex128) for _ in labels]
    for x, wx in zip(nodes, weights):
        for y, wy in zip(nodes, weights):
            z = x + 1j * y
            r2 = x * x + y * y
            monomials = np.array([z**n for n in range(n_fock)]) / factorials
            projector_without_gaussian = np.outer(monomials, monomials.conjugate())
            common = (wx * wy / math.pi) * math.exp(-beta * r2)
            for operator, (a, b) in zip(operators, labels):
                operator += common * (x**a) * (y**b) * projector_without_gaussian

    columns = [
        np.concatenate([operator.real.ravel(), operator.imag.ravel()])
        for operator in operators
    ]
    return np.column_stack(columns), labels


def coherent_trunc_vector(z, n_fock):
    """<n|z> for n < n_fock (unnormalised in the truncated space; sum |.|^2 = P(Poisson(|z|^2) < n_fock))."""
    n = np.arange(n_fock)
    v = np.zeros(n_fock, dtype=complex)
    if z == 0:
        v[0] = 1.0
        return v
    logw = -abs(z) ** 2 / 2 + n * np.log(abs(z)) - 0.5 * np.array([math.lgamma(k + 1) for k in n])
    return np.exp(logw) * np.exp(1j * n * np.angle(z))


def coherent_cell_matrix(z0, side, n_fock, quadrature_order=32):
    """P_N A(V) P_N for the square cell V = {|Re(z - z0)| <= side/2, |Im(z - z0)| <= side/2},
    A(V) = (1/pi) ∫_V |z><z| d^2z, by tensor Gauss–Legendre on the cell (smooth integrand).
    Untruncated identities to test against: Tr A(V) = |V|/pi; ∑_cells A(V) = 1 (see selftest)."""
    x, w = leggauss(quadrature_order)
    z0 = complex(z0)
    xs, ys = z0.real + (side / 2) * x, z0.imag + (side / 2) * x
    M = np.zeros((n_fock, n_fock), dtype=complex)
    for xi, wx in zip(xs, w):
        for yj, wy in zip(ys, w):
            v = coherent_trunc_vector(complex(xi, yj), n_fock)
            M += (wx * wy * (side / 2) ** 2 / math.pi) * np.outer(v, v.conj())
    return (M + M.conj().T) / 2


def symmetrised_coherent_cell(z0, side, n_fock, quadrature_order=32):
    """A'(V) = (A(V) + A(-V)) / 2 — the z -> -z symmetrised Husimi POVM (a POVM, density rank 2 a.e.).
    Foil model for continuous-outcome intersubjectivity: cells V and -V share the common lower
    bound A(V)/2 (ratio 1/2 at every scale), and the anti-diagonal joint
    B(E) = (1/2pi)∫_{(z,-z)∈E}|z><z| + (1/2pi)∫_{(-z,z)∈E}|z><z| is a non-canonical self-joint."""
    return (coherent_cell_matrix(z0, side, n_fock, quadrature_order)
            + coherent_cell_matrix(-complex(z0), side, n_fock, quadrature_order)) / 2


def nearly_rank_one_clb_bound(X, Y, u, v):
    """Explicit dual certificate for max{Tr c : 0 <= c <= X, c <= Y} built from unit vectors u, v:
         Tr c (1 - |<u|v>|) <= Tr(Q_u X) + Tr(Q_v Y),   Q_u = 1 - |u><u|.
    Proof: Tr(c(p_u + p_v)) <= ||p_u + p_v|| Tr c = (1 + |<u|v>|) Tr c and
           Tr(c p_u) = Tr c - Tr(Q_u c) >= Tr c - Tr(Q_u X)  (0 <= c <= X, Q_u >= 0).
    Equivalently (Y', Z') = t (Q_u, Q_v), t = 1/(1 - |<u|v>|), is dual feasible (Y' + Z' >= 1) with
    objective Tr(X Y' + Y Z') = the bound.  Tight when X, Y are nearly rank one along u, v (e.g.
    small Husimi cells at their centres: bound O(s^4) vs Tr X O(s^2)).
    Returns (bound, overlap |<u|v>|, Tr(Q_u X), Tr(Q_v Y))."""
    u = np.asarray(u) / np.linalg.norm(u)
    v = np.asarray(v) / np.linalg.norm(v)
    tqx = float(np.trace(X).real - (u.conj() @ X @ u).real)
    tqy = float(np.trace(Y).real - (v.conj() @ Y @ v).real)
    ov = abs(complex(u.conj() @ v))
    return (tqx + tqy) / (1 - ov), ov, tqx, tqy


# ----------------------------------------------------------------------------
# polytope GPTs: state space conv(V), V = array (k, m); effects = vectors e in R^m
# with e·v in [0,1] for all vertices v.  (Coordinates include the normalisation
# coordinate, so linear functionals e·x exhaust the affine functionals.)
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# Infinite-dimensional anchors (see docstring "Infinite-dimensional addendum")
# ----------------------------------------------------------------------------
def common_lower_bound_sandwich(a, b, delta=1e-14, dps=None):
    """Solver-free bracket [lo, hi] = [||a:b||, 2||a:b||] for max{||c|| : 0 <= c <= a, c <= b}.
    a:b = ((a+δ)^{-1} + (b+δ)^{-1})^{-1} (regularised parallel sum, δ >= input noise so a+δ, b+δ are PD).
    With dps set, the inverses are formed in mpmath at that many digits (needed when a has eigenvalues
    below ~1e-8: the float inverse loses them).  Asserts that a:b is a common lower bound up to 1e-12."""
    if dps is None:
        c = parallel_sum(a, b, delta=delta)
        assert is_psd(a - c, tol=1e-12 + delta) and is_psd(b - c, tol=1e-12 + delta)
        v = eigmax(c)
        return v, 2 * v
    import mpmath as mp
    with mp.workdps(dps):                     # never leave the global precision changed (other callers compare floats)
        A = mp.matrix([[mp.mpc(complex(a[i, j])) for j in range(a.shape[1])] for i in range(a.shape[0])])
        B = mp.matrix([[mp.mpc(complex(b[i, j])) for j in range(b.shape[1])] for i in range(b.shape[0])])
        I = mp.eye(A.rows)
        C = mp.inverse(mp.inverse(A + delta * I) + mp.inverse(B + delta * I))
        C = (C + C.H) / 2
        for M in (A - C, B - C):
            assert min(mp.eighe(M)[0]) > -mp.mpf(1e-12), "parallel sum is not a common lower bound (numerics)"
        v = float(max(mp.eighe(C)[0]))
    return v, 2 * v


def fourier_arc_gram(N, alpha, beta, dps=100):
    """Gram matrix G_{mn} = (1/2pi) ∫_alpha^beta e^{i(n-m)theta} dtheta, |m|,|n| <= N, in mpmath at `dps` digits.
    G positive definite  <=>  no nonzero trig polynomial of degree <= N vanishes a.e. on the arc (alpha, beta)
    <=>  e_N ∧ P_{S^1 \\ arc} = 0.  lambda_min decays super-exponentially with N (~1e-38 at N = 16), so the
    positivity certificate needs high precision.  Returns (G, lambda_min)."""
    import mpmath as mp
    with mp.workdps(dps):
        idx = list(range(-N, N + 1))
        G = mp.matrix(len(idx), len(idx))
        alpha, beta = mp.mpf(alpha), mp.mpf(beta)
        for i, m in enumerate(idx):
            for j, n in enumerate(idx):
                k = n - m
                G[i, j] = (beta - alpha) / (2 * mp.pi) if k == 0 else (mp.expj(k * beta) - mp.expj(k * alpha)) / (2 * mp.pi * 1j * k)
        E, _ = mp.eighe(G)
        lam = min(E)
    return G, lam


def analytic_class_arc_povm(N, alpha=0.0, beta=2.0, decay=2.0):
    """Fourier truncation (|n| <= N) of the 3-outcome family a_1 = ½ diag(e^{-decay|n|}), d = 1 - a_1,
    a_2 = d^{1/2} P_N d^{1/2}, a_3 = d^{1/2} (1-P_N) d^{1/2}, where P_N is the spectral projection (eigenvalues
    > 1/2) of the compression of P_I, I = S^1 \\ (alpha, beta).  In the limit the square-root ranges intersect
    pairwise trivially while the closed supports of a_1 and a_2 overlap (docstring).  Returns [a_1, a_2, a_3]
    as numpy arrays (double precision; P_N from the double-precision Gram)."""
    idx = np.arange(-N, N + 1)
    lam = 0.5 * np.exp(-decay * np.abs(idx))
    a1 = np.diag(lam).astype(complex)
    d12 = np.sqrt(np.diag(1.0 - lam)).astype(complex)
    G, _ = fourier_arc_gram(N, alpha, beta, dps=30)
    Gd = np.array([[complex(G[i, j]) for j in range(G.cols)] for i in range(G.rows)])
    GI = np.eye(len(idx)) - (Gd + Gd.conj().T) / 2          # compression of 1_I
    w, U = np.linalg.eigh(GI)
    V = U[:, w > 0.5]
    PN = V @ V.conj().T
    a2 = d12 @ PN @ d12
    a3 = d12 @ (np.eye(len(idx)) - PN) @ d12
    return [a1, (a2 + a2.conj().T) / 2, (a3 + a3.conj().T) / 2]


def husimi_halfplane_matrix(N, right=True):
    """<m|A(U)|n>, m,n <= N, for U = right (Re z > 0) or left half-plane of the Husimi POVM
    A(U) = (1/pi) ∫_U |z><z| d^2z, closed form: angular ∫ e^{i(n-m)theta} over the half circle × Γ((m+n+2)/2)/2."""
    lo, hi = (-math.pi / 2, math.pi / 2) if right else (math.pi / 2, 3 * math.pi / 2)

    def ang(k):
        return hi - lo if k == 0 else (np.exp(1j * k * hi) - np.exp(1j * k * lo)) / (1j * k)
    M = np.zeros((N + 1, N + 1), dtype=complex)
    for m in range(N + 1):
        for n in range(N + 1):
            M[m, n] = ang(n - m) * math.gamma((m + n + 2) / 2) / 2 / math.pi / math.sqrt(float(math.factorial(m)) * float(math.factorial(n)))
    return (M + M.conj().T) / 2


def husimi_dbar_witness(N, right=True, z0=0.0):
    """Common-element witness for the two half-plane cells: psi_n = (1/pi) ∫_U dbar(phi) z^n/sqrt(n!) d^2z with
    phi(z) = exp(-1/(1-|z-z0|^2)) on |z-z0| < 1 (z0 real).  Returns (psi, ||1_U h||^2), h = e^{|z|^2/2} dbar(phi),
    so that |psi><psi| / ||1_U h||^2 <= A(U).  For z0 = 0 the disc straddles both cells and psi != 0 (psi_0 =
    -∫_0^1 r^2 e^{-1/(1-r^2)} (1-r^2)^{-2} dr < 0); for |z0| >= 1 the bump lies in one cell and psi = 0 (Stokes) —
    the built-in foil."""
    from scipy.integrate import quad
    psi = np.zeros(N + 1, dtype=complex)
    dphi = lambda r: -np.exp(-1.0 / (1 - r * r)) / (1 - r * r) ** 2 if r < 1 else 0.0

    def theta_range(r):
        c = (-z0 / r) if right else (z0 / r)
        if c <= -1:
            return [(-math.pi, math.pi)]
        if c >= 1:
            return []
        t = math.acos(c)
        return [(-t, t)] if right else [(math.pi - t, math.pi + t)]

    def ang(k, lo, hi):
        return hi - lo if k == 0 else (np.exp(1j * k * hi) - np.exp(1j * k * lo)) / (1j * k)

    for n in range(N + 1):
        def integrand(r):
            tot = 0.0 + 0.0j
            for (lo, hi) in theta_range(r):
                for j in range(n + 1):
                    coef = math.comb(n, j) * z0 ** (n - j) * r ** j
                    tot += coef * r * ang(j + 1, lo, hi)
            return dphi(r) * r * tot / math.sqrt(float(math.factorial(n))) / math.pi
        psi[n] = quad(lambda r: integrand(r).real, 0, 1, limit=200)[0] + 1j * quad(lambda r: integrand(r).imag, 0, 1, limit=200)[0]

    def nrm(r):
        tot = 0.0
        for (lo, hi) in theta_range(r):
            tot += quad(lambda th: np.exp(abs(z0 + r * np.exp(1j * th)) ** 2), lo, hi)[0]
        return dphi(r) ** 2 * r ** 3 * tot / math.pi
    f2 = quad(nrm, 0, 1, limit=200)[0]
    return psi, f2


class Polytope:
    def __init__(self, V):
        self.V = np.asarray(V, dtype=float)
        self.k, self.m = self.V.shape
        self.unit = self._find_unit()

    def _find_unit(self):
        # any e with e·v = 1 for all vertices (exists since a normalisation coordinate is present)
        e, *_ = np.linalg.lstsq(self.V, np.ones(self.k), rcond=None)
        assert np.allclose(self.V @ e, 1), "no unit effect: vertices must carry a normalisation coordinate"
        return e

    def vals(self, e):
        return self.V @ np.asarray(e, dtype=float)

    def is_effect(self, e, tol=1e-9):
        v = self.vals(e)
        return v.min() >= -tol and v.max() <= 1 + tol

    def is_measurement(self, A, tol=1e-9):
        return all(self.is_effect(a, tol) for a in A) and np.allclose(self.vals(sum(A)), 1, atol=tol)

    # -- LP helpers (variables = coefficient vectors of effects)
    def max_common_lower_bound_norm(self, a, b):
        """max ||c|| = max_v c(v) over effects c <= a, c <= b (exact LP)."""
        best = (0.0, None)
        va, vb = self.vals(a), self.vals(b)
        for v0 in self.V:
            # max c·v0  s.t. 0 <= V c <= min(va, vb)
            res = linprog(-v0, A_ub=np.vstack([self.V, -self.V]),
                          b_ub=np.concatenate([np.minimum(va, vb), np.zeros(self.k)]),
                          bounds=[(None, None)] * self.m, method="highs")
            assert res.status == 0, res.message
            if -res.fun > best[0]:
                best = (float(-res.fun), res.x)
        return best

    def is_degree(self, A):
        """alpha_IS(A) = min_{B in JM(A,A)} min_v sum_x b_xx(v), exact LP per vertex."""
        n = len(A)
        best = np.inf
        Avals = [self.vals(a) for a in A]
        nvar = n * n * self.m

        def idx(i, j):
            return slice((i * n + j) * self.m, (i * n + j + 1) * self.m)
        # equality: marginals at every vertex
        Aeq, beq = [], []
        for i in range(n):
            for v_i, v in enumerate(self.V):
                row = np.zeros(nvar)
                for j in range(n):
                    row[idx(i, j)] = v
                Aeq.append(row); beq.append(Avals[i][v_i])
                row = np.zeros(nvar)
                for j in range(n):
                    row[idx(j, i)] = v
                Aeq.append(row); beq.append(Avals[i][v_i])
        # inequality: 0 <= b_ij(v) <= 1
        Aub, bub = [], []
        for i in range(n):
            for j in range(n):
                for v in self.V:
                    row = np.zeros(nvar); row[idx(i, j)] = -v; Aub.append(row); bub.append(0.0)
                    row = np.zeros(nvar); row[idx(i, j)] = v; Aub.append(row); bub.append(1.0)
        Bbest = None
        for v0 in self.V:
            cobj = np.zeros(nvar)
            for i in range(n):
                cobj[idx(i, i)] = v0
            res = linprog(cobj, A_ub=np.array(Aub), b_ub=np.array(bub), A_eq=np.array(Aeq), b_eq=np.array(beq),
                          bounds=[(None, None)] * nvar, method="highs")
            assert res.status == 0, res.message
            if res.fun < best:
                best = res.fun
                Bbest = [[res.x[idx(i, j)] for j in range(n)] for i in range(n)]
        return float(best), Bbest

    def is_extremal(self, A):
        """A extreme in M_S(X)  <=>  no delta != 0 with A ± delta measurements."""
        n = len(A)
        nvar = n * self.m
        Avals = [self.vals(a) for a in A]
        Aeq, beq = [], []
        for v in self.V:  # sum_x delta_x(v) = 0
            row = np.zeros(nvar)
            for i in range(n):
                row[i * self.m:(i + 1) * self.m] = v
            Aeq.append(row); beq.append(0.0)
        Aub, bub = [], []
        for i in range(n):
            for v_i, v in enumerate(self.V):
                for sgn in (+1, -1):  # 0 <= a_x(v) + sgn*delta_x(v) <= 1
                    row = np.zeros(nvar); row[i * self.m:(i + 1) * self.m] = -sgn * v
                    Aub.append(row); bub.append(Avals[i][v_i])
                    row = np.zeros(nvar); row[i * self.m:(i + 1) * self.m] = sgn * v
                    Aub.append(row); bub.append(1 - Avals[i][v_i])
        worst = 0.0
        for i in range(n):
            for v in self.V:
                cobj = np.zeros(nvar); cobj[i * self.m:(i + 1) * self.m] = -v
                # box bounds only guard against HiGHS declaring 'unbounded' on near-singular
                # vertex matrices; a hit on the box is reported as an error, not a verdict
                res = linprog(cobj, A_ub=np.array(Aub), b_ub=np.array(bub), A_eq=np.array(Aeq), b_eq=np.array(beq),
                              bounds=[(-BOX, BOX)] * nvar, method="highs")
                assert res.status == 0, res.message
                assert np.max(np.abs(res.x)) < 0.99 * BOX, "extremality LP hit the box bound"
                worst = max(worst, -res.fun)
        return worst < 1e-9, worst

    def is_indecomposable(self, a):
        """a != 0 indecomposable  <=>  every effect b <= a is a multiple of a.
        Test: maximise the distance of b from the ray {t a} over b <= a (LP on |.|_1 proxy):
        we check whether the cone {b : 0 <= b <= a} is one-dimensional by computing
        the rank of its extreme directions found by LP in random objective directions."""
        va = self.vals(a)
        found = []
        rng = np.random.default_rng(0)
        for _ in range(12):
            cobj = rng.normal(size=self.m)
            res = linprog(cobj, A_ub=np.vstack([self.V, -self.V]),
                          b_ub=np.concatenate([va, np.zeros(self.k)]),
                          bounds=[(None, None)] * self.m, method="highs")
            if res.status == 0:
                found.append(self.vals(res.x))
        M = np.array([f for f in found if np.linalg.norm(f) > 1e-9])
        if len(M) == 0:
            return False  # a = 0
        return np.linalg.matrix_rank(M, tol=1e-8) == 1


def polytope_vertices_from_halfspaces(A_ub, b_ub, A_eq, b_eq):
    """Brute-force vertex enumeration of {x : A_ub x <= b_ub, A_eq x = b_eq} (small dims)."""
    A_ub, b_ub = np.asarray(A_ub, float), np.asarray(b_ub, float)
    A_eq, b_eq = np.asarray(A_eq, float), np.asarray(b_eq, float)
    m = A_ub.shape[1]
    need = m - A_eq.shape[0]
    verts = []
    for S in itertools.combinations(range(A_ub.shape[0]), need):
        M = np.vstack([A_eq, A_ub[list(S)]])
        rhs = np.concatenate([b_eq, b_ub[list(S)]])
        if np.linalg.matrix_rank(M) < m:
            continue
        x = np.linalg.solve(M, rhs)
        if np.all(A_ub @ x <= b_ub + 1e-9) and np.allclose(A_eq @ x, b_eq):
            if not any(np.allclose(x, v) for v in verts):
                verts.append(x)
    return np.array(verts)


# ----------------------------------------------------------------------------
# classical couplings (LP)
# ----------------------------------------------------------------------------
def min_diag_coupling(p):
    """min sum_i pi_ii over couplings pi >= 0 with both marginals p (exact LP)."""
    p = np.asarray(p, float)
    n = len(p)
    c = np.zeros(n * n)
    for i in range(n):
        c[i * n + i] = 1
    Aeq, beq = [], []
    for i in range(n):
        row = np.zeros(n * n); row[i * n:(i + 1) * n] = 1; Aeq.append(row); beq.append(p[i])
        row = np.zeros(n * n); row[i::n] = 1; Aeq.append(row); beq.append(p[i])
    res = linprog(c, A_eq=np.array(Aeq), b_eq=np.array(beq), bounds=[(0, None)] * (n * n), method="highs")
    assert res.status == 0
    return float(res.fun), res.x.reshape(n, n)


def report(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return ok


# ----------------------------------------------------------------------------
# self-test (paper-independent anchors)
# ----------------------------------------------------------------------------
def _selftest():
    rng = np.random.default_rng(0)
    I2 = np.eye(2, dtype=complex)
    sz = np.diag([1.0, -1.0]).astype(complex)
    P0, P1 = np.diag([1.0, 0]).astype(complex), np.diag([0, 1.0]).astype(complex)
    okk = True
    # common lower bounds: orthogonal projections -> 0, identical -> Tr P
    r = max_common_lower_bound(P0, P1); okk &= abs(r["primal"]) < 1e-7 and abs(r["dual"]) < 1e-7
    r = max_common_lower_bound(P0, P0); okk &= abs(r["primal"] - 1) < 1e-6 and abs(r["dual"] - 1) < 1e-6
    # 2-outcome: alpha_IS(unbiased |lam|=0.6) = 0.36 by the exact n=2 relation alpha = 1 - 2 max||c||
    A = [0.5 * (I2 + 0.6 * sz), 0.5 * (I2 - 0.6 * sz)]
    val, _, _ = max_common_lower_bound_norm(A[0], A[1], rng=rng, directions=bloch_grid(120))
    okk &= abs((1 - 2 * val) - 0.36) < 3e-3
    # coin toss: min-diagonal coupling of (1/2,1/2) is 0; of (0.7,0.3) is 0.4
    okk &= abs(min_diag_coupling([0.5, 0.5])[0]) < 1e-12 and abs(min_diag_coupling([0.7, 0.3])[0] - 0.4) < 1e-12
    # square model: (b+,b-) extremal with alpha_IS = 1, the coin has alpha_IS = 0
    S = Polytope(np.array([[1, 1, 1], [1, -1, 1], [-1, 1, 1], [-1, -1, 1]], float))
    bp, bm = np.array([0.5, 0, 0.5]), np.array([-0.5, 0, 0.5])
    okk &= S.is_measurement([bp, bm]) and abs(S.is_degree([bp, bm])[0] - 1) < 1e-9 and S.is_extremal([bp, bm])[0]
    okk &= abs(S.is_degree([np.array([0, 0, 0.5])] * 2)[0]) < 1e-9
    okk &= len(set_partitions(4)) == 15
    # support criterion vs witness: rank-1 distinct directions -> trivial intersection
    a = np.outer([1, 0], [1, 0]).astype(complex); b = 0.5 * np.array([[1, 1], [1, 1]], complex)
    okk &= supports_intersect_trivially(a, b) and not supports_intersect_trivially(a, a)
    # Husimi anchors: correct normalization and finite bounded-family injectivity.
    resolution = coherent_resolution_matrix()
    okk &= np.linalg.norm(resolution - np.eye(resolution.shape[0]), ord=2) < 5e-12
    moment_map, labels = coherent_bounded_moment_map()
    okk &= np.linalg.matrix_rank(moment_map, tol=1e-10) == len(labels)
    # Internal foil: exp(-|z|^2/4) gives vacuum normalization 2 rather than 1.
    broken = coherent_resolution_matrix(amplitude_exponent=0.25)
    okk &= abs(float(broken[0, 0].real) - 1.0) > 0.9
    # Infinite-dimensional anchors.  (i) sandwich: a:a = a/2, so identical projections -> [1/2, 1]
    # (true max ||c|| = 1 sits at the upper end), orthogonal projections -> 0.
    lo, hi = common_lower_bound_sandwich(P0, P0); okk &= abs(lo - 0.5) < 1e-6 and abs(hi - 1) < 1e-6
    lo, hi = common_lower_bound_sandwich(P0, P1); okk &= hi < 1e-9
    lo_mp, _ = common_lower_bound_sandwich(P0, P0, dps=30); okk &= abs(lo_mp - 0.5) < 1e-9
    # (ii) arc Gram positive definite and lambda_min decreasing (meet e_N ∧ P_I = 0 for every N).
    l4 = fourier_arc_gram(4, 0.0, 2.0)[1]; l8 = fourier_arc_gram(8, 0.0, 2.0)[1]
    okk &= l4 > 0 and l8 > 0 and l8 < l4 / 1e6
    okk &= fourier_arc_gram(3, 0.0, 0.0)[1] == 0          # foil: empty arc -> G = 0
    # (iii) 3-outcome family: POVM on V_N, pair (2,3) has no common lower bound, a_1 injective, a_2 singular.
    A3 = analytic_class_arc_povm(6)
    okk &= is_measurement(A3, tol=1e-9)
    okk &= common_lower_bound_sandwich(A3[1], A3[2], dps=40)[1] < 1e-9
    okk &= np.min(np.diag(A3[0]).real) > 0 and np.linalg.matrix_rank(A3[1], tol=1e-10) < A3[1].shape[0]
    # (iv) Husimi half-planes: A(right) + A(left) = 1; dbar witness nonzero and a common lower bound; foil z0 = 3.
    AR, AL = husimi_halfplane_matrix(6, True), husimi_halfplane_matrix(6, False)
    okk &= np.allclose(AR + AL, np.eye(7), atol=1e-12)
    psi, f2 = husimi_dbar_witness(6, True); psiL, f2L = husimi_dbar_witness(6, False)
    okk &= np.linalg.norm(psi) > 1e-3 and np.allclose(psiL, -psi, atol=1e-9)
    cw = np.outer(psi, psi.conj())          # (name kept distinct from the later 2α-block variable c)
    okk &= eigmin(AR - cw / f2) > -1e-10 and eigmin(AL - cw / f2L) > -1e-10
    okk &= np.linalg.norm(husimi_dbar_witness(4, True, z0=3.0)[0]) < 1e-12
    # Husimi square cells: Tr A_N(V) -> |V|/pi, a coarse grid sums to ~1, and the nearly-rank-one
    # certificate bounds an explicit common lower bound while a non-lower-bound (c = X) violates it.
    X, Y = coherent_cell_matrix(0.5, 0.4, 9), coherent_cell_matrix(-0.5, 0.4, 9)
    okk &= abs(np.trace(X).real - 0.16 / math.pi) < 1e-9
    grid = sum(coherent_cell_matrix(complex(i + 0.5, j + 0.5) * 0.5, 0.5, 4, 12) for i in range(-8, 8) for j in range(-8, 8))
    okk &= np.linalg.norm(grid - np.eye(4), ord=2) < 1e-3
    u, v = coherent_trunc_vector(0.5, 9), coherent_trunc_vector(-0.5, 9)
    bound, ov, _, _ = nearly_rank_one_clb_bound(X, Y, u, v)
    okk &= abs(ov - math.exp(-0.5)) < 1e-9
    c = 0.5 * parallel_sum(X, Y)                      # an explicit common lower bound (delta-regularised: feasible to ~1e-9)
    okk &= eigmin(X - c) > -1e-8 and eigmin(Y - c) > -1e-8 and np.trace(c).real <= bound
    okk &= np.trace(X).real * (1 - ov) > bound        # foil: c = X is not <= Y and breaks the bound
    Xs, Ys = symmetrised_coherent_cell(0.5, 0.4, 9), symmetrised_coherent_cell(-0.5, 0.4, 9)
    cs = 0.5 * coherent_cell_matrix(0.5, 0.4, 9)      # foil model: A(V)/2 is a common lower bound of A'(V), A'(-V)
    okk &= eigmin(Xs - cs) > -1e-12 and eigmin(Ys - cs) > -1e-12 and abs(np.trace(cs).real / np.trace(Xs).real - 0.5) < 1e-12
    print("gpt_measurements selftest:", "PASS" if okk else "FAIL")
    return 0 if okk else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__.splitlines()[0])
