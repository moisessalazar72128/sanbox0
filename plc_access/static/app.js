const el = id => document.getElementById(id);
let submitting = false;
async function refresh() {
  try {
    const response = await fetch('/api/status');
    if (!response.ok) throw new Error('Authentication or relay unavailable');
    const data = await response.json();
    const values = data.sample?.values;
    el('connection').textContent = data.fresh ? 'Gateway connected · fresh data' : 'STALE / OFFLINE · do not rely on displayed values';
    el('connection').className = data.fresh ? 'good' : 'bad';
    el('temperature').textContent = values ? `${values.temperature_c.toFixed(1)} °C` : '—';
    el('running').textContent = values ? (values.running ? 'Running' : 'Stopped') : '—';
    el('setpoint').textContent = values ? `${values.setpoint_c.toFixed(1)} °C` : '—';
    el('identity').textContent = `Signed in: ${data.user.name} · ${data.user.role}`;
    el('quality').textContent = `Sample age: ${data.age_seconds === null ? 'no sample' : data.age_seconds.toFixed(1) + ' s'} · relay writes: ${data.writes_enabled ? 'enabled' : 'disabled'} · gateway writes: ${data.sample?.writable ? 'enabled' : 'disabled'}`;
    el('write').disabled = submitting || !(data.fresh && data.writes_enabled && data.sample?.writable && data.user.role === 'operator');
    if (data.command) el('result').textContent = `Command ${data.command.id}: ${data.command.status}${data.command.status === 'delivered' ? ' (outcome unknown until acknowledged)' : ''}`;
  } catch (error) {
    el('connection').textContent = error.message;
    el('connection').className = 'bad';
    el('write').disabled = true;
  }
}
el('write').addEventListener('click', async () => {
  if (!el('value').reportValidity()) return;
  if (!confirm('Apply this setpoint to the configured device?')) return;
  submitting = true;
  el('write').disabled = true;
  try {
    const response = await fetch('/api/setpoint', {method:'POST', headers:{'Content-Type':'application/json','X-PLC-Action':'setpoint'}, body:JSON.stringify({value:Number(el('value').value)})});
    const body = await response.json();
    el('result').textContent = response.ok ? `Queued ${body.id}` : String(body.detail);
  } catch { el('result').textContent = 'Request failed. Check status before taking further action.'; }
  finally { submitting = false; }
});
refresh();
setInterval(refresh, 2000);
