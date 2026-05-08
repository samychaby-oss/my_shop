from flask import Blueprint, jsonify, request, current_app
from psycopg2.extras import RealDictCursor

commandes_bp = Blueprint('commandes', __name__, url_prefix='/api')

def get_db():
    return current_app.get_db_connection()

# ── GET toutes les commandes ─────────────────────────────────
@commandes_bp.route('/commandes', methods=['GET'])
def get_commandes():
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT
                c.id,
                c.statut,
                c.total,
                c.adresse_livraison,
                c.created_at,
                u.nom        AS client_nom,
                u.prenom     AS client_prenom,
                u.email      AS client_email
            FROM public.commandes c
            JOIN public.utilisateurs u ON u.id = c.utilisateur_id
            ORDER BY c.created_at DESC
        ''')
        commandes = cur.fetchall()

        # Ajouter les produits de chaque commande
        result = []
        for cmd in commandes:
            cmd = dict(cmd)
            cur.execute('''
                SELECT p.nom, cp.quantite, cp.prix_unitaire
                FROM public.commande_produits cp
                JOIN public.produits p ON p.id = cp.produit_id
                WHERE cp.commande_id = %s
            ''', (cmd['id'],))
            cmd['produits'] = [dict(r) for r in cur.fetchall()]
            cmd['clientName'] = f"{cmd.pop('client_prenom')} {cmd.pop('client_nom')}"
            cmd['date'] = cmd.pop('created_at').isoformat() if cmd.get('created_at') else None
            result.append(cmd)

        cur.close(); conn.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── GET une commande ─────────────────────────────────────────
@commandes_bp.route('/commandes/<int:id>', methods=['GET'])
def get_commande(id):
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT c.*, u.nom, u.prenom, u.email
            FROM public.commandes c
            JOIN public.utilisateurs u ON u.id = c.utilisateur_id
            WHERE c.id = %s
        ''', (id,))
        commande = cur.fetchone()
        if not commande:
            return jsonify({'error': 'Commande introuvable'}), 404

        commande = dict(commande)
        cur.execute('''
            SELECT p.nom, p.image_url, cp.quantite, cp.prix_unitaire
            FROM public.commande_produits cp
            JOIN public.produits p ON p.id = cp.produit_id
            WHERE cp.commande_id = %s
        ''', (id,))
        commande['produits'] = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return jsonify(commande)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── POST créer une commande ──────────────────────────────────
