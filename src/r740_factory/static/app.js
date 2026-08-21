const token = document.querySelector('#token');
const model = document.querySelector('#model');
const status = document.querySelector('#status');
const messages = document.querySelector('#messages');
const send = document.querySelector('#send');
const conversation = [];
const MAX_HISTORY_MESSAGES = 20;
const MAX_HISTORY_CHARACTERS = 32000;
token.value = sessionStorage.getItem('r740-token') || '';
model.value = sessionStorage.getItem('r740-model') || 'local-model';

function addMessage(role, text, error = false) {
  const node = document.createElement('div');
  node.className = `message ${error ? 'error' : role}`;
  node.textContent = text;
  messages.append(node);
  messages.scrollTop = messages.scrollHeight;
}

document.querySelector('#save').addEventListener('click', () => {
  sessionStorage.setItem('r740-token', token.value.trim());
  sessionStorage.setItem('r740-model', model.value.trim());
  addMessage('assistant', 'Credentials kept for this tab.');
});

document.querySelector('#reset').addEventListener('click', () => {
  conversation.length = 0;
  messages.replaceChildren();
  addMessage('assistant', 'New conversation started.');
});

function boundedHistory() {
  let total = 0;
  const selected = [];
  for (let index = conversation.length - 1; index >= 0 && selected.length < MAX_HISTORY_MESSAGES; index -= 1) {
    const item = conversation[index];
    total += item.content.length;
    if (total > MAX_HISTORY_CHARACTERS) break;
    selected.unshift(item);
  }
  return selected;
}

async function refreshStatus() {
  try {
    const response = await fetch('/api/v1/info', {cache: 'no-store'});
    const info = await response.json();
    status.textContent = info.inference_configured ? 'Backend configured' : 'Backend not configured';
    status.className = `status ${info.inference_configured ? 'ok' : 'bad'}`;
  } catch (_) {
    status.textContent = 'Control plane unavailable';
    status.className = 'status bad';
  }
}

document.querySelector('#chat').addEventListener('submit', async (event) => {
  event.preventDefault();
  const prompt = document.querySelector('#prompt');
  const value = prompt.value.trim();
  const secret = token.value.trim();
  if (!secret) { addMessage('error', 'Enter the administrator token first.', true); return; }
  if (!value) return;
  addMessage('user', value);
  conversation.push({role: 'user', content: value});
  prompt.value = '';
  send.disabled = true;
  try {
    const response = await fetch('/api/v1/chat/completions', {
      method: 'POST',
      headers: {'Authorization': `Bearer ${secret}`, 'Content-Type': 'application/json'},
      body: JSON.stringify({model: model.value.trim() || 'local-model', messages: boundedHistory()})
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    const content = payload?.choices?.[0]?.message?.content;
    if (typeof content !== 'string' || !content.trim()) throw new Error('Backend returned no visible response');
    addMessage('assistant', content.trim());
    conversation.push({role: 'assistant', content: content.trim()});
  } catch (error) {
    conversation.pop();
    addMessage('error', `Error: ${error.message}`, true);
  } finally { send.disabled = false; }
});

refreshStatus();
