"""تجهيز البيانات التلقائية المطلوبة عند فتح يوم للعرض."""
from .inspection_schedule import needs_seed as inspections_need_seed
from .inspection_schedule import seed_board_day
from .weekly_rest import needs_seed as weekly_needs_seed
from .weekly_rest import seed_day as seed_weekly_rest
from .target_defaults import needs_seed as targets_need_seed
from .target_defaults import seed_day as seed_targets


def needs_prepare(data, day, include_inspections=False):
    return weekly_needs_seed(data, day) or targets_need_seed(data, day) or (
        include_inspections and inspections_need_seed(data, day))


def prepare(data, day, include_inspections=False):
    # الراحة لازم تتسجّل قبل نسخ الأهداف عشان الضابط المستريح يتشال من
    # النسخة المبدئية بدل ما يظهر في الهدف وفي الراحات معًا.
    seed_weekly_rest(data, day)
    seed_targets(data, day)
    if include_inspections:
        seed_board_day(data, day)
