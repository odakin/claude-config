#!/usr/bin/env python3
"""check-dirac-conventions.py — conventions/dirac-conventions.md の対応表と変換の辞書を、 教科書 3 冊が印字した明示表現 (γ 行列) で数値検算する (負の対照つき)。

使い方:
  python3 scripts/check-dirac-conventions.py          # 全検査、 失敗があれば exit 1
  python3 scripts/check-dirac-conventions.py --quiet  # PASS 行を出さず、 失敗だけ出す

何を検算するか (各行の出典 = conventions/dirac-conventions.md の表):
  1. 各教科書の明示表現が、 その本の宣言どおりの Clifford 代数を満たす
     (Peskin–Schroeder {γ,γ} = +2g, g = diag(+,−,−,−) / Srednicki {γ,γ} = −2g, g = diag(−,+,+,+) /
      Weinberg {γ,γ} = +2η, η = diag(−,+,+,+))
  2. (γ⁰)² の符号と γ^μ の Hermite 性、 Weinberg の βγ^{μ†}β = −γ^μ
  3. 辞書: γ_W = −i γ_S (印字どおり)、 γ_P = γ_S (同じ数値行列)、 β_W = iγ⁰_W = β_S = γ⁰_P
  4. 自由ラグランジアンの行列部分が 3 冊で一致する (ψ̄ が共通なので行列の等式で足りる)
  5. Dirac 方程式の運動量空間の核が一致する
  6. 伝播関数 ⟨0|Tψ(x)ψ̄(y)|0⟩ の被積分関数 (分子・分母・指数) が一致する
  7. 負の対照: 辞書の符号を 1 つ変えると検査が落ちることを確かめる (検査が判別力を持つ証拠)
  8. u = C v^* の行列 C: 行ごとの条件 (Weinberg の行 γC = Cγ^*、 Srednicki / Peskin の行 γC = −Cγ^*)、 同じ C の
     各行の γ での書き方 (−γ²_W = +iγ²_S)、 u と v の方程式を実際に結ぶこと、 u の双線形を v で書くと運動量の順序が
     入れ替わること (ū_1 A u_2 = v̄_2 (βC A^T βC) v_1)

依存: numpy (無ければ exit 2 で理由を出す)。 公開層 (個人・project の値を持たない)。
"""
from __future__ import annotations

import argparse
import sys

try:
    import numpy as np
except ImportError:  # pragma: no cover
    print("check-dirac-conventions: numpy が無い (pip install numpy)", file=sys.stderr)
    sys.exit(2)

I2 = np.eye(2)
Z2 = np.zeros((2, 2))
SIG = [
    np.array([[0, 1], [1, 0]], dtype=complex),
    np.array([[0, -1j], [1j, 0]], dtype=complex),
    np.array([[1, 0], [0, -1]], dtype=complex),
]


def block(a, b, c, d):
    return np.block([[a, b], [c, d]]).astype(complex)


# --- 印字された明示表現 ----------------------------------------------------
# Peskin–Schroeder (3.25): γ⁰ = (0 1; 1 0), γ^i = (0 σ^i; −σ^i 0)
G_P = [block(Z2, I2, I2, Z2)] + [block(Z2, s, -s, Z2) for s in SIG]
# Srednicki (36.7): γ^μ = (0 σ^μ; σ̄^μ 0), σ^μ = (I, σ⃗), σ̄^μ = (I, −σ⃗)
SIG_UP = [I2] + SIG
SIG_BAR = [I2] + [-s for s in SIG]
G_S = [block(Z2, SIG_UP[m], SIG_BAR[m], Z2) for m in range(4)]
# Weinberg (5.4.17): γ⁰ = −i(0 1; 1 0), γ⃗ = −i(0 σ⃗; −σ⃗ 0)
G_W = [-1j * g for g in G_P]

ETA_P = np.diag([1.0, -1.0, -1.0, -1.0])  # Notations and Conventions p. xix
ETA_S = np.diag([-1.0, 1.0, 1.0, 1.0])  # (1.8), (2.4)
ETA_W = np.diag([-1.0, 1.0, 1.0, 1.0])  # (2.3.3)

BETA_P = G_P[0]  # (3.32) ψ̄ = ψ†γ⁰
BETA_S = G_S[0]  # (36.21)「数値として β = γ⁰」

QUIET = False


def make_check(fails: list[str]):
    def check(name: str, ok: bool) -> None:
        if ok:
            if not QUIET:
                print(f"PASS  {name}")
        else:
            fails.append(name)
            print(f"FAIL  {name}")

    return check


