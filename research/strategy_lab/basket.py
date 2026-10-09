import sys, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8"); pd.set_option("display.width", 200)
sys.argv = ["x"]
import lab, rob
from rob import pullback, trades, stats, DATA
from lab import pf

BASKET = ["US500","NAS100","US30","JPN225","UK100","EUSTX50","FRA40","AUS200","ETHUSD"]
for name, kw in (("centre du plateau (pull20 sl2 trail3 adx25)", dict(pull=20, sl=2.0, trail=3.0, adx_min=25)),
                 ("adx20 (plus permissif)", dict(pull=20, sl=2.0, trail=3.0, adx_min=20))):
    d = trades(pullback(**kw)); d = d[d.sym.isin(BASKET)].copy()
    print(f"\n=== {name} — panier faisable ({len(BASKET)} symboles)\n", stats(d))
    print("par symbole PF:", {s: round(pf(g.R.clip(upper=6)), 2) for s, g in d.groupby('sym')})
    # sens : l'avantage vient-il seulement de la hausse ? (R positif des longs vs shorts)
    sig = {}
    for s in BASKET:
        df = DATA[s]; L, S_, *_ = pullback(**kw)(df, "1d")
        sig[s] = (int(L.sum()), int(S_.sum()))
    print("signaux (longs, shorts):", sum(a for a, b in sig.values()), sum(b for a, b in sig.values()))
    # portefeuille à 0,5 % de risque par trade, avec chevauchements : R réalisé à la sortie
    d["exit"] = d.t + pd.to_timedelta(d.bars, unit="D"); d = d.sort_values("exit")
    eq = 1.0; curve = []
    for r in d.R.clip(upper=6): eq *= 1 + 0.005 * r; curve.append(eq)
    c = pd.Series(curve, index=d.exit.values); dd = float((1 - c / c.cummax()).max() * 100)
    yrs = (d.exit.max() - d.t.min()).days / 365.25
    print(f"à 0,5 %/trade : rendement total {(eq-1)*100:.1f} % sur {yrs:.1f} ans ({((eq**(1/yrs))-1)*100:.1f} %/an) | drawdown max {dd:.1f} % | trades/an {len(d)/yrs:.0f}")
    daily = d.groupby(d.exit.dt.date).R.sum() * 0.5
    print(f"jours avec un résultat : {len(daily)} sur {int(yrs*252)} jours ouvrés ({len(daily)/(yrs*252)*100:.0f} %) | gain moyen les jours actifs {daily.mean():+.2f} %")
    # intervalle de confiance bootstrap de l'espérance
    rs = d.R.clip(upper=6).values; rng = np.random.default_rng(0)
    bs = [rng.choice(rs, len(rs)).mean() for _ in range(4000)]
    print(f"espérance R/trade : {rs.mean():.3f}  IC95 [{np.percentile(bs,2.5):.3f} ; {np.percentile(bs,97.5):.3f}]  P(espérance<=0)={np.mean(np.array(bs)<=0)*100:.0f} %")