@commandes_bp.route('/commandes', methods=['POST'])
def create_commande():
    try:
        data = request.get_json()
        utilisateur_id = data.get('utilisateur_id')
        produits       = data.get('produits', [])  # [{produit_id, quantite}]
        adresse        = data.get('adresse_livraison', '')

        if not utilisateur_id or not produits:
            return jsonify({'error': 'Données manquantes'}), 400

        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)

        # Calculer le total
        total = float(data.get('total', 0))

        # Créer la commande
        cur.execute('''
            INSERT INTO public.commandes (utilisateur_id, total, adresse_livraison)
            VALUES (%s, %s, %s) RETURNING id
        ''', (utilisateur_id, total, adresse))
        commande_id = cur.fetchone()['id']

        # Ajouter les produits + décrémenter le stock
        for item in produits:
            prix_unitaire = item.get('prix', 0)

            cur.execute('''
                INSERT INTO public.commande_produits (commande_id, produit_id, quantite, prix_unitaire)
                VALUES (%s, %s, %s, %s)
            ''', (commande_id, item['produit_id'], item['quantite'], prix_unitaire))

            # Décrémenter stock
            cur.execute('''
                UPDATE public.produits
                SET stock = GREATEST(stock - %s, 0)
                WHERE id = %s
            ''', (item['quantite'], item['produit_id']))

        conn.commit()
        cur.close(); conn.close()
        return jsonify({'message': 'Commande créée', 'commande_id': commande_id}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── PUT changer le statut d'une commande ─────────────────────
@commandes_bp.route('/commandes/<int:id>/statut', methods=['PUT'])
def update_statut(id):
    try:
        data   = request.get_json()
        statut = data.get('statut')
        statuts_valides = ['en_attente', 'en_cours', 'livree', 'annulee']
        if statut not in statuts_valides:
            return jsonify({'error': f'Statut invalide. Valeurs: {statuts_valides}'}), 400

        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            UPDATE public.commandes SET statut = %s
            WHERE id = %s RETURNING *
        ''', (statut, id))
        commande = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        if not commande:
            return jsonify({'error': 'Commande introuvable'}), 404
        return jsonify(dict(commande))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── GET stats pour le dashboard ──────────────────────────────
@commandes_bp.route('/stats', methods=['GET'])
def get_stats():
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)

        # CA total ce mois
        cur.execute("""
            SELECT COALESCE(SUM(total), 0) AS revenue
            FROM public.commandes
            WHERE DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW())
            AND statut != 'annulee'
        """)
        revenue = float(cur.fetchone()['revenue'])

        # Nombre de commandes ce mois
        cur.execute("""
            SELECT COUNT(*) AS orders
            FROM public.commandes
            WHERE DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW())
        """)
        orders = int(cur.fetchone()['orders'])

        # Nombre de produits actifs
        cur.execute("SELECT COUNT(*) AS products FROM public.produits WHERE actif = TRUE")
        products = int(cur.fetchone()['products'])

        # Nombre de clients
        cur.execute("SELECT COUNT(*) AS clients FROM public.utilisateurs WHERE role = 'client'")
        clients = int(cur.fetchone()['clients'])

        # Nouveaux clients ce mois
        cur.execute("""
            SELECT COUNT(*) AS new_clients FROM public.utilisateurs
            WHERE role = 'client'
            AND DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW())
        """)
        new_clients = int(cur.fetchone()['new_clients'])

        # CA par mois (6 derniers mois)
        cur.execute("""
            SELECT TO_CHAR(DATE_TRUNC('month', created_at), 'Mon') AS month,
                   COALESCE(SUM(total), 0) AS revenue
            FROM public.commandes
            WHERE created_at >= NOW() - INTERVAL '6 months'
            AND statut != 'annulee'
            GROUP BY DATE_TRUNC('month', created_at)
            ORDER BY DATE_TRUNC('month', created_at)
        """)
        revenue_by_month = [dict(r) for r in cur.fetchall()]

        # Ventes par catégorie
        cur.execute("""
            SELECT p.categorie AS name, COALESCE(SUM(cp.quantite * cp.prix_unitaire), 0) AS value
            FROM public.commande_produits cp
            JOIN public.produits p ON p.id = cp.produit_id
            GROUP BY p.categorie
            ORDER BY value DESC
        """)
        sales_by_category = [dict(r) for r in cur.fetchall()]

        cur.close(); conn.close()
        return jsonify({
            'revenue':          revenue,
            'orders':           orders,
            'products':         products,
            'clients':          clients,
            'newClients':       new_clients,
            'revenueByMonth':   revenue_by_month,
            'salesByCategory':  sales_by_category,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── GET dernières commandes pour le dashboard ────────────────
@commandes_bp.route('/stats/recent-orders', methods=['GET'])
def get_recent_orders():
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT c.id, c.statut AS status, c.total, c.created_at,
                   CONCAT(u.prenom, ' ', u.nom) AS "clientName"
            FROM public.commandes c
            JOIN public.utilisateurs u ON u.id = c.utilisateur_id
            ORDER BY c.created_at DESC
            LIMIT 5
        ''')
        rows = cur.fetchall()
        result = []
        for r in rows:
            r = dict(r)
            r['date'] = r.pop('created_at').isoformat() if r.get('created_at') else None
            result.append(r)
        cur.close(); conn.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500