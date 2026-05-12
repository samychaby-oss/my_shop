import numpy as np
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
import warnings
warnings.filterwarnings('ignore')


# ── ÉTAPE 1 : Collecter les données ──────────────────────────
def collecter(conn, magasin_id):
    cur = conn.cursor()

    cur.execute("SELECT nom FROM public.magasins WHERE id = %s", (magasin_id,))
    nom_magasin = cur.fetchone()[0]

    cur.execute("""
        SELECT
            u.id, u.prenom || ' ' || u.nom,
            p.id, p.nom, pm.prix, pm.prix_achat, pm.stock,
            COALESCE(p.seuil_alerte, 10),
            COUNT(DISTINCT c.id), COALESCE(AVG(cp.quantite), 0)
        FROM public.commandes c
        JOIN public.utilisateurs u       ON u.id = c.utilisateur_id
        JOIN public.commande_produits cp ON cp.commande_id = c.id
        JOIN public.produits p           ON p.id = cp.produit_id
        JOIN public.prix_magasins pm     ON pm.produit_id = p.id AND pm.magasin_id = %s
        WHERE c.adresse_livraison LIKE %s
          AND c.created_at >= NOW() - INTERVAL '6 months'
          AND c.statut != 'annulee'
          AND pm.magasin_id = %s
        GROUP BY u.id, u.prenom, u.nom, p.id, p.nom, pm.prix, pm.prix_achat, pm.stock, p.seuil_alerte
        ORDER BY p.id, COUNT(DISTINCT c.id) DESC
    """, (magasin_id, f'%{nom_magasin}%', magasin_id))
    ventes = cur.fetchall()

    cur.execute("""
        SELECT DATE_TRUNC('month', MIN(c.created_at)) AS mois, COUNT(*) AS nb
        FROM public.commandes c
        WHERE c.adresse_livraison LIKE %s AND c.statut != 'annulee'
        GROUP BY c.utilisateur_id
        HAVING MIN(c.created_at) >= NOW() - INTERVAL '6 months'
        ORDER BY mois
    """, (f'%{nom_magasin}%',))
    nouveaux_par_mois = cur.fetchall()

    cur.close()
    return ventes, nouveaux_par_mois


# ── ÉTAPE 2 : Classer les clients ────────────────────────────
def classer_clients(ventes, nb_mois=6):
    clients = {}
    for row in ventes:
        cid = row[0]
        if cid not in clients:
            clients[cid] = {'nom': row[1], 'nb_commandes': int(row[8]), 'produits': {}}
        pid = row[2]
        clients[cid]['produits'][pid] = {
            'nom': row[3], 'prix_vente': float(row[4] or 0),
            'prix_achat': float(row[5] or 0), 'stock': int(row[6] or 0),
            'seuil': int(row[7] or 10), 'qte_moyenne': int(round(float(row[9] or 0))),
        }

    for cid, c in clients.items():
        frequence = c['nb_commandes'] / nb_mois
        if frequence >= 1.0:   prob = min(95, 90 + int((frequence - 1) * 10))
        elif frequence >= 0.7: prob = int(70 + (frequence - 0.7) * 66)
        elif frequence >= 0.4: prob = int(40 + (frequence - 0.4) * 100)
        elif frequence >= 0.2: prob = int(20 + (frequence - 0.2) * 100)
        else:                  prob = max(5, int(frequence * 100))
        c['probabilite'] = prob

    return clients


# ── ÉTAPE 3 : Prédire les nouveaux clients + calcul erreurs ──
def predire_nouveaux_clients(nouveaux_par_mois):
    if len(nouveaux_par_mois) < 2:
        return int(np.mean([int(r[1]) for r in nouveaux_par_mois])) if nouveaux_par_mois else 1

    valeurs = np.array([int(r[1]) for r in nouveaux_par_mois], dtype=float)
    X       = np.arange(len(valeurs)).reshape(-1, 1)

    # ── Train / Test split 80% / 20% ─────────────────────────
    split   = max(1, int(len(valeurs) * 0.8))  # 5 mois train, 1 mois test
    X_train = X[:split]
    X_test  = X[split:]
    y_train = valeurs[:split]
    y_test  = valeurs[split:]

    # ── Compétition LinearRegression vs Ridge ─────────────────
    lr    = LinearRegression().fit(X_train, y_train)
    ridge = Ridge(alpha=1.0).fit(X_train, y_train)

    score_lr    = r2_score(y_train, lr.predict(X_train))
    score_ridge = r2_score(y_train, ridge.predict(X_train))

    if score_ridge >= score_lr:
        modele, gagnant = ridge, 'Ridge'
    else:
        modele, gagnant = lr, 'LinearRegression'

    print(f"    Compétition — LinearRegression R²={round(score_lr,3)} | Ridge R²={round(score_ridge,3)}")
    print(f"    Gagnant : {gagnant}")

    # ── Calcul des erreurs sur données de test ────────────────
    if len(y_test) > 0:
        y_pred  = modele.predict(X_test)
        rmse    = round(float(np.sqrt(mean_squared_error(y_test, y_pred))), 3)
        mae     = round(float(mean_absolute_error(y_test, y_pred)), 3)
        print(f"    Erreurs sur données test :")
        print(f"      RMSE = {rmse}  → le modèle se trompe en moyenne de {rmse} clients")
        print(f"      MAE  = {mae}   → écart absolu moyen = {mae} clients")
        print(f"      Note : calculé sur {len(y_test)} point(s) de test seulement")
    else:
        print("    Pas assez de données pour calculer les erreurs.")

    # ── Prédiction mois prochain ──────────────────────────────
    nb_prevu = max(1, round(float(modele.predict([[len(valeurs)]])[0])))
    print(f"    Nouveaux clients prévus : {nb_prevu}")

    return int(nb_prevu)


