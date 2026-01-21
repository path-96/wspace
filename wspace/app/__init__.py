from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from app.config import Config

db = SQLAlchemy()
migrate = Migrate()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    from app.routes import notes, folders, tags, search, sync
    app.register_blueprint(notes.bp)
    app.register_blueprint(folders.bp)
    app.register_blueprint(tags.bp)
    app.register_blueprint(search.bp)
    app.register_blueprint(sync.bp)

    with app.app_context():
        db.create_all()
        from app.services.search_service import setup_fts
        setup_fts(db)

    return app
