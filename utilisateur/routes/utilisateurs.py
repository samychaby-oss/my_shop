from flask import Blueprint, jsonify, request, current_app, session
from psycopg2.extras import RealDictCursor
import hashlib

utilisateurs_bp = Blueprint('utilisateurs', __name__, url_prefix='/api')

def get_db():
    return current_app.get_db_connection()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ── GET tous les clients (admin) ─────────────────────────────
@utilisateurs_bp.route('/clients', methods=['GET'])
def get_clients():
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT
                u.id,
                CONCAT(u.prenom, ' ', u.nom) AS name,
                u.email,
                u.created_at,
                COUNT(c.id)           AS "ordersCount",
                COALESCE(SUM(c.total), 0) AS "totalSpent",
                MAX(c.created_at)     AS "lastOrder"
            FROM public.utilisateurs u
            LEFT JOIN public.commandes c ON c.utilisateur_id = u.id
            WHERE u.role = 'client'
            GROUP BY u.id
            ORDER BY u.created_at DESC
        ''')
        clients = cur.fetchall()
        result = []
        for c in clients:
            c = dict(c)
            c['lastOrder'] = c['lastOrder'].isoformat() if c.get('lastOrder') else None
            c['created_at'] = c['created_at'].isoformat() if c.get('created_at') else None
            result.append(c)
        cur.close(); conn.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── POST inscription ─────────────────────────────────────────
@utilisateurs_bp.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        nom    = data.get('nom', '').strip()
        prenom = data.get('prenom', '').strip()
        email  = data.get('email', '').strip().lower()
        mdp    = data.get('mot_de_passe', '')

        if not all([nom, prenom, email, mdp]):
            return jsonify({'error': 'Tous les champs sont obligatoires'}), 400

        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)

        # Vérifier si email existe déjà
        cur.execute('SELECT id FROM public.utilisateurs WHERE email = %s', (email,))
        if cur.fetchone():
            return jsonify({'error': 'Cet email est déjà utilisé'}), 409

        cur.execute('''
            INSERT INTO public.utilisateurs (nom, prenom, email, mot_de_passe, role)
            VALUES (%s, %s, %s, %s, 'client')
            RETURNING id, nom, prenom, email, role
        ''', (nom, prenom, email, hash_password(mdp)))

        user = dict(cur.fetchone())
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'message': 'Compte créé', 'user': user}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── POST connexion ───────────────────────────────────────────
@utilisateurs_bp.route('/login', methods=['POST'])
def login():
    try:
        data  = request.get_json()
        email = data.get('email', '').strip().lower()
        mdp   = data.get('mot_de_passe', '')

        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT id, nom, prenom, email, role
            FROM public.utilisateurs
            WHERE email = %s AND mot_de_passe = %s
        ''', (email, hash_password(mdp)))

        user = cur.fetchone()
        cur.close(); conn.close()

        if not user:
            return jsonify({'error': 'Email ou mot de passe incorrect'}), 401

        return jsonify({'message': 'Connexion réussie', 'user': dict(user)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── GET panier d'un utilisateur ──────────────────────────────
@utilisateurs_bp.route('/panier/<int:utilisateur_id>', methods=['GET'])
def get_panier(utilisateur_id):
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT p.id AS panier_id, pr.id, pr.nom, pr.prix, pr.image_url, p.quantite
            FROM public.panier p
            JOIN public.produits pr ON pr.id = p.produit_id
            WHERE p.utilisateur_id = %s
        ''', (utilisateur_id,))
        items = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── POST ajouter au panier ───────────────────────────────────
@utilisateurs_bp.route('/panier', methods=['POST'])
def add_to_panier():
    try:
        data           = request.get_json()
        utilisateur_id = data.get('utilisateur_id')
        produit_id     = data.get('produit_id')
        quantite       = data.get('quantite', 1)

        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            INSERT INTO public.panier (utilisateur_id, produit_id, quantite)
            VALUES (%s, %s, %s)
            ON CONFLICT (utilisateur_id, produit_id)
            DO UPDATE SET quantite = panier.quantite + EXCLUDED.quantite
            RETURNING *
        ''', (utilisateur_id, produit_id, quantite))
        item = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        return jsonify(dict(item)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── DELETE vider/retirer du panier ──────────────────────────
@utilisateurs_bp.route('/panier/<int:utilisateur_id>/<int:produit_id>', methods=['DELETE'])
def remove_from_panier(utilisateur_id, produit_id):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute('''
            DELETE FROM public.panier
            WHERE utilisateur_id = %s AND produit_id = %s
        ''', (utilisateur_id, produit_id))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'message': 'Produit retiré du panier'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500