# ── ÉTAPE 4 : Prédire les ventes par produit ─────────────────
def predire_ventes(clients, nb_nouveaux):
    produits = {}

    for cid, c in clients.items():
        for pid, p in c['produits'].items():
            if pid not in produits:
                produits[pid] = {
                    'nom': p['nom'], 'prix_vente': p['prix_vente'],
                    'prix_achat': p['prix_achat'], 'stock': p['stock'],
                    'seuil': p['seuil'], 'prevision': 0,
                }
            contribution = p['qte_moyenne'] * (c['probabilite'] / 100)
            produits[pid]['prevision'] += contribution

    # Panier moyen réel = 1.83 produits par commande (calculé depuis la base)
    PANIER_MOYEN = 1.83
    if produits:
        for pid in produits:
            produits[pid]['prevision'] += (nb_nouveaux * PANIER_MOYEN) / len(produits)

    for pid in produits:
        produits[pid]['prevision'] = max(0, int(round(produits[pid]['prevision'])))

    return produits


# ── ÉTAPE 5 : Recommandation par produit ─────────────────────
def recommander(produits):
    resultats = []

    for pid, p in produits.items():
        prevision    = p['prevision']
        stock        = p['stock']
        seuil        = p['seuil']
        a_commander  = max(0, prevision - stock)
        cout_achat   = round(a_commander * p['prix_achat'], 2)
        revenu_prevu = round(prevision   * p['prix_vente'], 2)

        if stock == 0 and prevision > 0:
            rec, urg, qte = 'commander_urgent', 'critique', prevision + seuil
        elif a_commander > seuil:
            rec, urg, qte = 'commander', 'haute', a_commander + seuil
        elif a_commander > 0:
            rec, urg, qte = 'commander', 'normale', a_commander
        elif stock > prevision * 3 and prevision > 0:
            rec, urg, qte = 'reduire', 'faible', 0
        else:
            rec, urg, qte = 'ok', 'faible', 0

        resultats.append({
            'produit_id': pid, 'nom': p['nom'],
            'prix_actuel': p['prix_vente'], 'prix_achat': p['prix_achat'],
            'stock_actuel': stock, 'prevision': prevision,
            'a_commander': int(qte), 'cout_achat': cout_achat,
            'revenu_prevu': revenu_prevu, 'recommandation': rec, 'urgence': urg,
        })

    ordre = {'critique': 0, 'haute': 1, 'normale': 2, 'faible': 3}
    resultats.sort(key=lambda x: ordre.get(x['urgence'], 4))
    return resultats


# ── Fonction principale appelée par Flask ─────────────────────
def generer_previsions(conn, magasin_id):
    try:
        print("\n--- Collecte des données ---")
        ventes, nouveaux_par_mois = collecter(conn, magasin_id)
        if not ventes:
            return {'previsions': [], 'analyse': {}, 'message': 'Pas de données.'}
        print(f"    {len(ventes)} lignes récupérées")

        print("\n--- Classement des clients ---")
        clients = classer_clients(ventes)
        print(f"    {len(clients)} clients analysés")

        print("\n--- Prédiction nouveaux clients + calcul erreurs ---")
        nb_nouveaux = predire_nouveaux_clients(nouveaux_par_mois)

        print("\n--- Prévision des ventes par produit ---")
        produits   = predire_ventes(clients, nb_nouveaux)
        previsions = recommander(produits)

        ca_prevu   = round(sum(p['revenu_prevu'] for p in previsions), 2)
        cout_total = round(sum(p['cout_achat']   for p in previsions), 2)

        print(f"    CA prévu : {ca_prevu} €")

        return {
            'previsions': previsions,
            'analyse': {
                'prevision_ca_mois_prochain': ca_prevu,
                'cout_achat_total':           cout_total,
                'marge_prevue':               round(ca_prevu - cout_total, 2),
                'nb_produits_commander':      len([p for p in previsions if 'commander' in p['recommandation']]),
                'nb_produits_ok':             len([p for p in previsions if p['recommandation'] == 'ok']),
            },
            'message':   f"Modèle entraîné sur {len(clients)} clients.",
            'genere_le': datetime.now().strftime('%d/%m/%Y à %H:%M'),
        }
    except Exception as e:
        return {'previsions': [], 'analyse': {}, 'message': f'Erreur: {str(e)}'}