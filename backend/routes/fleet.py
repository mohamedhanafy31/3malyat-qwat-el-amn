from flask import Blueprint, jsonify, request

from .. import campaign, changes, fleet
from .. import day_status
from ..constants import VEHICLE_ORIGINS, VEHICLE_STATUSES, VEHICLE_TYPES
from ..models import Conscript, Vehicle
from ..repo import Repos
from ..store import AbortRequest, load_data, with_data
from ..utils import canonical_day, json_payload

bp = Blueprint("fleet", __name__)


def _vehicle_dict(vehicle):
    out = vehicle.as_dict()
    out["plate"] = vehicle.plate
    out["label"] = fleet.vehicle_label(vehicle)
    return out


def _vehicle_from_payload(payload, vehicle=None):
    if vehicle is None:
        vehicle = Vehicle()
    fields = ("plate_series", "plate_number", "type", "model", "status", "fault", "notes", "archived",
              "origin", "party")
    for field in fields:
        if field in payload:
            setattr(vehicle, field, payload[field])
    vehicle.plate_series, vehicle.plate_number = fleet.normalize_plate(
        vehicle.plate_series, vehicle.plate_number)
    if vehicle.status == "operational":
        vehicle.fault = ""
    if vehicle.origin != "external":
        vehicle.party = ""
    return vehicle


def _validate_vehicle(repos, vehicle, ignore_id=None):
    errors = vehicle.validate()
    if errors:
        return errors[0], 400
    if fleet.plate_taken(repos.data, vehicle.plate_series, vehicle.plate_number, ignore_id):
        return "رقم اللوحة مستخدم بالفعل.", 409
    return None, None


@bp.get("/api/vehicles")
def list_vehicles():
    data = load_data(())
    repos = Repos(data)
    vehicle_type = request.args.get("type", "").strip()
    status = request.args.get("status", "").strip()
    origin = request.args.get("origin", "").strip()
    include_archived = request.args.get("archived") == "1"
    vehicles = repos.vehicles.all()
    if vehicle_type:
        vehicles = [v for v in vehicles if v.type == vehicle_type]
    if status:
        vehicles = [v for v in vehicles if v.status == status]
    if origin:
        vehicles = [v for v in vehicles if v.origin == origin]
    if not include_archived:
        vehicles = [v for v in vehicles if not v.archived]
    return jsonify({"vehicles": [_vehicle_dict(v) for v in vehicles],
                    "types": VEHICLE_TYPES, "statuses": VEHICLE_STATUSES,
                    "origins": VEHICLE_ORIGINS})


@bp.post("/api/vehicles")
def add_vehicle():
    payload = json_payload()

    def mutate(data):
        repos = Repos(data)
        vehicle = _vehicle_from_payload(payload)
        error, status = _validate_vehicle(repos, vehicle)
        if error:
            raise AbortRequest((jsonify({"error": error}), status))
        repos.vehicles.add(vehicle)
        changes.record(data, "vehicle", vehicle.id, "create", after=vehicle.as_dict(),
                       text=f"إضافة مركبة «{vehicle.plate}»")
        return jsonify(_vehicle_dict(vehicle)), 201

    return with_data(mutate, ())


@bp.patch("/api/vehicles/<vehicle_id>")
def edit_vehicle(vehicle_id):
    payload = json_payload()

    def mutate(data):
        repos = Repos(data)
        vehicle = repos.vehicles.find(vehicle_id)
        if not vehicle:
            raise AbortRequest((jsonify({"error": "المركبة غير موجودة."}), 404))
        before = vehicle.as_dict()
        _vehicle_from_payload(payload, vehicle)
        error, status = _validate_vehicle(repos, vehicle, vehicle_id)
        if error:
            raise AbortRequest((jsonify({"error": error}), status))
        repos.vehicles.save(vehicle)
        changes.record(data, "vehicle", vehicle_id, "update", before=before,
                       after=vehicle.as_dict(), text=f"تعديل مركبة «{vehicle.plate}»")
        return jsonify(_vehicle_dict(vehicle))

    return with_data(mutate, ())


