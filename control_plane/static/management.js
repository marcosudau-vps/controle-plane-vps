'use strict';
let context, services = [],
  selected = null,
  currentPlan = null;
const byId = id => document.getElementById(id);
const scopes = {
  viewer: ['read'],
  operator: ['read', 'runtime'],
  deployer: ['read', 'runtime', 'deploy'],
  maintainer: ['read', 'runtime', 'deploy', 'configure'],
  administrator: ['read', 'runtime', 'deploy', 'configure', 'policy']
};
const can = s => Boolean(context && scopes[context.role]?.includes(s));

function node(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = String(text);
  if (cls) n.className = cls;
  return n;
}

function showError(e) {
  byId('error').hidden = false;
  byId('error').textContent = e.message || String(e);
}
async function api(path, body, method) {
  const r = await fetch('/api/v1' + path, {
    credentials: 'same-origin',
    method: method || (body ? 'POST' : 'GET'),
    headers: body ? {
      'Content-Type': 'application/json',
      'X-CP-CSRF': '1'
    } : {},
    body: body ? JSON.stringify(body) : undefined
  });
  const result = await r.json();
  if (!r.ok) throw Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail || result));
  return result.data;
}

function detailBlock(parent, title, data) {
  const d = node('details');
  d.append(node('summary', title), node('pre', JSON.stringify(data, null, 2)));
  parent.append(d);
}
async function refresh() {
  byId('error').hidden = true;
  context = await api('/management/context');
  byId('identity').textContent = context.actor + ' · ' + context.role;
  services = (await api('/catalog?limit=500')).items;
  catalog();
  byId('storage-load').hidden = !can('configure') || !context.services.includes('*');
  byId('policy-form').hidden = !can('policy');
  const sys = await api('/management/system');
  const container = byId('system');
  container.replaceChildren();
  for (const [title, value, small] of [
      ['Registriert', services.length, 'Services im zugänglichen Bereich'],
      ['RAM verfügbar', sys.memory_available_mib + ' MiB', 'Host-Beobachtung'],
      ['Systemlast', sys.load.map(n => n.toFixed(2)).join(' / '), '1 / 5 / 15 Minuten'],
      ['Ausführung', context.execution_enabled ? 'Freigeschaltet' : 'Deaktiviert', sys.observed_at]
    ]) {
    const card = node('div', undefined, 'card');
    card.append(node('span', title), node('strong', value), node('small', small));
    container.append(card);
  }
  await histories();
  if (selected) await selectService(selected);
}

