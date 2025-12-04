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

// ============ SESSION (sessionStorage so tab close wipes it) ============
function getOrCreateSession() {
  let sid = sessionStorage.getItem("sessionId");
  if (!sid) {
    sid = Math.random().toString(36).slice(2, 9);
    sessionStorage.setItem("sessionId", sid);
  }
  return sid;
}
let sessionId = getOrCreateSession();

// wipe session on tab close (extra safety)
window.addEventListener("beforeunload", () => {
  sessionStorage.removeItem("sessionId");
  sessionStorage.removeItem("chatHistory");
});

// ============ PHONE AUTOFILL ============
const urlParams = new URLSearchParams(window.location.search);
let autoPhone = urlParams.get("phone") || null;

if (autoPhone) {
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
  const saved = sessionStorage.getItem("chatHistory");
  if (!saved) return;
  const items = JSON.parse(saved);
  items.forEach(msg => addMessage(msg.text, msg.who, msg.time, true));
}

function saveMessage(text, who) {
  const existing = JSON.parse(sessionStorage.getItem("chatHistory") || "[]");
  existing.push({ text, who, time: new Date().toLocaleTimeString() });
  sessionStorage.setItem("chatHistory", JSON.stringify(existing));
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

  if (who === 'agent') {
    // avatar first so it appears on the LEFT
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    wrapper.appendChild(avatar);

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;
    wrapper.appendChild(bubble);
  } else {
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;
    wrapper.appendChild(bubble);
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

  // avatar on LEFT
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  wrapper.appendChild(avatar);

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

  const timeEl = document.createElement('div');
  timeEl.className = 'timestamp';
  timeEl.textContent = new Date().toLocaleTimeString();
  wrapper.appendChild(timeEl);

  transcript.appendChild(wrapper);
  transcript.scrollTop = transcript.scrollHeight;
}

// ============ SPEECH SYNTHESIS (slower & stable) ============
let selectedVoice = null;

function initVoices() {
  const voices = speechSynthesis.getVoices();
  if (!voices || !voices.length) return;
  selectedVoice =
    voices.find(v => v.lang && v.lang.toLowerCase().startsWith("en-in")) ||
    voices.find(v => v.lang && v.lang.toLowerCase().startsWith("en")) ||
    voices[0];
}
speechSynthesis.onvoiceschanged = initVoices;
initVoices();

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
      } else if ('speechSynthesis' in window) {
        const utter = new SpeechSynthesisUtterance(data.reply_text);
        utter.rate = 0.9; // slower, more natural
        if (selectedVoice) utter.voice = selectedVoice;
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
  sessionStorage.removeItem("chatHistory");
  sessionStorage.removeItem("sessionId");

  sessionId = getOrCreateSession();

  addMessage(
    "Hello! Welcome to Aarush Ai solutions, we specialize in building useful AI agents for businesses that can generate leads, book services, and help with customer support. I am an AI voice assistant. Want your own Custom AI Agent? You can book a call with me to discuss your agent and custom features — or directly book an AI agent for your business.",
    'agent'
  );
});

// ============ VOICE INPUT (Web Speech API, no backend STT) ============
let recognition = null;
let isListening = false;

function initRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const rec = new SR();
  rec.lang = "en-IN"; // better for you; still understands English globally
  rec.continuous = false;
  rec.interimResults = false;
  return rec;
}

micButton.addEventListener('pointerdown', (e) => {
  e.preventDefault();
  if (isListening) return;

  if (!recognition) {
    recognition = initRecognition();
    if (!recognition) {
      showToast("Voice input not supported in this browser");
      return;
    }

    recognition.onstart = () => {
      isListening = true;
      micArea.classList.add('listening');
      micLabel.textContent = "Listening...";
    };

    recognition.onend = () => {
      isListening = false;
      micArea.classList.remove('listening');
      micLabel.textContent = "Hold to talk";
    };

    recognition.onerror = (ev) => {
      isListening = false;
      micArea.classList.remove('listening');
      micLabel.textContent = "Hold to talk";
      if (ev.error !== "no-speech") {
        showToast("Voice error");
      }
    };

    recognition.onresult = async (ev) => {
      if (!ev.results || !ev.results[0] || !ev.results[0][0]) return;
      const text = ev.results[0][0].transcript;
      addMessage(text, 'user');
      await sendToBackend(text);
    };
  }

  try {
    recognition.start();
  } catch {
    // start may throw if already started; ignore
  }
});

micButton.addEventListener('pointerup', (e) => {
  e.preventDefault();
  if (!recognition || !isListening) return;
  try {
    recognition.stop();
  } catch {
    // ignore
  }
});

// ============ INIT ============
loadChatHistory();
if (transcript.children.length === 0) {
  addMessage(
    "Hello! Welcome to Aarush Ai solutions, we specialize in building useful AI agents for businesses that can generate leads, book services, and help with customer support. I am an AI voice assistant. Want your own Custom AI Agent? You can book a call with me to discuss your agent and custom features — or directly book an AI agent for your business.",
    'agent'
  );
}
