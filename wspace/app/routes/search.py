from flask import Blueprint, render_template, request, jsonify
from app.services.search_service import search_notes

bp = Blueprint('search', __name__, url_prefix='/search')


@bp.route('/')
def search():
    """Full-text search across notes."""
    query = request.args.get('q', '').strip()
    if not query:
        if request.headers.get('HX-Request'):
            return render_template('partials/search_results.html', results=[], query='')
        return jsonify([])

    results = search_notes(query)

    if request.headers.get('HX-Request'):
        return render_template('partials/search_results.html', results=results, query=query)
    return jsonify(results)
