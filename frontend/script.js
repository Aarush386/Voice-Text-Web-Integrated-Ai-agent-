// ============ CONFIG ============
const API_BASE = "https://voice-text-web-integrated-ai-agent-production.up.railway.app";

// ============ DOM ELEMENTS ============
const micButton = document.getElementById('micButton');
const micArea = document.getElementById('micArea');
const micLabel = document.getElementById('micLabel');
const transcript = document.getElementById('transcript');
const chips = document.getElementById('chips');
const restartBtn = document.getElementById('restartBtn');
const toast = document.getElementById('toast');
const textInput = document.getElementById('textInput');
const sendButton = document.getElementById('sendButton');

// ============ SESSION ============
function getOrCreateSession() {
  let sid = localStorage.getItem("sessionId");
  if (!sid) {
    sid = Math.random().toString(36).slice(2, 9);
    localStorage.setItem("sessionId", sid);
  }
  return sid;
}
let sessionId = getOrCreateSession();

// ============ PHONE AUTOFILL ============
const urlParams = new URLSearchParams(window.location.search);
let autoPhone = urlParams.get("phone") || null;

if (autoPhone) {
  // ensure + prefix and digits only after +
  autoPhone = autoPhone.trim();
  autoPhone = autoPhone.replace(/^whatsapp:/, "");
  const digits = autoPhone.replace(/[^\d]/g, "");
  if (digits) {
    autoPhone = "+" + digits;
  } else {
    autoPhone = null;
  }
}

// ============ CHAT HISTORY ============
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

// ============ UI HELPERS ============
function showToast(msg, timeout = 3000) {
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), timeout);
}

function addMessage(text, who = 'agent', ts = null, loadingHistory = false) {
  const wrapper = document.createElement('div');
  wrapper.className = 'message ' + (who === 'user' ? 'user' : 'agent');

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  wrapper.appendChild(bubble);

  if (who === 'agent') {
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    wrapper.appendChild(avatar);
  }

  const timeEl = document.createElement('div');
  timeEl.className = 'timestamp';
  timeEl.textContent = ts || new Date().toLocaleTimeString();
  wrapper.appendChild(timeEl);

  transcript.appendChild(wrapper);
  transcript.scrollTop = transcript.scrollHeight;

  if (!loadingHistory) saveMessage(text, who);
}

// Show media (QR/catalog/location)
function addMedia(url, type = "image") {
  const wrapper = document.createElement('div');
  wrapper.className = 'message agent';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  if (type === "image") {
    const img = document.createElement('img');
    img.src = url;
    img.className = 'media-image';
    bubble.appendChild(img);
  } else {
    const a = document.createElement('a');
    a.href = url;
    a.target = "_blank";
    a.textContent = "Open link";
    bubble.appendChild(a);
  }

  wrapper.appendChild(bubble);

  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  wrapper.appendChild(avatar);

  const timeEl = document.createElement('div');
  timeEl.className = 'timestamp';
  timeEl.textContent = new Date().toLocaleTimeString();
  wrapper.appendChild(timeEl);

  transcript.appendChild(wrapper);
  transcript.scrollTop = transcript.scrollHeight;
}

// ============ BACKEND ============
async function sendToBackend(msg) {
  try {
    const payload = {
      session_id: sessionId,
      frontend_phone: autoPhone,
      messages: [
        { role: "user", parts: [{ text: msg }] }
      ]
    };

    const res = await fetch(`${API_BASE}/api/text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      showToast("Server error");
      return;
    }

    const data = await res.json();

    if (data.reply_text) {
      addMessage(data.reply_text, 'agent');

      if (data.reply_audio_url) {
        const audio = new Audio(data.reply_audio_url);
        audio.play().catch(() => { });
      } else {
        const utter = new SpeechSynthesisUtterance(data.reply_text);
        utter.rate = 1.3;
        speechSynthesis.cancel();
        speechSynthesis.speak(utter);
      }
    }

    const s = data.structured || {};
    if (s.qr_url) addMedia(s.qr_url, "image");
    if (s.catalog_url) addMedia(s.catalog_url, "image");
    if (s.location_url) addMedia(s.location_url, "link");

  } catch (err) {
    showToast("Network error");
  }
}

// ============ TEXT SENDING ============
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

// ============ QUICK CHIPS ============
chips.addEventListener('click', async (e) => {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  const value = chip.dataset.value;
  addMessage(value, 'user');
  await sendToBackend(value);
});

// ============ RESTART ============
restartBtn.addEventListener('click', () => {
  transcript.innerHTML = '';
  localStorage.removeItem("chatHistory");

  sessionId = Math.random().toString(36).slice(2, 9);
  localStorage.setItem("sessionId", sessionId);

  addMessage(
    "Hello! Welcome to Aarush Ai solutions, we specialize in building useful AI agents for businesses that can generate leads, book services, and help with customer support. I am an AI voice assistant. Want your own Custom AI Agent? You can book a call with me to discuss your agent and custom features — or directly book an AI agent for your business.",
    'agent'
  );
});

// ============ VOICE ============
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
      } catch (err) {
        showToast("Voice error");
      }
      stream.getTracks().forEach(t => t.stop());
    };

    mediaRecorder.start();
    isListening = true;
    micArea.classList.add('listening');
    micLabel.textContent = "Listening...";
  } catch {
    showToast("Microphone blocked");
  }
});

micButton.addEventListener('pointerup', () => {
  if (!isListening) return;
  mediaRecorder.stop();
  isListening = false;
  micArea.classList.remove('listening');
  micLabel.textContent = "Hold to talk";
});

async function sendAudioToServer(blob) {
  const fd = new FormData();
  fd.append('audio', blob, 'speech.webm');
  fd.append('session', sessionId);
  if (autoPhone) fd.append('frontend_phone', autoPhone);

  const res = await fetch(`${API_BASE}/api/voice`, {
    method: 'POST',
    body: fd
  });

  if (!res.ok) {
    showToast("Server error");
    return;
  }

  const j = await res.json();

  if (j.transcript) addMessage(j.transcript, 'user');
  if (j.reply_text) {
    addMessage(j.reply_text, 'agent');
    if (j.reply_audio_url) {
      const a = new Audio(j.reply_audio_url);
      a.play().catch(() => { });
    }
  }

  const s = j.structured || {};
  if (s.qr_url) addMedia(s.qr_url, "image");
  if (s.catalog_url) addMedia(s.catalog_url, "image");
  if (s.location_url) addMedia(s.location_url, "link");
}

// ============ INIT ============
loadChatHistory();
if (transcript.children.length === 0) {
  addMessage(
    "Hello! Welcome to Aarush Ai solutions, we specialize in building useful AI agents for businesses that can generate leads, book services, and help with customer support. I am an AI voice assistant. Want your own Custom AI Agent? You can book a call with me to discuss your agent and custom features — or directly book an AI agent for your business.",
    'agent'
  );
}
