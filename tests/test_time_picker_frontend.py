import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed to execute the picker functions")
def test_time_picker_canonical_values_and_period_mapping():
    core = Path(__file__).parents[1] / "static/js/core.js"
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('function parseTimeAr(');
const middle = source.indexOf('const timePopover=', start);
const picker = source.indexOf('function _tpCanonical(', middle);
const end = source.indexOf('function _tpRender(', picker);
assert(start >= 0 && middle > start && picker > middle && end > picker);
const context = {};
vm.createContext(context);
vm.runInContext(source.slice(start, middle) + source.slice(picker, end), context);

for (let hour = 1; hour <= 6; hour++) {
  const am = `${String(hour).padStart(2, '0')}:00`;
  const pm = `${hour + 12}:00`;
  const input = { dataset: {}, value: '' };
  context.setTimeInputValue(input, am);
  assert.equal(input.dataset.hhmm, am);
  assert.equal(context._tpCanonical(context._tpDraftFromInput(input)), am);
  context.setTimeInputValue(input, pm);
  assert.equal(input.dataset.hhmm, pm);
  assert.equal(context._tpCanonical(context._tpDraftFromInput(input)), pm);
  assert.equal(context.parseTimeAr(String(hour)), pm);
  assert.equal(context.parseTimeAr(String(hour), "ص"), am);
  assert.equal(context.parseTimeAr(String(hour), "م"), pm);
}
for (let hour = 7; hour <= 11; hour++) {
  assert.equal(context.parseTimeAr(`${String(hour).padStart(2, '0')}:00`), `${String(hour).padStart(2, '0')}:00`);
  assert.equal(context.parseTimeAr(String(hour)), `${String(hour).padStart(2, '0')}:00`);
}
assert.equal(context._tpCanonical({hour: 12, minute: 0, period: 'am'}), '00:00');
assert.equal(context._tpCanonical({hour: 12, minute: 0, period: 'pm'}), '12:00');
assert.equal(context.parseTimeAr('1ص'), '01:00');
assert.equal(context.parseTimeAr('3:30ص'), '03:30');
assert.equal(context.parseTimeAr('6ص'), '06:00');
assert.equal(context.parseTimeAr('1م'), '13:00');
assert.equal(context.parseTimeAr('5م'), '17:00');
{
  const catalog = fs.readFileSync(process.argv[1].replace('/static/js/core.js', '/static/js/service-catalog.js'), 'utf8');
  assert.match(catalog, /setTimeInputValue\(\$\("#serviceLineAm"\), line\?\.depart_am \|\| "", "ص"\)/);
  assert.match(catalog, /setTimeInputValue\(\$\("#serviceLinePm"\), line\?\.depart_pm \|\| "", "م"\)/);
  assert.match(catalog, /setTimeInputValue\(\$\("#svcReportAm"\), s\?\.report_am \|\| "", "ص"\)/);
  assert.match(catalog, /setTimeInputValue\(\$\("#svcReportPm"\), s\?\.report_pm \|\| "", "م"\)/);
}
for (const [value, display] of [['00:00', '12 ليل'], ['12:00', '12ظ']]) {
  const input = {dataset: {}, value: ''};
  context.setTimeInputValue(input, value);
  assert.equal(input.dataset.hhmm, value);
  assert.equal(input.value, display);
  assert.equal(context._tpCanonical(context._tpDraftFromInput(input)), value);
}
"""
    subprocess.run(["node", "-e", script, str(core)], check=True, capture_output=True, text=True)
