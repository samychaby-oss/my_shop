from flask import Blueprint, jsonify, current_app, request
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import re

previsions_bp = Blueprint('previsions', __name__, url_prefix='/api')

def get_db():
    return current_app.get_db_connection()

def get_magasin_nom(cur, magasin_id):
    cur.execute("SELECT nom FROM public.magasins WHERE id = %s", (magasin_id,))
    row = cur.fetchone()
    return row['nom'] if row else ''


# ── 1. Prévisions Produits (ML) ──────────────────────────────
@previsions_bp.route('/previsions/<int:magasin_id>', methods=['GET'])
def get_previsions(magasin_id):
    try:
        from ml_model import generer_previsions
        conn = get_db()
        data = generer_previsions(conn, magasin_id)
        conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e), 'previsions': [], 'analyse': {}}), 500


# ── 2. Prévisions Clients (ML) ───────────────────────────────
@previsions_bp.route('/clients-previsions/<int:magasin_id>', methods=['GET'])
def get_clients_previsions(magasin_id):
    try:
        from ml_model import previsions_clients
        periode = request.args.get('periode', '6mois')

        intervalles = {
            'semaine': ('7 days',   7 / 30),
            'mois':    ('1 month',  1),
            '3mois':   ('3 months', 3),
            '6mois':   ('6 months', 6),
        }
        intervalle, nb_mois = intervalles.get(periode, ('6 months', 6))

        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        nom  = get_magasin_nom(cur, magasin_id)

        cur.execute(f"""
            SELECT u.id AS utilisateur_id, u.nom, u.prenom,
                   COUNT(DISTINCT c.id) AS nb_commandes
            FROM public.commandes c
            JOIN public.utilisateurs u ON u.id = c.utilisateur_id
            WHERE c.adresse_livraison LIKE %s
              AND c.created_at >= NOW() - INTERVAL '{intervalle}'
              AND c.statut != 'annulee'
            GROUP BY u.id, u.nom, u.prenom
            ORDER BY nb_commandes DESC
        """, (f'%{nom}%',))
        clients_data = [dict(r) for r in cur.fetchall()]
        nb_clients   = len(clients_data)
        cur.close()
        conn.close()

        resultats    = previsions_clients(clients_data, nb_mois)
        retour_prob  = [r for r in resultats if r['probabilite'] >= 60]
        tres_fideles = [r for r in resultats if r['statut'] == 'Très fidèle']
        a_risque     = [r for r in resultats if r['statut'] == 'À risque']

        return jsonify({
            'clients': resultats,
            'analyse': {
                'nb_clients_actifs':  nb_clients,
                'nb_retour_probable': len(retour_prob),
                'nb_tres_fideles':    len(tres_fideles),
                'nb_a_risque':        len(a_risque),
            },
            'periode':    periode,
            'magasin_id': magasin_id,
            'genere_le':  datetime.now().strftime('%d/%m/%Y à %H:%M'),
        })
    except Exception as e:
        return jsonify({'error': str(e), 'clients': [], 'analyse': {}}), 500


