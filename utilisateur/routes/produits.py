from flask import Blueprint, jsonify, request, current_app

produits_bp = Blueprint('produits', __name__, url_prefix='/api')

def get_db():
    return current_app.get_db_connection()

# ── GET tous les produits ────────────────────────────────────
@produits_bp.route('/produits', methods=['GET'])
def get_produits():
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=__import__('psycopg2.extras', fromlist=['RealDictCursor']).RealDictCursor)
        cur.execute('SELECT * FROM public.produits ORDER BY id ASC')
        produits = cur.fetchall()
        cur.close(); conn.close()
        return jsonify(list(produits))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── GET un produit par id ────────────────────────────────────
@produits_bp.route('/produits/<int:id>', methods=['GET'])
def get_produit(id):
    try:
        from psycopg2.extras import RealDictCursor
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM public.produits WHERE id = %s', (id,))
        produit = cur.fetchone()
        cur.close(); conn.close()
        if not produit:
            return jsonify({'error': 'Produit introuvable'}), 404
        return jsonify(dict(produit))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── POST créer un produit ────────────────────────────────────
@produits_bp.route('/produits', methods=['POST'])
def create_produit():
    try:
        data = request.get_json()
        conn = get_db()
        cur  = conn.cursor(cursor_factory=__import__('psycopg2.extras', fromlist=['RealDictCursor']).RealDictCursor)
        cur.execute('''
            INSERT INTO public.produits
                (nom, description, categorie, prix, stock, seuil_alerte, code_barres, image_url, nutriscore)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        ''', (
            data.get('nom'),
            data.get('description'),
            data.get('categorie'),
            data.get('prix', 0),
            data.get('stock', 0),
            data.get('seuil_alerte', 10),
            data.get('code_barres'),
            data.get('image_url'),
            data.get('nutriscore'),
        ))
        produit = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        return jsonify(dict(produit)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── PUT modifier un produit ──────────────────────────────────
@produits_bp.route('/produits/<int:id>', methods=['PUT'])
def update_produit(id):
    try:
        from psycopg2.extras import RealDictCursor
        data = request.get_json()
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            UPDATE public.produits SET
                nom          = COALESCE(%s, nom),
                description  = COALESCE(%s, description),
                categorie    = COALESCE(%s, categorie),
                prix         = COALESCE(%s, prix),
                stock        = COALESCE(%s, stock),
                seuil_alerte = COALESCE(%s, seuil_alerte),
                image_url    = COALESCE(%s, image_url),
                nutriscore   = COALESCE(%s, nutriscore),
                actif        = COALESCE(%s, actif)
            WHERE id = %s
            RETURNING *
        ''', (
            data.get('nom'),
            data.get('description'),
            data.get('categorie'),
            data.get('prix'),
            data.get('stock'),
            data.get('seuil_alerte'),
            data.get('image_url'),
            data.get('nutriscore'),
            data.get('actif'),
            id,
        ))
        produit = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        if not produit:
            return jsonify({'error': 'Produit introuvable'}), 404
        return jsonify(dict(produit))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── DELETE supprimer un produit ──────────────────────────────
@produits_bp.route('/produits/<int:id>', methods=['DELETE'])
def delete_produit(id):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute('DELETE FROM public.produits WHERE id = %s', (id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'message': 'Produit supprimé'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500





@produits_bp.route('/magasins', methods=['GET'])
def get_magasins():
    try:
        from psycopg2.extras import RealDictCursor
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM public.magasins WHERE actif = TRUE ORDER BY nom')
        magasins = cur.fetchall()
        cur.close(); conn.close()
        return jsonify(list(magasins))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produits_bp.route('/produits/magasin/<int:magasin_id>', methods=['GET'])
def get_produits_magasin(magasin_id):
    try:
        from psycopg2.extras import RealDictCursor
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT p.*, pm.prix AS prix, pm.stock AS stock
            FROM public.produits p
            JOIN public.prix_magasins pm ON pm.produit_id = p.id
            WHERE pm.magasin_id = %s AND p.actif = TRUE
            ORDER BY p.nom
        ''', (magasin_id,))
        produits = cur.fetchall()
        cur.close(); conn.close()
        return jsonify(list(produits))
    except Exception as e:
        return jsonify({'error': str(e)}), 500