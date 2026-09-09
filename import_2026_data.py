import json
import logging
import sys
from datetime import datetime

# Setup detailed logging with timestamp as per global rules
log_filename = f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logging.info("Starting data import script for 2026 PDF files...")

with open('data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

courses = data.get('courses', [])
course_terms = data.get('course_terms', [])
leaves = data.get('leaves', [])
officers = data.get('officers', {}).get('active', [])

# Map officers for name verification
officer_dict = {o['id']: o['name'] for o in officers}
logging.info(f"Loaded {len(courses)} courses, {len(course_terms)} course terms, {len(leaves)} leaves, {len(officers)} officers.")

# Existing course mapping normalize
existing_course_aliases = {
    "فرقة": "CRS-001",
    "فرقة قادة اهداف حيوية": "CRS-002",
    "قادة أهداف حيوية": "CRS-002",
    "فرقة أمن المعسكرات": "CRS-003",
    "فرقة القيادات الأولى": "CRS-004",
    "القيادات الأولى": "CRS-004",
    "فرقة التدريب علي الاعمال القتالية": "CRS-005",
    "فرقة تأهيلية": "CRS-006",
    "فرقة أعمال المواجهة والتصدي للعدائيات": "CRS-007",
    "التصدي للعدائيات": "CRS-007",
    "فرقة الحراسات المشددة": "CRS-008",
    "حراسات مشددة": "CRS-008",
    "تخطيط وإدارة مسرح العمليات": "CRS-009"
}

# Build name -> ID mapping for existing courses
course_name_to_id = {c['name']: c['id'] for c in courses}
for alias, cid in existing_course_aliases.items():
    course_name_to_id[alias] = cid

# Determine max IDs
def get_max_crs_num():
    max_n = 0
    for c in courses:
        if c['id'].startswith('CRS-'):
            try:
                n = int(c['id'].split('-')[1])
                if n > max_n: max_n = n
            except ValueError: pass
    return max_n

def get_max_ct_num():
    max_n = 0
    for ct in course_terms:
        if ct['id'].startswith('CT-'):
            try:
                n = int(ct['id'].split('-')[1])
                if n > max_n: max_n = n
            except ValueError: pass
    return max_n

def get_max_lv_num():
    max_n = 0
    for lv in leaves:
        if lv['id'].startswith('LV-'):
            try:
                n = int(lv['id'].split('-')[1])
                if n > max_n: max_n = n
            except ValueError: pass
    return max_n

curr_crs_num = get_max_crs_num()
curr_ct_num = get_max_ct_num()
curr_lv_num = get_max_lv_num()

def get_or_create_course(course_name):
    global curr_crs_num
    if course_name in course_name_to_id:
        return course_name_to_id[course_name]
    
    curr_crs_num += 1
    new_id = f"CRS-{curr_crs_num:03d}"
    new_course = {
        "id": new_id,
        "name": course_name,
        "place": "",
        "kind": "",
        "note": ""
    }
    courses.append(new_course)
    course_name_to_id[course_name] = new_id
    logging.info(f"Created new Course: {new_id} - {course_name}")
    return new_id

# Officer courses to import (NO DATES)
officer_courses_import = [
    # OFF-002
    ("OFF-002", "تخطيط وإدارة مسرح العمليات"),
    ("OFF-002", "مواجهة أعمال قتالية"),
    ("OFF-002", "حراسات مشددة"),
    ("OFF-002", "قادة أهداف حيوية"),
    ("OFF-002", "أعمال مواجهة واقتحام"),
    ("OFF-002", "قناصة"),
    # OFF-027
    ("OFF-027", "البحث الجنائي"),
    ("OFF-027", "مباحث التهرب الضريبي"),
    ("OFF-027", "مباحث المصنفات الفنية وحقوق الملكية الفكرية"),
    ("OFF-027", "حقوق الإنسان"),
    # OFF-038
    ("OFF-038", "الإدارة العامة للمرور الأساسية"),
    ("OFF-038", "الأسلحة والذخائر"),
    ("OFF-038", "النجدة"),
    # OFF-016
    ("OFF-016", "عمليات الشرطة"),
    ("OFF-016", "قادة عمليات الشرطة"),
    ("OFF-016", "المهارة الميدانية في الأعمال القتالية"),
    ("OFF-016", "التأهيلية للأمن المركزي"),
    ("OFF-016", "الاستطلاع"),
    # OFF-043
    ("OFF-043", "المرور الأساسية"),
    ("OFF-043", "الأحوال المدنية الأساسية"),
    ("OFF-043", "القيادات الوسطى"),
    # OFF-028
    ("OFF-028", "التأهيلية للأمن المركزي"),
    ("OFF-028", "الأسلحة الصغيرة"),
    ("OFF-028", "التأهيلية للكشف والتفتيش والتعامل مع المفرقعات"),
    ("OFF-028", "التأهيلية لفحص أثار النزيف والتزوير لقطاع المنافذ والوثائق"),
    ("OFF-028", "إعداد قيادات إدارات قوات الأمن"),
    ("OFF-028", "القيادات الوسطى"),
    # OFF-015
    ("OFF-015", "الأساسية النزيف والتزوير"),
    ("OFF-015", "المتقدمة النزيف والتزوير"),
    # OFF-010
    ("OFF-010", "الشئون الإدارية (أ ت)"),
    ("OFF-010", "القيادات الوسطى"),
    # OFF-013
    ("OFF-013", "التأهيلية للأمن المركزي"),
    ("OFF-013", "تأمين وحراسة المنشآت"),
    ("OFF-013", "أطقم الميكروباص المدرع"),
    ("OFF-013", "تخطيط وإدارة مسرح العمليات"),
    # OFF-025
    ("OFF-025", "القيادات الأولى"),
    ("OFF-025", "القيادات الوسطى"),
    # OFF-031
    ("OFF-031", "حقوق الإنسان"),
    ("OFF-031", "جرائم عنف ضد المرأة"),
    # OFF-012
    ("OFF-012", "الشئون الإدارية (أ ت)"),
    ("OFF-012", "القيادات الوسطى"),
    # OFF-048
    ("OFF-048", "المواجهات الأمنية في الأماكن المفتوحة"),
    ("OFF-048", "التأهيلية للأمن المركزي"),
    # OFF-024
    ("OFF-024", "التأهيلية للأمن المركزي"),
    ("OFF-024", "أقسام ومراكز شرطة"),
    ("OFF-024", "الدوريات الأمنة"),
    # OFF-008
    ("OFF-008", "التأهيلية للأمن المركزي"),
    ("OFF-008", "تأمين وحراسة المنشآت"),
    ("OFF-008", "أطقم الميكروباص المدرع"),
    ("OFF-008", "تخطيط وإدارة مسرح العمليات"),
    # OFF-047
    ("OFF-047", "الكشف والتعامل مع المواد المتفجرة"),
    # OFF-019
    ("OFF-019", "الإطفاء الأساسية"),
    ("OFF-019", "المفرقعات والكشف عن الأجسام الأساسية"),
    ("OFF-019", "جرائم البترول"),
    ("OFF-019", "جرائم الطائرات والسفن"),
    # OFF-018
    ("OFF-018", "الأساسية لعلوم ونظم الاتصالات"),
    ("OFF-018", "التصدي للعدائيات"),
    ("OFF-018", "تلقى وفحص البلاغات الإلكترونية"),
    # OFF-039
    ("OFF-039", "التصدي للعدائيات"),
    # OFF-023
    ("OFF-023", "التصدي للعدائيات"),
    ("OFF-023", "المسعف القتالي"),
    ("OFF-023", "الرماية الدقيقة بالبندقية بعيدة المدى"),
    # OFF-049
    ("OFF-049", "الترسيخ والأخلاقيات للملازمين"),
    # OFF-044
    ("OFF-044", "ترسيخ وأخلاقيات العمل الشرطي")
]

# Track existing (officer_id, course_id) to avoid duplicate CT entries
existing_ct_pairs = {(ct['officer_id'], ct['course_id']) for ct in course_terms}

ct_added_count = 0
for off_id, crs_name in officer_courses_import:
    cid = get_or_create_course(crs_name)
    if (off_id, cid) in existing_ct_pairs:
        logging.info(f"Course term already exists for Officer {off_id} and Course {cid} ({crs_name}). Skipping.")
        continue
    
    curr_ct_num += 1
    new_ct_id = f"CT-{curr_ct_num:04d}"
    new_ct = {
        "id": new_ct_id,
        "course_id": cid,
        "officer_id": off_id,
        "start": "",
        "end": "",
        "note": "",
        "source": "فرق الضباط 2026"
    }
    course_terms.append(new_ct)
    existing_ct_pairs.add((off_id, cid))
    ct_added_count += 1
    logging.info(f"Added Course Term: {new_ct_id} | Officer: {off_id} ({officer_dict.get(off_id)}) | Course: {cid} ({crs_name})")

# Leaves to import (Monthly & Bi-monthly)
leaves_import = [
    # Monthly (شهرية)
    {"person_id": "OFF-008", "type": "شهرية", "start": "2026-09-08", "end": "2026-09-14", "return_date": "2026-09-15", "note": "تقصيرة 7/9"},
    {"person_id": "OFF-036", "type": "شهرية", "start": "2026-09-08", "end": "2026-09-14", "return_date": "2026-09-15", "note": "تقصيرة 7/9"},
    {"person_id": "OFF-037", "type": "شهرية", "start": "2026-09-08", "end": "2026-09-14", "return_date": "2026-09-15", "note": "تقصيرة 7/9"},
    {"person_id": "OFF-011", "type": "شهرية", "start": "2026-09-16", "end": "2026-09-22", "return_date": "2026-09-23", "note": "تقصيرة 15/9"},
    {"person_id": "OFF-047", "type": "شهرية", "start": "2026-09-16", "end": "2026-09-22", "return_date": "2026-09-23", "note": "تقصيرة 15/9"},
    {"person_id": "OFF-012", "type": "شهرية", "start": "2026-09-16", "end": "2026-09-22", "return_date": "2026-09-23", "note": "تقصيرة 15/9"},
    {"person_id": "OFF-031", "type": "شهرية", "start": "2026-09-23", "end": "2026-09-29", "return_date": "2026-09-30", "note": "تقصيرة 22/9"},
    {"person_id": "OFF-042", "type": "شهرية", "start": "2026-09-23", "end": "2026-09-29", "return_date": "2026-09-30", "note": "تقصيرة 22/9"},
    {"person_id": "OFF-013", "type": "شهرية", "start": "2026-09-30", "end": "2026-10-06", "return_date": "2026-10-07", "note": "تقصيرة 29/9"},
    {"person_id": "OFF-049", "type": "شهرية", "start": "2026-09-30", "end": "2026-10-06", "return_date": "2026-10-07", "note": "تقصيرة 29/9"},
    # Bi-monthly (نصف شهرية)
    {"person_id": "OFF-031", "type": "نصف شهرية", "start": "2026-08-28", "end": "2026-08-30", "return_date": "2026-08-31", "note": "تقصيرة 27/8"},
    {"person_id": "OFF-040", "type": "نصف شهرية", "start": "2026-08-28", "end": "2026-08-30", "return_date": "2026-08-31", "note": "تقصيرة 27/8"},
    {"person_id": "OFF-015", "type": "نصف شهرية", "start": "2026-09-01", "end": "2026-09-03", "return_date": "2026-09-04", "note": "تقصيرة 31/8"},
    {"person_id": "OFF-016", "type": "نصف شهرية", "start": "2026-09-07", "end": "2026-09-09", "return_date": "2026-09-10", "note": "تقصيرة 6/9"},
]

leaves_added_count = 0
for lv in leaves_import:
    off_id = lv['person_id']
    off_name = officer_dict.get(off_id, "")
    
    # Check if duplicate leave already exists
    duplicate = False
    for existing_lv in leaves:
        if (existing_lv.get('person_id') == off_id and 
            existing_lv.get('start') == lv['start'] and 
            existing_lv.get('end') == lv['end'] and
            existing_lv.get('type') == lv['type']):
            duplicate = True
            break
            
    if duplicate:
        logging.info(f"Leave already exists for Officer {off_id} on {lv['start']}. Skipping.")
        continue
        
    curr_lv_num += 1
    new_lv_id = f"LV-{curr_lv_num:03d}"
    new_leave_obj = {
        "id": new_lv_id,
        "person_id": off_id,
        "name": off_name,
        "type": lv['type'],
        "start": lv['start'],
        "end": lv['end'],
        "return_date": lv['return_date'],
        "note": lv['note'],
        "source": "الراحات الشهرية والنصف شهرية 2026"
    }
    leaves.append(new_leave_obj)
    leaves_added_count += 1
    logging.info(f"Added Leave: {new_lv_id} | Officer: {off_id} ({off_name}) | Type: {lv['type']} | Dates: {lv['start']} to {lv['end']}")

# Save updated arrays back to data dictionary
data['courses'] = courses
data['course_terms'] = course_terms
data['leaves'] = leaves

with open('data.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

logging.info(f"Data saved successfully to data.json!")
logging.info(f"Summary of changes:")
logging.info(f"  - Total Courses now: {len(courses)}")
logging.info(f"  - Total Course Terms added: {ct_added_count} (Total: {len(course_terms)})")
logging.info(f"  - Total Leaves added: {leaves_added_count} (Total: {len(leaves)})")
