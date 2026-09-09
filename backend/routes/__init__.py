from .pages import bp as pages_bp
from .meta import bp as meta_bp
from .people import bp as people_bp
from .leaves import bp as leaves_bp
from .duty import bp as duty_bp
from .board import bp as board_bp
from .services import bp as services_bp
from .register import bp as register_bp
from .courses import bp as courses_bp

ALL_BLUEPRINTS = [pages_bp, meta_bp, people_bp, leaves_bp, duty_bp, board_bp,
                  services_bp, register_bp, courses_bp]


def register_routes(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