@bp.delete("/api/vehicles/<vehicle_id>")
def delete_vehicle(vehicle_id):
    def mutate(data):
        repos = Repos(data)
        vehicle = repos.vehicles.find(vehicle_id)
        if not vehicle:
            raise AbortRequest((jsonify({"error": "المركبة غير موجودة."}), 404))
        referenced = campaign.referenced_vehicle_days(data, vehicle_id)
        if referenced:
            raise AbortRequest((jsonify({"error": "المركبة مستخدمة في يومية الحملة؛ أرشفها بدل حذفها."}), 409))
        repos.vehicles.remove(vehicle_id)
        changes.record(data, "vehicle", vehicle_id, "delete", before=vehicle.as_dict(),
                       text=f"حذف مركبة «{vehicle.plate}»")
        return jsonify({"ok": True})

    return with_data(mutate, lambda view: view.index.days_with("day_campaign"))


def _normal_name(value):
    return " ".join(str(value or "").split())


def _conscript_from_payload(payload, conscript=None):
    conscript = conscript or Conscript()
    if "name" in payload:
        conscript.name = _normal_name(payload["name"])
    if "phone" in payload:
        conscript.phone = str(payload["phone"] or "").strip()
    if "is_driver" in payload:
        conscript.is_driver = bool(payload["is_driver"])
    return conscript


@bp.get("/api/conscripts")
def list_conscripts():
    return jsonify({"conscripts": [c.as_dict() for c in Repos(load_data(())).conscripts.all()]})


@bp.post("/api/conscripts")
def add_conscript():
    payload = json_payload()

    def mutate(data):
        repos = Repos(data)
        conscript = _conscript_from_payload(payload)
        errors = conscript.validate()
        if errors:
            raise AbortRequest((jsonify({"error": errors[0]}), 400))
        if any(_normal_name(c.name) == _normal_name(conscript.name) for c in repos.conscripts.all()):
            raise AbortRequest((jsonify({"error": "المجند موجود بالفعل."}), 409))
        repos.conscripts.add(conscript)
        changes.record(data, "conscript", conscript.id, "create", after=conscript.as_dict(),
                       text=f"إضافة مجند «{conscript.name}»")
        return jsonify(conscript.as_dict()), 201

    return with_data(mutate, ())


@bp.patch("/api/conscripts/<conscript_id>")
def edit_conscript(conscript_id):
    payload = json_payload()

    def mutate(data):
        repos = Repos(data)
        conscript = repos.conscripts.find(conscript_id)
        if not conscript:
            raise AbortRequest((jsonify({"error": "المجند غير موجود."}), 404))
        before = conscript.as_dict()
        _conscript_from_payload(payload, conscript)
        errors = conscript.validate()
        if errors:
            raise AbortRequest((jsonify({"error": errors[0]}), 400))
        if any(c.id != conscript_id and _normal_name(c.name) == _normal_name(conscript.name)
               for c in repos.conscripts.all()):
            raise AbortRequest((jsonify({"error": "المجند موجود بالفعل."}), 409))
        repos.conscripts.save(conscript)
        changes.record(data, "conscript", conscript_id, "update", before=before,
                       after=conscript.as_dict(), text=f"تعديل مجند «{conscript.name}»")
        return jsonify(conscript.as_dict())

    return with_data(mutate, ())


@bp.delete("/api/conscripts/<conscript_id>")
def delete_conscript(conscript_id):
    def mutate(data):
        repos = Repos(data)
        conscript = repos.conscripts.find(conscript_id)
        if not conscript:
            raise AbortRequest((jsonify({"error": "المجند غير موجود."}), 404))
        referenced = campaign.referenced_conscript_days(data, conscript_id)
        if referenced:
            raise AbortRequest((jsonify({"error": "المجند مستخدم كسائق في يومية الحملة؛ ألغ تحديد is_driver بدل حذفه."}), 409))
        repos.conscripts.remove(conscript_id)
        changes.record(data, "conscript", conscript_id, "delete", before=conscript.as_dict(),
                       text=f"حذف مجند «{conscript.name}»")
        return jsonify({"ok": True})

    return with_data(mutate, lambda view: view.index.days_with("day_campaign"))


@bp.get("/api/drivers")
def list_drivers():
    day = canonical_day(request.args.get("day") or day_status.today_iso())
    if not day:
        return jsonify({"error": "التاريخ غير صحيح."}), 400
    return jsonify(fleet.drivers_on(load_data(()), day))
