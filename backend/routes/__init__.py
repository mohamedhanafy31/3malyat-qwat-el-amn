from .pages import bp as pages_bp
from .meta import bp as meta_bp
from .people import bp as people_bp
from .leaves import bp as leaves_bp
from .duty import bp as duty_bp
from .board import bp as board_bp
from .register import bp as register_bp
from .courses import bp as courses_bp
from .counts import bp as counts_bp
from .changes import bp as changes_bp
from .missions import bp as missions_bp
from .day_status import bp as day_status_bp

ALL_BLUEPRINTS = [pages_bp, meta_bp, people_bp, leaves_bp, duty_bp, board_bp,
                  register_bp, courses_bp, counts_bp, changes_bp,
                  missions_bp, day_status_bp]


def register_routes(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
