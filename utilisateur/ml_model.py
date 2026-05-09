import numpy as np
from datetime import datetime

# ── ÉTAPE 1 : RÉCUPÉRER LES DONNÉES ──────────────────────────
def collecter_donnees(connexion, id_magasin):
    curseur = connexion.cursor()

    # On récupère les ventes des 6 derniers mois avec les infos produits et stocks
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

# ── ÉTAPE 2 : ANALYSER LA FIDÉLITÉ (FRÉQUENCE) ───────────────
def analyser_comportement_clients(ventes_brutes):
    # Ce dictionnaire va stocker : "Qui a acheté quoi et combien de fois"
    suivi_clients = {}

    for ligne in ventes_brutes:
        id_c, id_p, nom_p, p_vente, p_achat, stock, qte = ligne
        
        if id_c not in suivi_clients:
            suivi_clients[id_c] = {"visites": 0, "achats": {}}
        
        # On compte une visite/commande
        suivi_clients[id_c]["visites"] += 1
        
        # On enregistre le produit et la quantité
        if id_p not in suivi_clients[id_c]["achats"]:
            suivi_clients[id_c]["achats"][id_p] = {
                "nom": nom_p, "qte_totale": 0, "prix_v": p_vente, 
                "prix_a": p_achat, "stock": stock
            }
        
        suivi_clients[id_c]["achats"][id_p]["qte_totale"] += qte

    return suivi_clients

# ── ÉTAPE 3 : PRÉDIRE LES BESOINS DU MOIS PROCHAIN ───────────
def calculer_previsions(suivi_clients):
    inventaire_previsionnel = {}

    for id_c, infos in suivi_clients.items():
        # Score de fidélité : si venu 6 fois en 6 mois = 1.0 (100% de chance de revenir)
        # Si venu 1 fois en 6 mois = 0.16 (16% de chance)
        score_fidelite = min(1.0, infos["visites"] / 6)

        for id_p, detail in infos["achats"].items():
            if id_p not in inventaire_previsionnel:
                inventaire_previsionnel[id_p] = {
                    "nom": detail["nom"],
                    "stock": detail["stock"],
                    "prix_achat": detail["prix_a"],
                    "prix_vente": detail["prix_v"],
                    "ventes_estimees": 0
                }
            
            # La prévision = (Moyenne achetée par mois) * (Probabilité de retour)
            moyenne_mensuelle = detail["qte_totale"] / 6
            inventaire_previsionnel[id_p]["ventes_estimees"] += moyenne_mensuelle * score_fidelite

    return inventaire_previsionnel

# ── ÉTAPE 4 : GÉNÉRER LE RAPPORT FINAL ───────────────────────
def generer_rapport(inventaire_previsionnel):
    liste_recommandations = []

    for id_p, p in inventaire_previsionnel.items():
        estimation = round(p["ventes_estimees"])
        stock_actuel = p["stock"]
        
        # Si on va vendre plus que ce qu'on a en stock
        if estimation > stock_actuel:
            quantite_a_commander = estimation - stock_actuel
            statut = "Commander"
            urgence = "Haute"
        else:
            quantite_a_commander = 0
            statut = "Stock OK"
            urgence = "Basse"

        liste_recommandations.append({
            "nom": p["nom"],
            "stock_actuel": stock_actuel,
            "prevision_ventes": estimation,
            "a_commander": quantite_a_commander,
            "cout_achat_estime": round(quantite_a_commander * p["prix_achat"], 2),
            "revenu_attendu": round(estimation * p["prix_vente"], 2),
            "decision": statut,
            "urgence": urgence
        })

    return liste_recommandations

# ── FONCTION PRINCIPALE (Celle que ton application appelle) ──
def executer_analyse_stock(connexion, id_magasin):
    try:
        # On enchaîne les étapes simplement
        donnees = collecter_donnees(connexion, id_magasin)
        
        if not donnees:
            return {"message": "Aucune donnée de vente disponible."}
            
        comportement = analyser_comportement_clients(donnees)
        previsions = calculer_previsions(comportement)
        resultat_final = generer_rapport(previsions)
        
        # On calcule quelques totaux pour le tableau de bord
        ca_total = sum(r["revenu_attendu"] for r in resultat_final)
        achats_total = sum(r["cout_achat_estime"] for r in resultat_final)

        return {
            "previsions": resultat_final,
            "resume": {
                "chiffre_affaires_prevu": round(ca_total, 2),
                "investissement_necessaire": round(achats_total, 2),
                "marge_estimee": round(ca_total - achats_total, 2)
            },
            "date": datetime.now().strftime("%d/%m/%Y")
        }
    except Exception as e:
        return {"erreur": str(e)}