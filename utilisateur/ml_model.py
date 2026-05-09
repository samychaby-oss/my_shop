import numpy as np
from datetime import datetime

# ── ÉTAPE 1 : RÉCUPÉRER LES DONNÉES ──────────────────────────
def collecter_donnees(connexion, id_magasin):
    curseur = connexion.cursor()
    # On récupère les ventes des 6 derniers mois
    requete = """
        SELECT 
            u.id AS id_client,
            p.id AS id_produit,
            p.nom AS nom_produit,
            pm.prix AS prix_vente,
            pm.prix_achat AS prix_achat,
            pm.stock AS stock_actuel,
            cp.quantite AS qte_achetee
        FROM public.commandes c
        JOIN public.utilisateurs u ON u.id = c.utilisateur_id
        JOIN public.commande_produits cp ON cp.commande_id = c.id
        JOIN public.produits p ON p.id = cp.produit_id
        JOIN public.prix_magasins pm ON pm.produit_id = p.id
        WHERE pm.magasin_id = %s
          AND c.statut != 'annulee'
          AND c.created_at >= NOW() - INTERVAL '6 months'
    """
    curseur.execute(requete, (id_magasin,))
    ventes_brutes = curseur.fetchall()
    curseur.close()
    return ventes_brutes

# ── ÉTAPE 2 : ANALYSER LE COMPORTEMENT ───────────────────────
def analyser_comportement_clients(ventes_brutes):
    suivi_clients = {}
    for ligne in ventes_brutes:
        id_c, id_p, nom_p, p_vente, p_achat, stock, qte = ligne
        if id_c not in suivi_clients:
            suivi_clients[id_c] = {"visites": 0, "achats": {}}
        suivi_clients[id_c]["visites"] += 1
        if id_p not in suivi_clients[id_c]["achats"]:
            suivi_clients[id_c]["achats"][id_p] = {
                "nom": nom_p, "qte_totale": 0, "prix_v": p_vente, 
                "prix_a": p_achat, "stock": stock
            }
        suivi_clients[id_c]["achats"][id_p]["qte_totale"] += qte
    return suivi_clients

# ── ÉTAPE 3 : CALCULER LES PRÉVISIONS ────────────────────────
def calculer_previsions_internes(suivi_clients):
    inventaire_previsionnel = {}
    for id_c, infos in suivi_clients.items():
        # Plus un client est venu souvent en 6 mois, plus sa probabilité est haute
        score_fidelite = min(1.0, infos["visites"] / 6)
        for id_p, detail in infos["achats"].items():
            if id_p not in inventaire_previsionnel:
                inventaire_previsionnel[id_p] = {
                    "nom": detail["nom"], "stock": detail["stock"],
                    "prix_achat": detail["prix_a"], "prix_vente": detail["prix_v"],
                    "ventes_estimees": 0
                }
            moyenne_mensuelle = detail["qte_totale"] / 6
            inventaire_previsionnel[id_p]["ventes_estimees"] += moyenne_mensuelle * score_fidelite
    return inventaire_previsionnel

# ── ÉTAPE 4 : LA FONCTION PRINCIPALE (Celle que Render appelle) ──
def generer_previsions(conn, magasin_id):
    try:
        # 1. Récupération
        donnees = collecter_donnees(conn, magasin_id)
        if not donnees:
            return {"previsions": [], "analyse": {}, "message": "Aucune donnée trouvée."}
            
        # 2. Analyse et Calculs
        comportement = analyser_comportement_clients(donnees)
        previsions_brutes = calculer_previsions_internes(comportement)
        
        # 3. Formatage pour le tableau de l'image
        liste_finale = []
        for id_p, p in previsions_brutes.items():
            estimation = int(round(p["ventes_estimees"]))
            stock_actuel = p["stock"]
            a_commander = max(0, estimation - stock_actuel)
            
            liste_finale.append({
                "produit_id": id_p,
                "nom": p["nom"],
                "stock_actuel": stock_actuel,
                "prevision": estimation,     # S'affiche dans 'PRÉVISION VENTES'
                "a_commander": a_commander,   # S'affiche dans 'À COMMANDER'
                "prix_achat": p["prix_achat"],
                "cout_achat": round(a_commander * p["prix_achat"], 2),
                "revenu_prevu": round(estimation * p["prix_vente"], 2),
                "recommandation": "Commander" if a_commander > 0 else "OK",
                "urgence": "Haute" if a_commander > 0 else "Basse"
            })

        # 4. Résumé pour les compteurs (CA, Marge, etc.)
        ca_prevu = sum(item["revenu_prevu"] for item in liste_finale)
        cout_achat = sum(item["cout_achat"] for item in liste_finale)

        return {
            "previsions": liste_finale,
            "analyse": {
                "prevision_ca_mois_prochain": round(ca_prevu, 2),
                "cout_achat_total": round(cout_achat, 2),
                "marge_prevue": round(ca_prevu - cout_achat, 2),
                "nb_produits_commander": len([i for i in liste_finale if i["a_commander"] > 0]),
                "nb_produits_ok": len([i for i in liste_finale if i["a_commander"] == 0])
            },
            "message": f"Analyse réussie pour le magasin {magasin_id}",
            "genere_le": datetime.now().strftime("%d/%m/%Y à %H:%M")
        }
    except Exception as e:
        return {"previsions": [], "analyse": {}, "message": f"Erreur critique: {str(e)}"}