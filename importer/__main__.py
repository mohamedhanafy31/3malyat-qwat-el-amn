"""واجهة سطر الأوامر لمراحل الاستيراد."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

from .discover import VERSION as DISCOVER_VERSION
from .discover import run_discover
from .extract import VERSION as EXTRACT_VERSION
from .extract import run_extract
from .ledger import Ledger
from .normalize import VERSION as NORMALIZE_VERSION
from .normalize import run_normalize
from .resolve import VERSION as RESOLVE_VERSION
from .resolve import run_resolve
from .validate import VERSION as VALIDATE_VERSION
from .validate import run_validate


STAGES = ("discover", "extract", "validate", "normalize", "resolve", "transform", "verify", "store", "rollback", "report", "run")
DEFAULT_START = dt.date(2023, 10, 1)
DEFAULT_END = dt.date(2026, 9, 29)
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARCHIVE = REPO_ROOT.parents[1]


def _iso_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("يجب أن يكون التاريخ بصيغة YYYY-MM-DD") from exc


def _batch_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise argparse.ArgumentTypeError("رقم الدفعة يقبل الحروف والأرقام و._- فقط")
    return value


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python -m importer", description="مستورد أرشيف اليوميات")
    result.add_argument("stage", choices=STAGES)
    result.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE, help="جذر الأرشيف")
    result.add_argument("--data-dir", type=Path, default=None, help="مجلد بيانات الهدف")
    result.add_argument("--from", dest="from_date", type=_iso_date, default=DEFAULT_START)
    result.add_argument("--to", dest="to_date", type=_iso_date, default=DEFAULT_END)
    result.add_argument("--batch", type=_batch_id)
    result.add_argument("--write", action="store_true", help="السماح لمرحلة store بالكتابة")
    result.add_argument("--resume", action="store_true")
    result.add_argument("--i-know", action="store_true", help="السماح صراحة باستخدام data/ الخاصة بالمستودع")
    return result


def _data_dir(args: argparse.Namespace, cli: argparse.ArgumentParser) -> Path:
    raw = args.data_dir or os.environ.get("PERSONNEL_DATA_DIR")
    if not raw:
        cli.error("--data-dir مطلوب، أو عيّن PERSONNEL_DATA_DIR")
    path = Path(raw).expanduser().resolve()
    if path == (REPO_ROOT / "data").resolve() and not args.i_know:
        cli.error("رُفض استخدام data/ الخاصة بالمستودع؛ مرّر --i-know إذا كان ذلك مقصودًا")
    return path


def main(argv: list[str] | None = None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    data_dir = _data_dir(args, cli)
    archive = args.archive.expanduser().resolve()
    if args.from_date > args.to_date:
        cli.error("--from يجب ألا يأتي بعد --to")
    if not archive.is_dir():
        cli.error(f"جذر الأرشيف غير موجود: {archive}")
    batch = args.batch or f"{args.from_date.isoformat()}_{args.to_date.isoformat()}"
    ledger = Ledger(data_dir, batch)
    params = {
        "archive": str(archive),
        "data_dir": str(data_dir),
        "from": args.from_date.isoformat(),
        "to": args.to_date.isoformat(),
        "batch": batch,
        "write": args.write,
        "resume": args.resume,
    }
    state = ledger.initialise(params, {
        "discover": DISCOVER_VERSION,
        "extract": EXTRACT_VERSION,
        "validate": VALIDATE_VERSION,
        "normalize": NORMALIZE_VERSION,
        "resolve": RESOLVE_VERSION,
    })
    if args.stage == "discover":
        checkpoint = run_discover(archive, ledger, args.from_date, args.to_date, state)
        print(f"اكتملت مرحلة discover: {checkpoint['files']} ملف، {checkpoint['covered_dates']} تاريخًا مغطى.")
        return 0
    if args.stage == "extract":
        try:
            checkpoint = run_extract(archive, ledger, args.from_date, args.to_date, state,
                                     resume=args.resume)
        except FileNotFoundError as exc:
            cli.error(str(exc))
        print(f"اكتملت مرحلة extract: {checkpoint['documents']} وثيقة، "
              f"{checkpoint['records']} سجلًا، {checkpoint['errors']} أخطاء.")
        return 0
    if args.stage == "validate":
        try:
            checkpoint = run_validate(ledger, state, args.from_date, args.to_date, resume=args.resume)
        except FileNotFoundError as exc:
            cli.error(str(exc))
        print(f"اكتملت مرحلة validate: {checkpoint['documents']} وثيقة، "
              f"{checkpoint['quarantined_documents']} وثيقة معزولة.")
        return 0
    if args.stage == "normalize":
        try:
            checkpoint = run_normalize(ledger, state, args.from_date, args.to_date, resume=args.resume)
        except FileNotFoundError as exc:
            cli.error(str(exc))
        print(f"اكتملت مرحلة normalize: {checkpoint['records']} سجلًا، "
              f"{checkpoint['flagged_records']} سجلًا يحمل إشارة مراجعة.")
        return 0
    if args.stage == "resolve":
        try:
            checkpoint = run_resolve(ledger, state, args.from_date, args.to_date, resume=args.resume)
        except FileNotFoundError as exc:
            cli.error(str(exc))
        officers, personnel = checkpoint["officers"], checkpoint["personnel"]
        print("اكتملت مرحلة resolve: "
              f"الضباط {officers['clusters']} تجمعًا "
              f"({officers['matched_existing']} مطابق، {officers['new']} جديد، {officers['review']} مراجعة)؛ "
              f"الأفراد {personnel['clusters']} تجمعًا "
              f"({personnel['matched_existing']} مطابق، {personnel['new']} جديد، {personnel['review']} مراجعة).")
        fuzzy = checkpoint.get("fuzzy_merges", {})
        remaining = checkpoint.get("remaining_candidates", {})
        print("الدمج الاستدلالي: "
              f"{fuzzy.get('officers', 0)} للضباط، {fuzzy.get('personnel', 0)} للأفراد؛ "
              f"المرشحات المتبقية {remaining.get('officers', 0)} و"
              f"{remaining.get('personnel', 0)}؛ التجمعات الهالكة {checkpoint.get('junk_clusters', 0)}.")
        if checkpoint.get("self_check_errors"):
            print(f"أخطاء الفحص الذاتي: {checkpoint['self_check_errors']} "
                  "(راجع تقرير resolve-self-check.json).")
        return 0
    if args.stage == "run":
        run_discover(archive, ledger, args.from_date, args.to_date, state)
        run_extract(archive, ledger, args.from_date, args.to_date, state, resume=args.resume)
        run_validate(ledger, state, args.from_date, args.to_date, resume=args.resume)
        run_normalize(ledger, state, args.from_date, args.to_date, resume=args.resume)
        run_resolve(ledger, state, args.from_date, args.to_date, resume=args.resume)
        print("اكتملت المراحل discover وextract وvalidate وnormalize وresolve.")
        return 0
    print(f"المرحلة {args.stage}: not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
