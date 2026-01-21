from datetime import datetime, timezone
from app import db
from app.models.tag import note_tags


class Note(db.Model):
    __tablename__ = 'notes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, default='')
    file_type = db.Column(db.String(10), default='md')  # 'txt' or 'md'
    folder_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=True)
    gdrive_id = db.Column(db.String(255), nullable=True)
    gdrive_modified = db.Column(db.DateTime, nullable=True)
    sync_status = db.Column(db.String(20), default='local')  # local, synced, conflict
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Many-to-many relationship with tags
    tags = db.relationship('Tag', secondary=note_tags, lazy='subquery',
                          backref=db.backref('notes', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'file_type': self.file_type,
            'folder_id': self.folder_id,
            'gdrive_id': self.gdrive_id,
            'sync_status': self.sync_status,
            'tags': [tag.to_dict() for tag in self.tags],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Note {self.title}>'
