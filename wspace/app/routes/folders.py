from flask import Blueprint, render_template, request, redirect, url_for, jsonify, g
from app import db
from app.models import Folder, Note
from app.routes.auth import login_required, get_current_user

bp = Blueprint('folders', __name__, url_prefix='/folders')


@bp.before_request
def load_user():
    """Load current user before each request."""
    g.user = get_current_user()


@bp.route('/')
@login_required
def list_folders():
    """List all folders in tree structure."""
    folders = Folder.query.filter_by(user_id=g.user.id, parent_id=None).all()
    if request.headers.get('HX-Request'):
        return render_template('partials/folder_tree.html', folders=folders)
    return jsonify([f.to_dict() for f in folders])


@bp.route('/new', methods=['POST'])
@login_required
def create_folder():
    """Create a new folder."""
    name = request.form.get('name', 'New Folder')
    parent_id = request.form.get('parent_id', type=int)

    folder = Folder(name=name, parent_id=parent_id, user_id=g.user.id)
    db.session.add(folder)
    db.session.commit()

    if request.headers.get('HX-Request'):
        folders = Folder.query.filter_by(user_id=g.user.id, parent_id=None).all()
        return render_template('partials/folder_tree.html', folders=folders)
    return jsonify(folder.to_dict()), 201


@bp.route('/<int:folder_id>', methods=['GET'])
@login_required
def get_folder(folder_id):
    """Get folder details."""
    folder = Folder.query.filter_by(id=folder_id, user_id=g.user.id).first_or_404()
    return jsonify(folder.to_dict())


@bp.route('/<int:folder_id>/rename', methods=['POST'])
@login_required
def rename_folder(folder_id):
    """Rename a folder."""
    folder = Folder.query.filter_by(id=folder_id, user_id=g.user.id).first_or_404()
    folder.name = request.form.get('name', folder.name)
    db.session.commit()

    if request.headers.get('HX-Request'):
        folders = Folder.query.filter_by(user_id=g.user.id, parent_id=None).all()
        return render_template('partials/folder_tree.html', folders=folders)
    return jsonify(folder.to_dict())


@bp.route('/<int:folder_id>/move', methods=['POST'])
@login_required
def move_folder(folder_id):
    """Move folder to a new parent."""
    folder = Folder.query.filter_by(id=folder_id, user_id=g.user.id).first_or_404()
    new_parent_id = request.form.get('parent_id', type=int)

    # Prevent moving folder into itself or its descendants
    if new_parent_id:
        current = Folder.query.filter_by(id=new_parent_id, user_id=g.user.id).first()
        while current:
            if current.id == folder_id:
                return jsonify({'error': 'Cannot move folder into itself'}), 400
            current = current.parent

    folder.parent_id = new_parent_id
    db.session.commit()

    if request.headers.get('HX-Request'):
        folders = Folder.query.filter_by(user_id=g.user.id, parent_id=None).all()
        return render_template('partials/folder_tree.html', folders=folders)
    return jsonify(folder.to_dict())


@bp.route('/<int:folder_id>/delete', methods=['POST'])
@login_required
def delete_folder(folder_id):
    """Delete a folder (moves notes to root)."""
    folder = Folder.query.filter_by(id=folder_id, user_id=g.user.id).first_or_404()

    # Move notes to root
    Note.query.filter_by(folder_id=folder_id, user_id=g.user.id).update({'folder_id': None})

    # Move subfolders to parent
    Folder.query.filter_by(parent_id=folder_id, user_id=g.user.id).update({'parent_id': folder.parent_id})

    db.session.delete(folder)
    db.session.commit()

    if request.headers.get('HX-Request'):
        folders = Folder.query.filter_by(user_id=g.user.id, parent_id=None).all()
        return render_template('partials/folder_tree.html', folders=folders)
    return '', 204