def close(a, b) -> bool:
    return bool(np.allclose(a, b, atol=1e-12))


def anticomm(g):
    return [[g[m] @ g[n] + g[n] @ g[m] for n in range(4)] for m in range(4)]


def slash(g, p_low):
    """γ^μ p_μ (上添字 γ と下添字 p の縮約)。"""
    return sum(g[m] * p_low[m] for m in range(4))


def is_hermitian(a) -> bool:
    return close(a, a.conj().T)


def run_checks(G_W_used=None, note="") -> list[str]:
    """G_W_used を差し替えると負の対照になる。 戻り値 = 落ちた検査の名前。"""
    fails: list[str] = []
    check = make_check(fails)
    GW = G_W if G_W_used is None else G_W_used
    E4 = np.eye(4)

    # 1. Clifford 代数 (各本の宣言)
    ac_P, ac_S, ac_W = anticomm(G_P), anticomm(G_S), anticomm(GW)
    check(f"Peskin (3.22): {{γ,γ}} = +2 g_P{note}",
          all(close(ac_P[m][n], 2 * ETA_P[m, n] * E4) for m in range(4) for n in range(4)))
    check(f"Srednicki (36.9): {{γ,γ}} = −2 g_S{note}",
          all(close(ac_S[m][n], -2 * ETA_S[m, n] * E4) for m in range(4) for n in range(4)))
    check(f"Weinberg (5.4.5): {{γ,γ}} = +2 η_W{note}",
          all(close(ac_W[m][n], 2 * ETA_W[m, n] * E4) for m in range(4) for n in range(4)))

    # 2. (γ⁰)² と Hermite 性
    check("Peskin: (γ⁰)² = +1", close(G_P[0] @ G_P[0], E4))
    check("Srednicki: (γ⁰)² = +1 (p. 237 本文)", close(G_S[0] @ G_S[0], E4))
    check(f"Weinberg: (γ⁰)² = −1{note}", close(GW[0] @ GW[0], -E4))
    check("Peskin/Srednicki: γ⁰ Hermite, γ^i 反 Hermite (明示行列から)",
          is_hermitian(G_P[0]) and all(close(G_P[i].conj().T, -G_P[i]) for i in (1, 2, 3)))
    check(f"Weinberg: γ⁰ 反 Hermite, γ^i Hermite (明示行列から){note}",
          close(GW[0].conj().T, -GW[0]) and all(is_hermitian(GW[i]) for i in (1, 2, 3)))
    BW = 1j * GW[0]  # (5.4.13) β = iγ⁰
    check(f"Weinberg (5.4.29): β = iγ⁰ = (0 1; 1 0){note}", close(BW, block(Z2, I2, I2, Z2)))
    check(f"Weinberg (5.4.30): β γ^{{μ†}} β = −γ^μ{note}",
          all(close(BW @ GW[m].conj().T @ BW, -GW[m]) for m in range(4)))

    # 3. 辞書
    check("γ_P = γ_S (Peskin (3.25) と Srednicki (36.7) は同じ数値行列)",
          all(close(G_P[m], G_S[m]) for m in range(4)))
    check(f"γ_W = −i γ_S (Weinberg (5.4.17) は Srednicki の −i 倍){note}",
          all(close(GW[m], -1j * G_S[m]) for m in range(4)))
    check(f"β_W = β_S = γ⁰_P (ψ̄ = ψ†β が 3 冊で同じ行列){note}",
          close(BW, BETA_S) and close(BETA_S, BETA_P))

    # 4. 自由ラグランジアンの行列部分 (∂_μ → 任意の下添字ベクトル k_μ で代表)
    rng = np.random.default_rng(20261012)
    m = 1.3
    ok_PS = ok_WS = True
    for _ in range(3):
        k = rng.normal(size=4) + 1j * rng.normal(size=4)
        L_P = 1j * slash(G_P, k) - m * E4          # (3.34)  ψ̄(iγ^μ∂_μ − m)ψ
        L_S = 1j * slash(G_S, k) - m * E4          # (36.28) iψ̄γ^μ∂_μψ − mψ̄ψ
        L_W = -(slash(GW, k) + m * E4)             # (7.5.34) −ψ̄(γ^μ∂_μ + m)ψ
        ok_PS &= close(L_P, L_S)
        ok_WS &= close(L_W, L_S)
    check(f"L_free: Peskin = Srednicki (記号ごと同一、 乱数 3 組){note}", ok_PS)
    check(f"L_free: Weinberg = Srednicki (γ_W = −iγ_S で、 乱数 3 組){note}", ok_WS)

    # 5. Dirac 方程式の核: 平面波 ψ ∝ u e^{(正振動数)} を入れた運動量空間の形
    #    上添字 p^μ を共通にとり、 下添字は各本の計量で下げる
    ok_SP = ok_WS = True
    for _ in range(3):
        p_up = rng.normal(size=4)
        pP, pS, pW = ETA_P @ p_up, ETA_S @ p_up, ETA_W @ p_up
        K_P = slash(G_P, pP) - m * E4             # (3.31) に e^{−ip·x}: (p̸ − m)u = 0
        K_S = slash(G_S, pS) + m * E4             # (36.11) に e^{+ipx}: (p̸ + m)u = 0
        K_W = 1j * slash(GW, pW) + m * E4         # (5.5.42): (iγ^μ p_μ + m)u = 0
        ok_SP &= close(K_S, -K_P)
        ok_WS &= close(K_W, K_S)
    check(f"Dirac 核: Srednicki = −Peskin (p̸_S = −p̸_P、 乱数 3 組){note}", ok_SP)
    check(f"Dirac 核: Weinberg = Srednicki (乱数 3 組){note}", ok_WS)

    # 6. 伝播関数 ⟨0|Tψ(x)ψ̄(y)|0⟩ の被積分関数 (off-shell の p^μ、 x−y は任意)
    eps = 1e-3
    ok_SP = ok_WS = ok_exp = True
    for _ in range(3):
        p_up = rng.normal(size=4) * 2.0
        x = rng.normal(size=4)
        pP, pS, pW = ETA_P @ p_up, ETA_S @ p_up, ETA_W @ p_up
        p2P, p2S, p2W = p_up @ pP, p_up @ pS, p_up @ pW
        F_P = 1j * (slash(G_P, pP) + m * E4) / (p2P - m**2 + 1j * eps) * np.exp(-1j * (x @ pP))   # (3.121)
        F_S = (1 / 1j) * (-slash(G_S, pS) + m * E4) / (p2S + m**2 - 1j * eps) * np.exp(1j * (x @ pS))  # (42.11)
        F_W = -1j * (-1j * slash(GW, pW) + m * E4) / (p2W + m**2 - 1j * eps) * np.exp(1j * (x @ pW))  # (6.2.1)(6.2.5)(6.2.18)
        ok_SP &= close(F_S, F_P)
        ok_WS &= close(F_W, F_S)
        ok_exp &= bool(np.isclose(np.exp(-1j * (x @ pP)), np.exp(1j * (x @ pS)))
                       and np.isclose(np.exp(1j * (x @ pS)), np.exp(1j * (x @ pW))))
    check(f"伝播関数 ⟨Tψψ̄⟩ の被積分関数: Srednicki = Peskin (乱数 3 組){note}", ok_SP)
    check(f"伝播関数 ⟨Tψψ̄⟩ の被積分関数: Weinberg = Srednicki (乱数 3 組){note}", ok_WS)
    check("正振動数因子: e^{−ip_P·x} = e^{ip_S·x} = e^{ip_W·x} (乱数 3 組)", ok_exp)

    # 8. u = C v^* の行列 C と、 u の双線形を v で書き直したときの運動量の順序 (doc §2 の「電荷共役」)
    #    C は「その行の u と v の方程式を結ぶ行列」 として定める (教科書の C の記法には依らない)。
    #    Weinberg の行: (iγp + m)u = 0, (iγp − m)v = 0 → 条件 γ_W C = C γ_W^*、 C = −γ²_W (任意の位相倍も可)
    #    Srednicki / Peskin の行: (p̸_S + m)u = 0, (p̸_S − m)v = 0 → 条件 γ_S C = −C γ_S^* (符号が変わる)
    BW0 = 1j * GW[0]
    C = -GW[2]
    ok_cond_W = all(close(GW[mu] @ C, C @ GW[mu].conj()) for mu in range(4))
    ok_cond_S = all(close(G_S[mu] @ C, -C @ G_S[mu].conj()) for mu in range(4))
    naive_S = all(close(G_S[mu] @ C, C @ G_S[mu].conj()) for mu in range(4))
    check(f"C = −γ²_W: 実対称で C² = 1、 γ_W C = C γ_W^*{note}",
          close(C, C.real) and close(C, C.T) and close(C @ C, E4) and ok_cond_W)
    check(f"同じ C は Srednicki の行では γ_S C = −C γ_S^* を満たし、 γ_S C = C γ_S^* (Weinberg の条件の写し) は満たさない{note}",
          ok_cond_S and not naive_S)
    check(f"同じ C を γ_S で書くと +iγ²_S (−iγ²_S ではない){note}",
          close(C, 1j * G_S[2]) and not close(C, -1j * G_S[2]))
    ok_uv_W = ok_uv_S = True
    for _ in range(3):
        p_up = rng.normal(size=4)
        p_up[0] = np.sqrt(m**2 + p_up[1:] @ p_up[1:])
        pW, pS = ETA_W @ p_up, ETA_S @ p_up
        # v を v の方程式の零空間から取り、 u = C v^* が u の方程式を満たすか
        for K_v, K_u, tag in ((1j * slash(GW, pW) - m * E4, 1j * slash(GW, pW) + m * E4, 'W'),
                              (slash(G_S, pS) - m * E4, slash(G_S, pS) + m * E4, 'S')):
            _, sv, vh = np.linalg.svd(K_v)
            vs = vh.conj().T[:, sv < 1e-9]
            good = vs.shape[1] == 2 and all(close(K_u @ (C @ vs[:, k].conj()), np.zeros(4)) for k in range(2))
            if tag == 'W':
                ok_uv_W &= good
            else:
                ok_uv_S &= good
    check(f"Weinberg の行: v が (iγp − m)v = 0 を満たせば u = C v^* は (iγp + m)u = 0 (乱数 3 組){note}", ok_uv_W)
    check(f"Srednicki の行: v が (p̸ − m)v = 0 を満たせば u = C v^* は (p̸ + m)u = 0 (乱数 3 組){note}", ok_uv_S)
    # 双線形: u_i = C v_i^* のとき ū_1 A u_2 = v̄_2 (βC A^T βC) v_1 (運動量の順序が入れ替わる)。
    # βC γ^{μT} βC = γ^μ と (βC)² = −1 から、 A = −i a̸ + b (Weinberg) なら βC A^T βC = −i a̸ − b
    bc = BW0 @ C
    ok_bc = close(bc @ bc, -E4) and all(close(bc @ GW[mu].T @ bc, GW[mu]) for mu in range(4))
    ok_order = True
    swapped_differs = False
    for _ in range(3):
        v1 = rng.normal(size=4) + 1j * rng.normal(size=4)
        v2 = rng.normal(size=4) + 1j * rng.normal(size=4)
        a_low = rng.normal(size=4) + 1j * rng.normal(size=4)
        b = complex(rng.normal(), rng.normal())
        A = -1j * slash(GW, a_low) + b * E4
        u1, u2 = C @ v1.conj(), C @ v2.conj()
        bar = lambda s: s.conj() @ BW0
        lhs = bar(u1) @ A @ u2
        Bv = -1j * slash(GW, a_low) - b * E4
        ok_order &= bool(np.isclose(lhs, bar(v2) @ Bv @ v1)) and close(bc @ A.T @ bc, Bv)
        swapped_differs |= not bool(np.isclose(lhs, bar(v1) @ Bv @ v2))
    check(f"Weinberg の行: (βC)² = −1、 βC γ^{{μT}} βC = γ^μ{note}", ok_bc)
    check(f"ū_1(−ia̸ + b)u_2 = v̄_2(−ia̸ − b)v_1 で、 順序をそのままにした v̄_1(…)v_2 とは一致しない (乱数 3 組){note}",
          ok_order and swapped_differs)
    return fails


def main() -> int:
    global QUIET
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    QUIET = args.quiet

    fails = run_checks()

    # 7. 負の対照: γ_W = +i γ_S と置き間違えると、 Weinberg 側の検査が落ちるはず
    print("--- 負の対照 (γ_W = +iγ_S と誤った辞書。 落ちる検査を数える) ---")
    saved_quiet = QUIET
    QUIET = True
    control_fails = run_checks(G_W_used=[1j * g for g in G_S], note=" [負の対照]")
    QUIET = saved_quiet
    for name in control_fails:
        print(f"      期待どおり落ちた: {name}")
    check = make_check(fails)
    check("負の対照: 誤った辞書では Weinberg 側の検査が落ちる", len(control_fails) > 0)

    print(f"--- 結果: 本検査の失敗 {len(fails)} 件 / 負の対照で落ちた検査 {len(control_fails)} 件 ---")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
