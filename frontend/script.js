const API_BASE = "https://voice-text-web-integrated-ai-agent-production.up.railway.app";

const micButton = document.getElementById('micButton');
const micArea = document.getElementById('micArea');
const micLabel = document.getElementById('micLabel');
const transcript = document.getElementById('transcript');
const chips = document.getElementById('chips');
const restartBtn = document.getElementById('restartBtn');
const toast = document.getElementById('toast');
const textInput = document.getElementById('textInput');
const sendButton = document.getElementById('sendButton');
function getOrCreateSession() {
  let sid = localStorage.getItem("sessionId");
  if (!sid) {
    sid = Math.random().toString(36).slice(2, 9);
    localStorage.setItem("sessionId", sid);
  }
  return sid;
}

let sessionId = getOrCreateSession();


const urlParams = new URLSearchParams(window.location.search);
let autoPhone = urlParams.get("phone") || null;

if (autoPhone && !autoPhone.startsWith("+")) {
  autoPhone = "+" + autoPhone.replace(/[^\d]/g, "");
}

function loadChatHistory() {
  const saved = localStorage.getItem("chatHistory");
  if (!saved) return;
  const items = JSON.parse(saved);
  items.forEach(msg => addMessage(msg.text, msg.who, msg.time, true));
}

function saveMessage(text, who) {
  const existing = JSON.parse(localStorage.getItem("chatHistory") || "[]");
  existing.push({ text, who, time: new Date().toLocaleTimeString() });
  localStorage.setItem("chatHistory", JSON.stringify(existing));
}

function showToast(msg, timeout = 3000) {
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), timeout);
}

function addMessage(text, who = 'agent', ts = null, loadingHistory = false) {
  const el = document.createElement('div');
  el.className = 'message ' + (who === 'user' ? 'user' : 'agent');

  if (who === 'agent') {
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    el.appendChild(avatar);
  }

  const inner = document.createElement('div');
  inner.className = 'bubble';
  inner.textContent = text;
  el.appendChild(inner);

  const timeEl = document.createElement('div');
  timeEl.className = 'timestamp';
  timeEl.textContent = ts || new Date().toLocaleTimeString();
  el.appendChild(timeEl);

  transcript.appendChild(el);
  transcript.scrollTop = transcript.scrollHeight;

  if (!loadingHistory) saveMessage(text, who);
}

function addMedia(url, type = "image") {
  const el = document.createElement('div');
  el.className = "message agent";

  if (type === "image") {
    const img = document.createElement("img");
    img.src = url;
    img.className = "media-image";
    el.appendChild(img);
  } else {
    const a = document.createElement("a");
    a.href = url;
    a.textContent = "Open link";
    a.target = "_blank";
    el.appendChild(a);
  }

  const timeEl = document.createElement('div');
  timeEl.className = "timestamp";
  timeEl.textContent = new Date().toLocaleTimeString();
  el.appendChild(timeEl);

  transcript.appendChild(el);
  transcript.scrollTop = transcript.scrollHeight;
}

async function sendToBackend(msg) {
  try {
    const payload = {
      session_id: sessionId,
      frontend_phone: autoPhone,
      messages: [
        {
          role: "user",
          parts: [{ text: msg }]
        }
      ]
    };

    const res = await fetch(`${API_BASE}/api/text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (data.reply_text) {
      addMessage(data.reply_text, "agent");

      if (data.reply_audio_url) {
        new Audio(data.reply_audio_url).play();
      } else {
        const speak = new SpeechSynthesisUtterance(data.reply_text);
        speak.rate = 1.35;
        speechSynthesis.cancel();
        speechSynthesis.speak(speak);
      }
    }

    const s = data.structured || {};
    if (s.qr_url) addMedia(s.qr_url);
    if (s.catalog_url) addMedia(s.catalog_url);
    if (s.location_url) addMedia(s.location_url, "link");

  } catch (err) {
    showToast("Server error");
  }
}

async function handleTextMessage() {
  const message = textInput.value.trim();
  if (!message) return;

  addMessage(message, 'user');
  textInput.value = '';
  await sendToBackend(message);
}

sendButton.addEventListener('click', handleTextMessage);
textInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') handleTextMessage();
});

chips.addEventListener('click', async (e) => {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  const value = chip.dataset.value;
  addMessage(value, 'user');
  await sendToBackend(value);
});


restartBtn.addEventListener('click', () => {
  transcript.innerHTML = '';
  localStorage.removeItem("chatHistory");

  sessionId = Math.random().toString(36).slice(2, 9);
  localStorage.setItem("sessionId", sessionId);

  addMessage(
    'Hello! Welcome to Aarush Ai solutions...',
    'agent'
  );
});

let mediaRecorder = null;
let audioChunks = [];
let isListening = false;

micButton.addEventListener('pointerdown', async (e) => {
  e.preventDefault();
  if (isListening) return;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];

    mediaRecorder.ondataavailable = ev => {
      if (ev.data.size > 0) audioChunks.push(ev.data);
    };

    mediaRecorder.onstop = async () => {
      const blob = new Blob(audioChunks, { type: 'audio/webm' });
      addMessage('... (voice message)', 'user');

      try {
        await sendAudioToServer(blob);
      } catch {
        showToast("Voice processing error");
      }

      stream.getTracks().forEach(t => t.stop());
    };

    mediaRecorder.start();
    isListening = true;
    micArea.className = "mic-state-listening";
    micLabel.textContent = "Listening...";

  } catch {
    showToast("Microphone blocked");
  }
});

micButton.addEventListener('pointerup', () => {
  if (!isListening) return;
  mediaRecorder.stop();
  isListening = false;
});

async function sendAudioToServer(blob) {
  const fd = new FormData();
  fd.append('audio', blob, 'speech.webm');
  fd.append('session', sessionId);
  if (autoPhone) fd.append("frontend_phone", autoPhone);

  const res = await fetch(`${API_BASE}/api/voice`, {
    method: 'POST',
    body: fd
  });

  const j = await res.json();

  if (j.transcript) addMessage(j.transcript, 'user');

  if (j.reply_text) {
    addMessage(j.reply_text, 'agent');
    if (j.reply_audio_url) new Audio(j.reply_audio_url).play();
  }
}

loadChatHistory();

if (transcript.children.length === 0) {
  addMessage(
    'Hello! Welcome to Aarush Ai solutions...',
    'agent'
  );
}
