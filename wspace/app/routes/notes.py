from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from app import db
from app.models import Note, Folder, Tag

bp = Blueprint('notes', __name__)


@bp.route('/')
def index():
    """Dashboard - list all notes."""
    folder_id = request.args.get('folder_id', type=int)
    tag_id = request.args.get('tag_id', type=int)

    query = Note.query

    if folder_id:
        query = query.filter_by(folder_id=folder_id)
    if tag_id:
        tag = Tag.query.get(tag_id)
        if tag:
            query = query.filter(Note.tags.contains(tag))

    notes = query.order_by(Note.updated_at.desc()).all()
    folders = Folder.query.filter_by(parent_id=None).all()
    tags = Tag.query.order_by(Tag.name).all()

    return render_template('index.html', notes=notes, folders=folders, tags=tags,
                         current_folder_id=folder_id, current_tag_id=tag_id)


@bp.route('/notes/new', methods=['GET', 'POST'])
def new_note():
    """Create a new note."""
    if request.method == 'POST':
        title = request.form.get('title', 'Untitled')
        content = request.form.get('content', '')
        file_type = request.form.get('file_type', 'md')
        folder_id = request.form.get('folder_id', type=int)
        tag_names = request.form.get('tags', '').split(',')

        note = Note(title=title, content=content, file_type=file_type, folder_id=folder_id)

        # Handle tags
        for tag_name in tag_names:
            tag_name = tag_name.strip()
            if tag_name:
                tag = Tag.query.filter_by(name=tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.session.add(tag)
                note.tags.append(tag)

        db.session.add(note)
        db.session.commit()

        if request.headers.get('HX-Request'):
            return redirect(url_for('notes.edit_note', note_id=note.id))
        return redirect(url_for('notes.edit_note', note_id=note.id))

    folders = Folder.query.all()
    tags = Tag.query.order_by(Tag.name).all()
    return render_template('editor.html', note=None, folders=folders, tags=tags)


@bp.route('/notes/<int:note_id>')
def view_note(note_id):
    """View a note."""
    note = Note.query.get_or_404(note_id)
    return redirect(url_for('notes.edit_note', note_id=note_id))


@bp.route('/notes/<int:note_id>/edit', methods=['GET', 'POST'])
def edit_note(note_id):
    """Edit a note."""
    note = Note.query.get_or_404(note_id)

    if request.method == 'POST':
        note.title = request.form.get('title', note.title)
        note.content = request.form.get('content', note.content)
        note.file_type = request.form.get('file_type', note.file_type)
        note.folder_id = request.form.get('folder_id', type=int) or None

        # Update tags
        tag_names = request.form.get('tags', '').split(',')
        note.tags = []
        for tag_name in tag_names:
            tag_name = tag_name.strip()
            if tag_name:
                tag = Tag.query.filter_by(name=tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.session.add(tag)
                note.tags.append(tag)

        note.sync_status = 'local'  # Mark as needing sync
        db.session.commit()

        if request.headers.get('HX-Request'):
            return render_template('partials/save_status.html', status='saved')
        return redirect(url_for('notes.index'))

    folders = Folder.query.all()
    tags = Tag.query.order_by(Tag.name).all()
    return render_template('editor.html', note=note, folders=folders, tags=tags)


@bp.route('/notes/<int:note_id>/delete', methods=['POST'])
def delete_note(note_id):
    """Delete a note."""
    note = Note.query.get_or_404(note_id)
    db.session.delete(note)
    db.session.commit()

    if request.headers.get('HX-Request'):
        return '', 200
    return redirect(url_for('notes.index'))


@bp.route('/notes/<int:note_id>/preview')
def preview_note(note_id):
    """Preview markdown content."""
    import markdown
    note = Note.query.get_or_404(note_id)
    if note.file_type == 'md':
        html = markdown.markdown(note.content, extensions=['fenced_code', 'tables'])
    else:
        html = f'<pre>{note.content}</pre>'
    return render_template('partials/preview.html', html=html)
