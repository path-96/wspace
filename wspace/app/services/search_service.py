from flask import current_app
from sqlalchemy import text
from app import db
from app.models import Note


def setup_fts(db_instance):
    """Set up FTS5 virtual table and triggers for full-text search."""
    with db_instance.engine.connect() as conn:
        # Check if FTS table exists
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='notes_fts'"
        ))
        if result.fetchone():
            return  # Already exists

        # Create FTS5 virtual table
        conn.execute(text('''
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                title,
                content,
                content='notes',
                content_rowid='id'
            )
        '''))

        # Populate FTS table with existing data
        conn.execute(text('''
            INSERT INTO notes_fts(rowid, title, content)
            SELECT id, title, content FROM notes
        '''))

        # Create triggers to keep FTS in sync
        conn.execute(text('''
            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, title, content)
                VALUES (new.id, new.title, new.content);
            END
        '''))

        conn.execute(text('''
            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, content)
                VALUES ('delete', old.id, old.title, old.content);
            END
        '''))

        conn.execute(text('''
            CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, content)
                VALUES ('delete', old.id, old.title, old.content);
                INSERT INTO notes_fts(rowid, title, content)
                VALUES (new.id, new.title, new.content);
            END
        '''))

        conn.commit()


def search_notes(query, limit=50):
    """
    Search notes using FTS5 with BM25 ranking.
    Returns list of note dicts with search rank.
    """
    if not query or not query.strip():
        return []

    # Escape special FTS5 characters and prepare query
    search_query = query.strip()
    # Add wildcards for partial matching
    search_terms = ' '.join([f'{term}*' for term in search_query.split()])

    try:
        with db.engine.connect() as conn:
            result = conn.execute(text('''
                SELECT
                    notes.id,
                    notes.title,
                    notes.content,
                    notes.file_type,
                    notes.folder_id,
                    notes.created_at,
                    notes.updated_at,
                    bm25(notes_fts) as rank
                FROM notes_fts
                JOIN notes ON notes_fts.rowid = notes.id
                WHERE notes_fts MATCH :query
                ORDER BY rank
                LIMIT :limit
            '''), {'query': search_terms, 'limit': limit})

            results = []
            for row in result:
                # Create snippet from content
                content = row.content or ''
                snippet = content[:200] + '...' if len(content) > 200 else content

                results.append({
                    'id': row.id,
                    'title': row.title,
                    'snippet': snippet,
                    'file_type': row.file_type,
                    'folder_id': row.folder_id,
                    'rank': row.rank,
                    'created_at': row.created_at.isoformat() if row.created_at else None,
                    'updated_at': row.updated_at.isoformat() if row.updated_at else None,
                })

            return results
    except Exception as e:
        current_app.logger.error(f"Search error: {e}")
        # Fallback to simple LIKE search if FTS fails
        notes = Note.query.filter(
            db.or_(
                Note.title.ilike(f'%{query}%'),
                Note.content.ilike(f'%{query}%')
            )
        ).limit(limit).all()

        return [{
            'id': n.id,
            'title': n.title,
            'snippet': (n.content[:200] + '...') if n.content and len(n.content) > 200 else (n.content or ''),
            'file_type': n.file_type,
            'folder_id': n.folder_id,
            'rank': 0,
            'created_at': n.created_at.isoformat() if n.created_at else None,
            'updated_at': n.updated_at.isoformat() if n.updated_at else None,
        } for n in notes]
