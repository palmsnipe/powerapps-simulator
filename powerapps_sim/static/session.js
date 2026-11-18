'use strict';

let checkingSession = false;
let syncingSession = false;
const sessionStatus = $('session-status');
const syncSessionButton = $('sync-session');

function sessionChanged(session) {
  return project.project_path !== session.project_path || project.revision !== session.revision ||
    project.preview_generation !== session.preview_generation;
}

function showSession(session) {
  const preview = session.pending_source ? 'Preview awaiting restart' :
    session.preview_started ? 'Preview running' : 'Preview ready to start';
  const mcp = session.mcp_attached ? `${session.mcp_attached} MCP connected` : 'No MCP client attached';
  const parts = [session.project_id, session.revision.slice(0, 8), preview, mcp];
  if (session.mcp_needs_rebind) parts.push(`${session.mcp_needs_rebind} awaiting MCP rebind`);
  if (syncSessionButton.hidden === false) parts.push('Browser has a local draft');
  const label = parts.join(' · ');
  if (sessionStatus.textContent !== label) sessionStatus.textContent = label;
  sessionStatus.title = session.revision;
  $('restart-button').textContent = session.preview_started ? 'Restart app' : 'Start preview';
}

async function syncSharedSession(session, confirmedDraft = null) {
  const hasUnconfirmedDraft = () => dirty && $('source-editor').value !== confirmedDraft;
  if (hasUnconfirmedDraft()) {
    syncSessionButton.hidden = false;
    showSession(session);
    return;
  }
  const summary = await api('/api/project');
  const params = new URLSearchParams({project: summary.project_path, generation: summary.preview_generation});
  const switched = summary.project_path !== project.project_path;
  const selection = !switched && (editorSelection?.startsWith('app:') || summary.documents.includes(editorSelection)) ?
    editorSelection : summary.screens[0]?.source || summary.documents[0];
  const source = selection.startsWith('app:') ? null :
    await api('/api/source?' + new URLSearchParams({...Object.fromEntries(params), revision: summary.revision, name: selection}));
  const snapshot = await api('/api/state?' + params);
  const projects = await api('/api/projects');
  if (hasUnconfirmedDraft() || document.querySelector('dialog[open]')) return;
  if (switched) {
    editorSelection = null;
    currentList = null;
    document.querySelector('[data-view="build"]').click();
  }
  dirty = false;
  await refreshProject(summary, projects);
  state = snapshot;
  await selectEditor(selection, source);
  renderState();
  syncSessionButton.hidden = true;
  status('Synced ' + project.title);
}

async function checkSharedSession() {
  if (!project || checkingSession || syncingSession || document.hidden) return;
  checkingSession = true;
  try {
    const session = await api('/api/session');
    showSession(session);
    if (!sessionChanged(session)) {
      syncSessionButton.hidden = true;
      return;
    }
    if (document.querySelector('dialog[open]')) return;
    syncingSession = true;
    await enqueue(() => syncSharedSession(session), {acrossSessions: true});
  } catch {
    sessionStatus.textContent = 'Local session unavailable';
  } finally {
    checkingSession = false;
    syncingSession = false;
  }
}

setInterval(checkSharedSession, 1500);
window.addEventListener('focus', () => checkSharedSession());
syncSessionButton.onclick = () => {
  if (dirty && !window.confirm('Discard the unsaved source draft and sync the shared session?')) return;
  const confirmedDraft = $('source-editor').value;
  enqueue(async () => {
    const session = await api('/api/session');
    if (sessionChanged(session)) {
      await syncSharedSession(session, confirmedDraft);
    }
  }, {acrossSessions: true});
};

$('bundle-button').onclick = () => {
  $('bundle-records').checked = false;
  $('bundle-dialog').showModal();
};

async function downloadProjectExport(path, params, filename) {
  const query = new URLSearchParams({project: project.project_path, ...params});
  const response = await fetch(path + '?' + query);
  if (!response.ok) throw new Error((await response.json()).error);
  const url = URL.createObjectURL(await response.blob());
  element('a', {href: url, download: filename}).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$('export-source').onclick = action(async () => {
  await downloadProjectExport('/api/export', {}, 'powerapps-source.zip');
});

$('download-bundle').onclick = action(async () => {
  const button = $('download-bundle');
  button.disabled = true;
  try {
    const filename = project.project_path.split(/[\\/]/).at(-1) + '.pasim';
    await downloadProjectExport('/api/export/project-bundle', {records: $('bundle-records').checked ? '1' : '0'}, filename);
    $('bundle-dialog').close();
    status('Project bundle downloaded');
  } finally {
    button.disabled = false;
  }
});
