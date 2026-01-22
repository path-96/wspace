from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session, g, current_app
from app import db
from app.models import Note, Folder, Tag
from app.routes.auth import login_required, get_current_user
from app.services.gdrive_service import GDriveService

bp = Blueprint('notes', __name__)


def get_folder_path(folder):
    """Get folder path as list of names from root to folder."""
    if not folder:
        return []
    path = []
    current = folder
    while current:
        path.insert(0, current.name)
        current = current.parent
    return path


def auto_sync_note(note):
    """Auto-sync a note to Google Drive if connected, preserving folder structure."""
    credentials = session.get('gdrive_credentials')
    if not credentials:
        return False

    try:
        service = GDriveService(current_app.config, credentials)
        root_folder_id = service.get_or_create_notes_folder()

        # Get the target folder in Drive (create folder structure if needed)
        if note.folder:
            folder_path = get_folder_path(note.folder)
            target_folder_id = service.get_or_create_folder_path(folder_path, root_folder_id)

            # Update folder's gdrive_id if not set
            if not note.folder.gdrive_id:
                note.folder.gdrive_id = target_folder_id
        else:
            target_folder_id = root_folder_id

        filename = f"{note.title}.{note.file_type}"
        if note.gdrive_id:
            # Update file, potentially moving to new folder
            service.update_file(note.gdrive_id, note.content, filename, target_folder_id)
        else:
            note.gdrive_id = service.upload_file(note.content, filename, target_folder_id)

        note.sync_status = 'synced'
        db.session.commit()

        # Update credentials in session (they may have been refreshed)
        session['gdrive_credentials'] = service.get_credentials_dict()
        return True
    except Exception as e:
        current_app.logger.error(f"Auto-sync error: {e}")
        note.sync_status = 'local'
        db.session.commit()
        return False


def auto_delete_from_drive(gdrive_id):
    """Delete a file from Google Drive if connected."""
    credentials = session.get('gdrive_credentials')
    if not credentials or not gdrive_id:
        return False

    try:
        service = GDriveService(current_app.config, credentials)
        service.service.files().delete(fileId=gdrive_id).execute()
        session['gdrive_credentials'] = service.get_credentials_dict()
        return True
    except Exception as e:
        current_app.logger.error(f"Auto-delete from Drive error: {e}")
        return False


@bp.before_request
def load_user():
    """Load current user before each request."""
    g.user = get_current_user()


@bp.route('/')
@login_required
def index():
    """Dashboard - list all notes."""
    folder_id = request.args.get('folder_id', type=int)
    tag_id = request.args.get('tag_id', type=int)

    query = Note.query.filter_by(user_id=g.user.id)

    if folder_id:
        query = query.filter_by(folder_id=folder_id)
    if tag_id:
        tag = Tag.query.get(tag_id)
        if tag:
            query = query.filter(Note.tags.contains(tag))

    notes = query.order_by(Note.updated_at.desc()).all()
    folders = Folder.query.filter_by(user_id=g.user.id, parent_id=None).all()
    tags = Tag.query.order_by(Tag.name).all()

    return render_template('index.html', notes=notes, folders=folders, tags=tags,
                         current_folder_id=folder_id, current_tag_id=tag_id, user=g.user)


@bp.route('/notes/new', methods=['GET', 'POST'])
@login_required
def new_note():
    """Create a new note."""
    if request.method == 'POST':
        title = request.form.get('title', 'Untitled')
        content = request.form.get('content', '')
        file_type = request.form.get('file_type', 'md')
        folder_id = request.form.get('folder_id', type=int)
        tag_names = request.form.get('tags', '').split(',')

        note = Note(title=title, content=content, file_type=file_type,
                   folder_id=folder_id, user_id=g.user.id)

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

        # Auto-sync to Google Drive
        auto_sync_note(note)

        if request.headers.get('HX-Request'):
            return redirect(url_for('notes.edit_note', note_id=note.id))
        return redirect(url_for('notes.edit_note', note_id=note.id))

    folders = Folder.query.filter_by(user_id=g.user.id).all()
    tags = Tag.query.order_by(Tag.name).all()
    return render_template('editor.html', note=None, folders=folders, tags=tags, user=g.user)


@bp.route('/notes/<int:note_id>')
@login_required
def view_note(note_id):
    """View a note."""
    note = Note.query.filter_by(id=note_id, user_id=g.user.id).first_or_404()
    return redirect(url_for('notes.edit_note', note_id=note_id))


@bp.route('/notes/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_note(note_id):
    """Edit a note."""
    note = Note.query.filter_by(id=note_id, user_id=g.user.id).first_or_404()

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

        db.session.commit()

        # Auto-sync to Google Drive
        synced = auto_sync_note(note)

        if request.headers.get('HX-Request'):
            return render_template('partials/save_status.html', status='synced' if synced else 'saved')
        return redirect(url_for('notes.index'))

    folders = Folder.query.filter_by(user_id=g.user.id).all()
    tags = Tag.query.order_by(Tag.name).all()
    return render_template('editor.html', note=note, folders=folders, tags=tags, user=g.user)


@bp.route('/notes/<int:note_id>/delete', methods=['POST'])
@login_required
def delete_note(note_id):
    """Delete a note."""
    note = Note.query.filter_by(id=note_id, user_id=g.user.id).first_or_404()
    gdrive_id = note.gdrive_id

    db.session.delete(note)
    db.session.commit()

    # Auto-delete from Google Drive
    if gdrive_id:
        auto_delete_from_drive(gdrive_id)

    if request.headers.get('HX-Request'):
        return '', 200
    return redirect(url_for('notes.index'))


@bp.route('/notes/<int:note_id>/preview')
@login_required
def preview_note(note_id):
    """Preview markdown content."""
    import markdown
    note = Note.query.filter_by(id=note_id, user_id=g.user.id).first_or_404()
    if note.file_type == 'md':
        html = markdown.markdown(note.content, extensions=['fenced_code', 'tables'])
    else:
        html = f'<pre>{note.content}</pre>'
    return render_template('partials/preview.html', html=html)
