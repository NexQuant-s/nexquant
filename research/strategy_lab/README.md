# Banc d'essai de stratégies (09/10/2026)

Compare 16 familles de stratégies classiques sur H1/H4/D1 et 29 symboles MT5, avec des règles réalistes :
signal sur bougie clôturée, entrée à l'ouverture suivante, spread réel x1,5 (+0,5 spread de glissement sur les stops),
stop >= 1 ATR (R borné), découpage apprentissage (< 2025-03-01) / test, paramètres classiques non optimisés.

    python fetch_data.py                 # historique MT5 (lecture seule)
    python lab.py all 1h,4h,1d           # classement -> out/resultats_*.csv
    python rob.py                        # robustesse du pullback D1 (classes d'actifs, tiers, voisinage de paramètres)
    python basket.py                     # panier faisable sur 900 € (indices + ETH), IC bootstrap, drawdown

Résultats et conclusions : docs/ETUDE_STRATEGIES_2026-10.md