function catalog() {
  const search = byId('search').value.toLowerCase();
  byId('catalog').replaceChildren();
  for (const s of services.filter(s => (s.slug + ' ' + s.title).toLowerCase().includes(search))) {
    const b = node('button', s.title + ' · ' + s.status);
    b.setAttribute('aria-current', String(s.slug === selected));
    b.addEventListener('click', () => selectService(s.slug).catch(showError));
    byId('catalog').append(b);
  }
}
async function selectService(slug) {
  selected = slug;
  catalog();
  const base = '/services/' + encodeURIComponent(slug);
  const [contract, status, rules, releases] = await Promise.all([api(base + '/contract'), api(base + '/runtime/status'), api(base + '/policies'), api(base + '/deployments/releases')]);
  const d = byId('detail');
  d.replaceChildren(node('h2', contract.service.title), node('span', contract.service.slug, 'badge'), node('span', contract.service.status, 'badge'), node('p', contract.service.summary || contract.profile.description || 'Keine Beschreibung hinterlegt.'));
  if (contract.lifecycle.protected) d.append(node('p', 'Geschützte Kerninfrastruktur. Laufzeitaktionen sind gesperrt.', 'warning'));
  for (const rt of status) {
    d.append(node('h3', 'Laufzeit · ' + rt.runtime_type), node('p', 'Soll: ' + rt.desired_state + ' · Beobachtet: ' + rt.observed_state + ' · ' + rt.observed_at));
    if (rt.error) d.append(node('p', rt.error, 'warning'));
    if (rt.metrics.length) detailBlock(d, 'CPU und RAM', rt.metrics);
    detailBlock(d, 'Container und Images', rt.containers);
    const actions = node('div', undefined, 'actions');
    const requestAction = (action, extra = {}) => plan(slug, rt.runtime_id, action, extra).catch(showError);
    if (can('runtime')) {
      for (const [action, label] of [
          ['start', 'Start planen'],
          ['stop', 'Stop planen'],
          ['restart', 'Restart planen']
        ]) {
        const b = node('button', label);
        b.disabled = contract.lifecycle.protected;
        b.addEventListener('click', () => requestAction(action));
        actions.append(b);
      }
      const autostart = node('select');
      autostart.setAttribute('aria-label', 'Autostart');
      for (const [v, t] of [
          ['on_demand', 'Bei Bedarf'],
          ['always', 'Automatischer Wiederanlauf'],
          ['disabled', 'Autostart aus']
        ]) {
        const o = node('option', t);
        o.value = v;
        autostart.append(o);
      }
      autostart.value = rt.autostart_policy;
      const a = node('button', 'Autostart planen');
      a.disabled = contract.lifecycle.protected;
      a.addEventListener('click', () => requestAction('autostart', {
        autostart_policy: autostart.value
      }));
      actions.append(autostart, a);
      const log = node('button', 'Logs anzeigen');
      log.addEventListener('click', async () => {
        try {
          detailBlock(d, 'Letzte Logs', (await api(base + '/runtime/logs?runtime_id=' + encodeURIComponent(rt.runtime_id))).text);
        } catch (e) {
          showError(e);
        }
      });
      actions.append(log);
    }
    if (can('deploy')) {
      for (const action of ['pull', 'build', 'deploy', 'update']) {
        const b = node('button', action + ' planen');
        b.disabled = contract.lifecycle.protected;
        b.addEventListener('click', () => requestAction(action));
        actions.append(b);
      }
      for (const release of releases.filter(r => r.runtime_id === rt.runtime_id && Object.keys(r.previous_images).length)) {
        const b = node('button', 'Rollback ' + release.id.slice(0, 8) + ' planen');
        b.disabled = contract.lifecycle.protected;
        b.addEventListener('click', () => requestAction('rollback', {
          release_id: release.id
        }));
        actions.append(b);
      }
    }
    d.append(actions);
    if (can('configure') && rt.compose_services) {
      const form = node('form');
      const title = node('h3', 'Image-Herkunft registrieren');
      const service = node('select');
      service.setAttribute('aria-label', 'Compose-Service');
      for (const name of rt.compose_services) {
        const o = node('option', name);
        o.value = name;
        service.append(o);
      }
      const kind = node('select');
      kind.setAttribute('aria-label', 'Build-Art');
      for (const k of ['registry_image', 'compose_build', 'external_build']) {
        const o = node('option', k);
        o.value = k;
        kind.append(o);
      }
      const image = node('input');
      image.placeholder = 'Image-Referenz aus Compose';
      image.required = true;
      image.setAttribute('aria-label', 'Image-Referenz');
      const workflow = node('input');
      workflow.placeholder = 'Workflow-ID bei externem Build';
      workflow.setAttribute('aria-label', 'Workflow-ID');
      const save = node('button', 'Herkunft speichern');
      form.append(service, kind, image, workflow, save);
      form.addEventListener('submit', async e => {
        e.preventDefault();
        try {
          await api(base + '/deployments/sources', {
            runtime_id: rt.runtime_id,
            compose_service: service.value,
            source_kind: kind.value,
            image_ref: image.value,
            workflow_id: workflow.value
          }, 'PUT');
          await selectService(slug);
        } catch (error) {
          showError(error);
        }
      });
      d.append(title, form);
    }
  }
  detailBlock(d, 'Routing, Ports und TLS', {
    routes: contract.routes,
    ports: contract.ports
  });
  detailBlock(d, 'Builds und Deployments', {
    sources: contract.deployment_sources,
    releases
  });
  detailBlock(d, 'Regeln und Abhängigkeiten', {
    rules,
    relations: contract.relations
  });
  detailBlock(d, 'Technischer Service-Contract', contract);
}
async function plan(slug, runtime_id, action, extra) {
  currentPlan = await api('/services/' + encodeURIComponent(slug) + '/operations/plan', {
    runtime_id,
    action,
    idempotency_key: crypto.randomUUID(),
    ...extra
  });
  byId('plan-detail').textContent = JSON.stringify(currentPlan.plan, null, 2);
  const blocked = currentPlan.plan.dependency_findings.length > 0;
  byId('plan-message').textContent = blocked ? 'Dieser Plan ist blockiert.' : !context.execution_enabled ? 'Die Ausführung ist serverseitig deaktiviert.' : 'Prüfe die betroffenen Ressourcen und gib den Plan ausdrücklich frei.';
  byId('plan-execute').disabled = blocked || !context.execution_enabled;
  byId('plan-dialog').showModal();
}
async function executePlan() {
  if (!currentPlan) return;
  byId('plan-execute').disabled = true;
  try {
    await api('/operations/' + currentPlan.id + '/execute', {
      plan_hash: currentPlan.plan_hash,
      approved: true
    });
    byId('plan-message').textContent = 'Operation angenommen. Ausführung wird geprüft …';
    for (let i = 0; i < 450; i++) {
      await new Promise(r => setTimeout(r, 2000));
      const op = await api('/operations/' + currentPlan.id);
      byId('plan-detail').textContent = JSON.stringify(op, null, 2);
      if (['completed', 'failed', 'interrupted'].includes(op.status)) {
        byId('plan-message').textContent = op.status === 'completed' ? 'Ausführung und Prüfung abgeschlossen.' : 'Operation fehlgeschlagen oder unterbrochen. Laufzeit prüfen und neuen Plan anlegen.';
        await histories();
        if (selected) await selectService(selected);
        return;
      }
    }
    byId('plan-message').textContent = 'Operation läuft weiter. Status in der Operationsliste prüfen.';
  } catch (e) {
    showError(e);
    byId('plan-message').textContent = e.message;
  }
}
async function histories() {
  const [ops, events] = await Promise.all([api('/operations'), api('/management/activities')]);
  for (const [id, data] of [
      ['operation-list', ops],
      ['activity-list', events]
    ]) {
    byId(id).replaceChildren();
    if (!data.length) byId(id).append(node('p', 'Keine Einträge vorhanden.'));
    for (const row of data) {
      const e = node('details');
      e.append(node('summary', (row.action || '') + ' · ' + (row.status || row.actor) + ' · ' + row.created_at), node('pre', JSON.stringify(row, null, 2)));
      byId(id).append(e);
    }
  }
}
byId('search').addEventListener('input', catalog);
byId('refresh').addEventListener('click', () => refresh().catch(showError));
byId('plan-cancel').addEventListener('click', () => byId('plan-dialog').close());
byId('plan-execute').addEventListener('click', executePlan);
byId('storage-load').addEventListener('click', async () => {
  try {
    byId('storage-result').textContent = JSON.stringify(await api('/docker/storage/cleanup/plan', {}), null, 2);
  } catch (e) {
    showError(e);
  }
});
byId('policy-form').addEventListener('submit', async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api('/policies', {
      service_slug: f.get('service_slug'),
      rule_id: f.get('rule_id'),
      version: Number(f.get('version')),
      severity: f.get('severity'),
      actions: [f.get('action')],
      message: f.get('message')
    });
    await histories();
    if (selected) await selectService(selected);
  } catch (error) {
    showError(error);
  }
});
refresh().catch(showError);
