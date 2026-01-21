from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from app import db
from app.models import Tag, Note

bp = Blueprint('tags', __name__, url_prefix='/tags')


@bp.route('/')
def list_tags():
    """List all tags."""
    tags = Tag.query.order_by(Tag.name).all()
    if request.headers.get('HX-Request'):
        return render_template('partials/tag_list.html', tags=tags)
    return jsonify([t.to_dict() for t in tags])


@bp.route('/new', methods=['POST'])
def create_tag():
    """Create a new tag."""
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Tag name required'}), 400

    existing = Tag.query.filter_by(name=name).first()
    if existing:
        return jsonify(existing.to_dict()), 200

    tag = Tag(name=name)
    db.session.add(tag)
    db.session.commit()

    if request.headers.get('HX-Request'):
        tags = Tag.query.order_by(Tag.name).all()
        return render_template('partials/tag_list.html', tags=tags)
    return jsonify(tag.to_dict()), 201


@bp.route('/<int:tag_id>/rename', methods=['POST'])
def rename_tag(tag_id):
    """Rename a tag."""
    tag = Tag.query.get_or_404(tag_id)
    new_name = request.form.get('name', '').strip()
    if not new_name:
        return jsonify({'error': 'Tag name required'}), 400

    tag.name = new_name
    db.session.commit()

    if request.headers.get('HX-Request'):
        tags = Tag.query.order_by(Tag.name).all()
        return render_template('partials/tag_list.html', tags=tags)
    return jsonify(tag.to_dict())


@bp.route('/<int:tag_id>/delete', methods=['POST'])
def delete_tag(tag_id):
    """Delete a tag."""
    tag = Tag.query.get_or_404(tag_id)
    db.session.delete(tag)
    db.session.commit()

    if request.headers.get('HX-Request'):
        tags = Tag.query.order_by(Tag.name).all()
        return render_template('partials/tag_list.html', tags=tags)
    return '', 204


@bp.route('/search')
def search_tags():
    """Search tags by name (for autocomplete)."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])

    tags = Tag.query.filter(Tag.name.ilike(f'%{query}%')).limit(10).all()
    return jsonify([t.to_dict() for t in tags])