# ── 3. Heures de pointe par jour (ML) ───────────────────────
@previsions_bp.route('/heures-pointe-jour/<int:magasin_id>', methods=['GET'])
def get_heures_pointe_jour(magasin_id):
    try:
        from ml_model import heures_pointe_par_jour
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        nom  = get_magasin_nom(cur, magasin_id)

        cur.execute("""
            SELECT adresse_livraison, created_at
            FROM public.commandes
            WHERE adresse_livraison LIKE %s
              AND created_at >= NOW() - INTERVAL '6 months'
              AND statut != 'annulee'
        """, (f'%{nom}%',))
        commandes = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()

        resultats = heures_pointe_par_jour(commandes)
        return jsonify({
            'jours':      resultats,
            'magasin_id': magasin_id,
            'basé_sur':   f'{len(commandes)} commandes sur 6 mois',
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── 4. Analyses — CA jour / mois / graphiques (SQL) ─────────
@previsions_bp.route('/analyses/<int:magasin_id>', methods=['GET'])
def get_analyses(magasin_id):
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        nom  = get_magasin_nom(cur, magasin_id)

        def fetch_ca(where):
            cur.execute(f"SELECT COALESCE(SUM(total), 0) AS ca FROM public.commandes WHERE adresse_livraison LIKE %s AND statut != 'annulee' AND {where}", (f'%{nom}%',))
            return float(cur.fetchone()['ca'])

        def fetch_nb(where):
            cur.execute(f"SELECT COUNT(*) AS nb FROM public.commandes WHERE adresse_livraison LIKE %s AND {where}", (f'%{nom}%',))
            return int(cur.fetchone()['nb'])

        ca_jour      = fetch_ca("DATE(created_at) = CURRENT_DATE")
        ca_hier      = fetch_ca("DATE(created_at) = CURRENT_DATE - INTERVAL '1 day'")
        ca_mois      = fetch_ca("DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW())")
        ca_mois_prec = fetch_ca("DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW() - INTERVAL '1 month')")
        nb_jour      = fetch_nb("DATE(created_at) = CURRENT_DATE")
        nb_hier      = fetch_nb("DATE(created_at) = CURRENT_DATE - INTERVAL '1 day'")

        # Top 3 produits ce mois
        cur.execute("""
            SELECT p.nom, SUM(cp.quantite) AS total
            FROM public.commande_produits cp
            JOIN public.produits p  ON p.id  = cp.produit_id
            JOIN public.commandes c ON c.id  = cp.commande_id
            WHERE c.adresse_livraison LIKE %s
              AND DATE_TRUNC('month', c.created_at) = DATE_TRUNC('month', NOW())
              AND c.statut != 'annulee'
            GROUP BY p.nom ORDER BY total DESC LIMIT 3
        """, (f'%{nom}%',))
        top_produits = [{'nom': r['nom'], 'total': int(r['total'])} for r in cur.fetchall()]

        # CA par mois sur 6 mois
        cur.execute("""
            SELECT TO_CHAR(DATE_TRUNC('month', created_at), 'Mon YYYY') AS mois,
                   COALESCE(SUM(total), 0) AS ca
            FROM public.commandes
            WHERE adresse_livraison LIKE %s
              AND created_at >= NOW() - INTERVAL '6 months'
              AND statut != 'annulee'
            GROUP BY DATE_TRUNC('month', created_at)
            ORDER BY DATE_TRUNC('month', created_at)
        """, (f'%{nom}%',))
        ca_par_mois = [{'mois': r['mois'], 'ca': float(r['ca'])} for r in cur.fetchall()]

        # CA par jour sur 7 derniers jours
        cur.execute("""
            SELECT TO_CHAR(DATE(created_at), 'DD/MM') AS jour,
                   COALESCE(SUM(total), 0) AS ca
            FROM public.commandes
            WHERE adresse_livraison LIKE %s
              AND created_at >= NOW() - INTERVAL '7 days'
              AND statut != 'annulee'
            GROUP BY DATE(created_at)
            ORDER BY DATE(created_at)
        """, (f'%{nom}%',))
        ca_par_semaine = [{'jour': r['jour'], 'ca': float(r['ca'])} for r in cur.fetchall()]

        cur.close()
        conn.close()
        return jsonify({
            'ca_jour':       ca_jour,
            'ca_hier':       ca_hier,
            'ca_mois':       ca_mois,
            'ca_mois_prec':  ca_mois_prec,
            'nb_jour':       nb_jour,
            'nb_hier':       nb_hier,
            'top_produits':  top_produits,
            'ca_par_mois':   ca_par_mois,
            'ca_par_semaine':ca_par_semaine,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── 5. Heures de pointe globales (SQL) ──────────────────────
@previsions_bp.route('/heures-pointe/<int:magasin_id>', methods=['GET'])
def get_heures_pointe(magasin_id):
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        nom  = get_magasin_nom(cur, magasin_id)

        cur.execute("""
            SELECT adresse_livraison FROM public.commandes
            WHERE adresse_livraison LIKE %s
              AND created_at >= NOW() - INTERVAL '6 months'
              AND statut != 'annulee'
        """, (f'%{nom}%',))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        heure_count = {h: 0 for h in range(9, 19)}
        for row in rows:
            match = re.search(r'(\d{2}):\d{2}', row['adresse_livraison'] or '')
            if match:
                h = int(match.group(1))
                if 9 <= h <= 18:
                    heure_count[h] += 1

        pic = max(heure_count, key=heure_count.get) if any(heure_count.values()) else 12
        return jsonify({
            'heures':       [{'heure': f'{h}h', 'nb': heure_count[h], 'is_pic': h == pic} for h in range(9, 19)],
            'heure_pointe': pic,
            'message':      f'Pic de commandes à {pic}h — soyez prêts !',
            'basé_sur':     f'{len(rows)} commandes sur 6 mois',
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── 6. Mur des commandes ─────────────────────────────────────
@previsions_bp.route('/mur-commandes/<int:magasin_id>', methods=['GET'])
def get_mur_commandes(magasin_id):
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        nom  = get_magasin_nom(cur, magasin_id)

        cur.execute("""
            SELECT DISTINCT c.id, c.statut, c.total, c.adresse_livraison, c.created_at,
                   CONCAT(u.prenom, ' ', u.nom) AS "clientName"
            FROM public.commandes c
            JOIN public.utilisateurs u ON u.id = c.utilisateur_id
            WHERE c.adresse_livraison LIKE %s
              AND c.statut IN ('en_attente', 'en_cours', 'livree')
              AND DATE(c.created_at) = CURRENT_DATE
            ORDER BY c.created_at ASC
        """, (f'%{nom}%',))

        commandes = []
        for row in cur.fetchall():
            cmd = dict(row)
            cmd['date'] = cmd['created_at'].isoformat() if cmd.get('created_at') else None
            cur.execute("""
                SELECT p.nom, cp.quantite, cp.prix_unitaire
                FROM public.commande_produits cp
                JOIN public.produits p ON p.id = cp.produit_id
                WHERE cp.commande_id = %s
            """, (cmd['id'],))
            cmd['produits'] = [dict(r) for r in cur.fetchall()]
            commandes.append(cmd)

        cur.close()
        conn.close()
        return jsonify(commandes)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── 7. Changer statut commande ───────────────────────────────
@previsions_bp.route('/mur-commandes/<int:commande_id>/statut', methods=['PUT'])
def update_mur_statut(commande_id):
    try:
        statut = request.get_json().get('statut')
        conn   = get_db()
        cur    = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("UPDATE public.commandes SET statut = %s WHERE id = %s RETURNING id, statut",
                    (statut, commande_id))
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(dict(result))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── 8. Historique commandes ──────────────────────────────────
@previsions_bp.route('/commandes/magasin/<int:magasin_id>', methods=['GET'])
def get_commandes_magasin(magasin_id):
    try:
        limit = int(request.args.get('limit', 200))
        conn  = get_db()
        cur   = conn.cursor(cursor_factory=RealDictCursor)
        nom   = get_magasin_nom(cur, magasin_id)

        cur.execute("""
            SELECT DISTINCT c.id, c.statut, c.total, c.adresse_livraison, c.created_at,
                   CONCAT(u.prenom, ' ', u.nom) AS "clientName"
            FROM public.commandes c
            JOIN public.utilisateurs u ON u.id = c.utilisateur_id
            WHERE c.adresse_livraison LIKE %s
            ORDER BY c.created_at DESC LIMIT %s
        """, (f'%{nom}%', limit))

        commandes = []
        for row in cur.fetchall():
            cmd = dict(row)
            cmd['date'] = cmd['created_at'].isoformat() if cmd.get('created_at') else None
            cur.execute("""
                SELECT p.nom, cp.quantite, cp.prix_unitaire
                FROM public.commande_produits cp
                JOIN public.produits p ON p.id = cp.produit_id
                WHERE cp.commande_id = %s
            """, (cmd['id'],))
            cmd['produits'] = [dict(r) for r in cur.fetchall()]
            commandes.append(cmd)

        cur.close()
        conn.close()
        return jsonify(commandes)
    except Exception as e:
        return jsonify({'error': str(e)}), 500