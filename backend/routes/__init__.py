from .pages import bp as pages_bp
from .meta import bp as meta_bp
from .people import bp as people_bp
from .leaves import bp as leaves_bp
from .duty import bp as duty_bp
from .duty_stats import bp as duty_stats_bp
from .board import bp as board_bp
from .register import bp as register_bp
from .courses import bp as courses_bp
from .counts import bp as counts_bp
from .changes import bp as changes_bp
from .missions import bp as missions_bp
from .fleet import bp as fleet_bp
from .service_catalog import bp as service_catalog_bp
from .officer_log import bp as officer_log_bp
from .day_status import bp as day_status_bp
from .afraad import bp as afraad_bp
from .inspection_schedule import bp as inspection_schedule_bp
from .rest_suspension import bp as rest_suspension_bp
from .auth import bp as auth_bp
from .users import bp as users_bp
from .audit import bp as audit_bp
from .campaign import bp as campaign_bp
from .day_files import bp as day_files_bp
from .ops import bp as ops_bp
from .roster_import import bp as roster_import_bp
from .health import bp as health_bp

ALL_BLUEPRINTS = [pages_bp, meta_bp, people_bp, leaves_bp, duty_bp, duty_stats_bp,
                  board_bp, register_bp, courses_bp, counts_bp, changes_bp,
                  missions_bp, fleet_bp, service_catalog_bp, officer_log_bp, day_status_bp,
                  afraad_bp, inspection_schedule_bp, rest_suspension_bp,
                  auth_bp, users_bp, audit_bp, campaign_bp, day_files_bp, ops_bp,
                  roster_import_bp, health_bp]


def register_routes(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
