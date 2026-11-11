#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-novelty-example.py — conventions/novelty-comparison.md の合成の例 (初等力学の周期) の式を数値で確かめる。 --selftest 内蔵。

用途: 規約の合成の例が書いている式と言明を、 例を直したときにも守る (例の式を変えたら、 ここの対応する検査も直す)。
確かめるのは式と数値だけで、 例の判定の語 (印刷されている・先行研究だけから出る など) は確かめない。

1 次元の保存力の下の周期 T(E) = sqrt(2m) * ∫_{x1}^{x2} dx / sqrt(E - V(x)) を、 転回点の 1/sqrt の特異性を
x = c + h sin(θ) の置換で消した中点則で積分する。 確かめる項目:

  1. V = -V0 / cosh^2(x/a)、 -V0 < E < 0: T = π a sqrt(2m/|E|) (V0 に依らない)            〔例の行 3〕
  2. V = A x^2 + B / x^2 (x > 0): T = π sqrt(m/(2A)) (E にも B にも依らない)              〔例の行 4 の反例〕
  3. V = k x^4: T は E に依る (項目 2 の対照。 周期が E に依らないことが積分の作りから出ていないことを見る)
  4. 左右非対称な井戸 V = x^2 + x^3/3 と、 その鏡映 V(-x): 同じ E で周期が等しい            〔例の行 2〕
  5. V = k (x - c)^2 / 2 + V1: T = 2π sqrt(m/k) (平行移動に依らない)                       〔規則 8 の例〕
  6. V = -cos x で E を極大の値 1 に近づけると、 周期が増え続ける (転回点が極大に当たると周期は有限でない)
     〔教科書役の結果の条件「転回点で V の傾きが零でない」 が要る理由〕

使い方:
  python3 scripts/check-novelty-example.py            # 項目ごとの数値と PASS / FAIL (失敗があれば exit 1)
  python3 scripts/check-novelty-example.py --selftest # 同じ検査を静かに回す (exit 0 = 全部 PASS)
"""
import argparse
import math
import sys


def period(V, x1, x2, E, m=1.0, n=100000):
    """T(E) between turning points x1 < x2 (midpoint rule in θ, x = c + h sin θ)."""
    c, h = (x1 + x2) / 2.0, (x2 - x1) / 2.0
    s = 0.0
    for i in range(n):
        th = -math.pi / 2.0 + (i + 0.5) * math.pi / n
        x = c + h * math.sin(th)
        s += h * math.cos(th) / math.sqrt(max(E - V(x), 1e-300))
    return math.sqrt(2.0 * m) * s * math.pi / n


def bisect(f, lo, hi, it=200):
    """Root of f in [lo, hi] (f(lo) and f(hi) have opposite signs)."""
    flo = f(lo)
    for _ in range(it):
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2.0


def checks():
    """Yield (label, passed, detail)."""
    m = 1.0
    # 1. sech^2 well
    for V0, a, E in [(1.0, 1.0, -0.3), (5.0, 0.7, -0.3), (5.0, 0.7, -4.0)]:
        xt = a * math.acosh(math.sqrt(V0 / abs(E)))
        T = period(lambda x: -V0 / math.cosh(x / a) ** 2, -xt, xt, E, m)
        exact = math.pi * a * math.sqrt(2.0 * m / abs(E))
        yield (f"1 sech2 V0={V0} a={a} E={E}", abs(T - exact) < 1e-4 * exact, f"T={T:.6f} 式={exact:.6f}")
    # 2. x^2 + 1/x^2 on the half line
    for A, B, E in [(1.0, 0.5, 2.0), (1.0, 0.5, 9.0), (1.0, 3.0, 9.0), (2.5, 0.5, 9.0)]:
        d = math.sqrt(E * E - 4.0 * A * B)
        x1, x2 = math.sqrt((E - d) / (2.0 * A)), math.sqrt((E + d) / (2.0 * A))
        T = period(lambda x: A * x * x + B / (x * x), x1, x2, E, m)
        exact = math.pi * math.sqrt(m / (2.0 * A))
        yield (f"2 x2+1/x2 A={A} B={B} E={E}", abs(T - exact) < 1e-4 * exact, f"T={T:.6f} 式={exact:.6f}")
    # 3. quartic: the period depends on E
    Ts = []
    for E in (1.0, 4.0):
        xt = E ** 0.25
        Ts.append(period(lambda x: x ** 4, -xt, xt, E, m))
    yield ("3 quartic は E に依る", abs(Ts[0] - Ts[1]) > 0.1 * Ts[0], f"T(1)={Ts[0]:.6f} T(4)={Ts[1]:.6f}")
    # 4. mirror image of an asymmetric well
    V = lambda x: x * x + x ** 3 / 3.0  # minimum at 0, maximum at x = -2 (V = 4/3)
    for E in (0.2, 0.8):
        x1 = bisect(lambda x: V(x) - E, -1.9, 0.0)
        x2 = bisect(lambda x: V(x) - E, 0.0, 3.0)
        T = period(V, x1, x2, E, m)
        Tm = period(lambda x: V(-x), -x2, -x1, E, m)
        Th = period(lambda x: x * x, -math.sqrt(E), math.sqrt(E), E, m)
        ok = abs(T - Tm) < 1e-9 * T and abs(T - Th) > 1e-3 * Th  # equal to the mirror, and not the harmonic value
        yield (f"4 鏡映 E={E}", ok, f"T={T:.6f} 鏡映={Tm:.6f} (放物線だけなら {Th:.6f})")
    # 5. shifted parabola
    for k, c, V1, E in [(2.0, 0.0, 0.0, 1.0), (2.0, 1.5, -3.0, 0.5), (0.5, -4.0, 2.0, 7.0)]:
        r = math.sqrt(2.0 * (E - V1) / k)
        T = period(lambda x: k * (x - c) ** 2 / 2.0 + V1, c - r, c + r, E, m)
        exact = 2.0 * math.pi * math.sqrt(m / k)
        yield (f"5 平行移動した放物線 k={k} c={c} V1={V1} E={E}", abs(T - exact) < 1e-6 * exact,
               f"T={T:.6f} 式={exact:.6f}")
    # 6. approach to a maximum: the period keeps growing
    Ts = []
    for E in (0.9, 0.999, 0.999999):
        xt = math.acos(-E)
        Ts.append(period(lambda x: -math.cos(x), -xt, xt, E, m, n=400000))
    yield ("6 極大に近づくと周期が増え続ける", Ts[0] < Ts[1] < Ts[2] and Ts[2] > 2.0 * Ts[0],
           "T=" + ", ".join(f"{t:.4f}" for t in Ts))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true", help="run the checks quietly; exit 0 when all pass")
    args = ap.parse_args()
    failed = 0
    for label, ok, detail in checks():
        if not ok:
            failed += 1
        if not args.selftest or not ok:
            print(("PASS " if ok else "FAIL ") + label + ": " + detail)
    if args.selftest and not failed:
        print("selftest OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
