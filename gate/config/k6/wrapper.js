// MOADIX gate k6 wrapper (increment 5). The gate copies this next to the product's
// load script in an export of HEAD, replacing __PRODUCT_SCRIPT__, and runs k6 on it.
// The product's options, setup, default function and teardown run unchanged; the
// gate's handleSummary replaces any the product defines, so the gate decides what
// is written: the full summary as JSON and every threshold as a JUnit test case.
// `export *` passes through options, setup, teardown and any scenario `exec` functions
// exactly as the product exports them (and nothing it does not export); this module's
// own handleSummary shadows the product's.
export * from '__PRODUCT_SCRIPT__';
import productDefault from '__PRODUCT_SCRIPT__';
export default productDefault;

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function handleSummary(data) {
  const cases = [];
  for (const name of Object.keys(data.metrics).sort()) {
    const th = data.metrics[name].thresholds || {};
    for (const expr of Object.keys(th).sort()) {
      cases.push({ metric: name, expr: expr, ok: th[expr].ok === true });
    }
  }
  const failed = cases.filter((c) => !c.ok).length;
  let xml = '<?xml version="1.0" encoding="UTF-8"?>\n';
  xml += '<testsuites tests="' + cases.length + '" failures="' + failed + '">\n';
  xml += '  <testsuite name="k6 thresholds" tests="' + cases.length + '" failures="' + failed + '">\n';
  for (const c of cases) {
    xml += '    <testcase classname="' + esc(c.metric) + '" name="' + esc(c.metric + ' ' + c.expr) + '">';
    if (!c.ok) xml += '<failure message="threshold crossed: ' + esc(c.expr) + '"/>';
    xml += '</testcase>\n';
  }
  xml += '  </testsuite>\n</testsuites>\n';
  const out = __ENV.MOADIX_OUT;
  const files = {};
  files[out + '/summary.json'] = JSON.stringify(data);
  files[out + '/junit.xml'] = xml;
  files[out + '/thresholds.json'] = JSON.stringify(cases);
  return files;
}
