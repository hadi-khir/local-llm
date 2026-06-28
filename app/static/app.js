const appState = {
  authenticated: Boolean(window.__APP_BOOTSTRAP__?.authenticated),
  conversations: [],
  activeConversationId: null,
  activeMessages: [],
  isSending: false,
  isLiveStreaming: false,
  messagePollTimer: null,
  availableModels: [],
  selectedModel: null,
  defaultModel: null,
  ollamaStatus: "checking",
  statusError: "",
  pendingAttachments: [], // [{id, filename, content_type}]
};

const elements = {
  statusPill: document.querySelector("#status-pill"),
  loginCard: document.querySelector("#login-card"),
  loginForm: document.querySelector("#login-form"),
  loginError: document.querySelector("#login-error"),
  username: document.querySelector("#username"),
  password: document.querySelector("#password"),
  chatApp: document.querySelector("#chat-app"),
  logoutButton: document.querySelector("#logout-button"),
  newChatButton: document.querySelector("#new-chat-button"),
  conversationTitle: document.querySelector("#conversation-title"),
  conversationMeta: document.querySelector("#conversation-meta"),
  conversationList: document.querySelector("#conversation-list"),
  messageList: document.querySelector("#message-list"),
  composerForm: document.querySelector("#composer-form"),
  promptInput: document.querySelector("#prompt-input"),
  composerError: document.querySelector("#composer-error"),
  sendButton: document.querySelector("#send-button"),
  attachButton: document.querySelector("#attach-button"),
  fileInput: document.querySelector("#file-input"),
  attachmentChips: document.querySelector("#attachment-chips"),
  modelSelect: document.querySelector("#model-select"),
  modelSelectWrapper: document.querySelector("#model-select-wrapper"),
  sidebar: document.querySelector("#sidebar"),
  sidebarToggle: document.querySelector("#sidebar-toggle"),
  sidebarOverlay: document.querySelector("#sidebar-overlay"),
};

function createRequestId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderInlineMarkdown(text) {
  const escaped = escapeHtml(text);
  return escaped
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_match, label, url) => {
      const safeUrl = escapeHtml(url);
      return `<a href="${safeUrl}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
    })
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function renderMarkdownToHtml(markdown) {
  const source = String(markdown || "").replace(/\r\n/g, "\n");
  const lines = source.split("\n");
  const fragments = [];
  let paragraph = [];
  let listItems = [];
  let inCodeBlock = false;
  let codeLanguage = "";
  let codeLines = [];

  function flushParagraph() {
    if (!paragraph.length) {
      return;
    }
    fragments.push(`<p>${renderInlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  }

  function flushList() {
    if (!listItems.length) {
      return;
    }
    fragments.push(
      `<ul>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul>`,
    );
    listItems = [];
  }

  function flushCodeBlock() {
    const codeClass = codeLanguage ? ` class="language-${escapeHtml(codeLanguage)}"` : "";
    fragments.push(
      `<pre><code${codeClass}>${escapeHtml(codeLines.join("\n"))}</code></pre>`,
    );
    codeLines = [];
    codeLanguage = "";
  }

  for (const line of lines) {
    const fenceMatch = line.match(/^\s*```([\w+-]*)\s*$/);
    if (fenceMatch) {
      flushParagraph();
      flushList();
      if (inCodeBlock) {
        flushCodeBlock();
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
        codeLanguage = fenceMatch[1];
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    const listMatch = line.match(/^\s*[-*]\s+(.*)$/);
    if (listMatch) {
      flushParagraph();
      listItems.push(listMatch[1]);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    paragraph.push(line.trim());
  }

  flushParagraph();
  flushList();
  if (inCodeBlock) {
    flushCodeBlock();
  }

  return fragments.join("");
}

function renderMarkdown(target, markdown) {
  target.innerHTML = renderMarkdownToHtml(markdown);
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    credentials: "same-origin",
    ...options,
  });

  if (!response.ok) {
    let detail = "Request failed.";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      // ignore invalid JSON
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  return response.text();
}

function renderAuthState() {
  elements.loginCard.hidden = appState.authenticated;
  elements.chatApp.hidden = !appState.authenticated;
}

function renderConversations() {
  elements.conversationList.innerHTML = "";
  if (!appState.conversations.length) {
    const empty = document.createElement("p");
    empty.className = "status-pill";
    empty.textContent = "No conversations yet.";
    elements.conversationList.append(empty);
    return;
  }
  
  for (const conversation of appState.conversations) {
     const item = document.createElement("div");
     item.className = "conversation-item";
   
     const button = document.createElement("button");
     button.type = "button";
     button.className = "conversation-button";
     if (conversation.id === appState.activeConversationId) {
       button.classList.add("is-active");
     }
     const title = document.createElement("span");
     title.className = "conversation-button__title";
     title.textContent = conversation.title;
     button.append(title);
     if (conversation.model) {
       const meta = document.createElement("span");
       meta.className = "conversation-button__meta";
       meta.textContent = conversation.model;
       button.append(meta);
     }
     button.addEventListener("click", () => selectConversation(conversation.id));
   
     const deleteBtn = document.createElement("button");
     deleteBtn.type = "button";
     deleteBtn.className = "delete-button";
     deleteBtn.textContent = "✕";
     deleteBtn.title = "Delete conversation";
     deleteBtn.addEventListener("click", (e) => {
       e.stopPropagation();
       deleteConversation(conversation.id);
     });
   
    item.append(button, deleteBtn);
    elements.conversationList.append(item);
  }
}

function getActiveConversation() {
  return appState.conversations.find(
   (conversation) => conversation.id === appState.activeConversationId,
  ) || null;
}

function getActiveConversationModel() {
  return getActiveConversation()?.model || appState.defaultModel || null;
}

function renderStatusPill() {
  if (appState.statusError) {
   elements.statusPill.textContent = appState.statusError;
   return;
  }

  const rows = [];
  const activeModel = getActiveConversationModel();
  const inFlight = appState.activeMessages.some((message) =>
   message.role === "assistant" && ["pending", "streaming"].includes(message.status),
  );

  if (appState.activeConversationId && activeModel) {
   rows.push(["This chat", activeModel]);
  } else if (appState.selectedModel) {
   rows.push(["Next chat", appState.selectedModel]);
  }

  if (appState.defaultModel) {
   rows.push(["Default", appState.defaultModel]);
  }

  rows.push(["Ollama", appState.ollamaStatus || "unknown"]);
  if (inFlight) {
   rows.push(["Status", "Generating response"]);
  }

  elements.statusPill.innerHTML = rows
   .map(
     ([label, value]) =>
       `<span class="status-pill__row"><span class="status-pill__label">${escapeHtml(label)}</span><span class="status-pill__value">${escapeHtml(value)}</span></span>`,
   )
   .join("");
}

function renderConversationMeta() {
  const activeConversation = getActiveConversation();
  if (activeConversation) {
   elements.conversationMeta.textContent = `Model locked to ${activeConversation.model || appState.defaultModel || "default"}`;
  } else if (appState.selectedModel) {
   elements.conversationMeta.textContent = `New chat will use ${appState.selectedModel}`;
  } else if (appState.defaultModel) {
   elements.conversationMeta.textContent = `New chat will use ${appState.defaultModel}`;
  } else {
   elements.conversationMeta.textContent = "Select a model to start a new chat.";
  }
  renderStatusPill();
}

function createAssistantLoadingNode(message) {
  const container = document.createElement("div");
  container.className = "message-loading";

  const dots = document.createElement("span");
  dots.className = "message-loading__dots";
  dots.setAttribute("aria-hidden", "true");
  for (let index = 0; index < 3; index += 1) {
   dots.append(document.createElement("span"));
  }

  const label = document.createElement("span");
  label.className = "message-loading__label";
  label.textContent = message.status === "pending" ? "Starting response…" : "Generating response…";

  container.append(dots, label);
  return container;
}

function appendMessage(message) {
  const article = document.createElement("article");
  article.className = `message message--${message.role}`;
  article.dataset.messageId = String(message.id);
  setMessageContent(article, message);

  elements.messageList.append(article);
  return article;
}

function setMessageContent(node, message) {
  node.innerHTML = "";
  if (message.role === "assistant") {
   if (message.status === "failed") {
     const error = document.createElement("p");
     error.className = "message-error";
     error.textContent = message.error || "Generation failed.";
     node.append(error);
     return;
   }
   if (message.status !== "completed") {
     node.append(createAssistantLoadingNode(message));
     return;
   }
   if (message.content) {
     renderMarkdown(node, message.content);
     return;
   }
   return;
  }

  node.textContent = message.content;
}

function renderMessages(messages) {
  appState.activeMessages = messages;
  elements.messageList.innerHTML = "";
  for (const message of messages) {
    appendMessage(message);
  }
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
  renderStatusPill();
  scheduleMessagePolling();
}

function clearMessagePolling() {
  if (appState.messagePollTimer) {
    window.clearTimeout(appState.messagePollTimer);
    appState.messagePollTimer = null;
  }
}

function scheduleMessagePolling() {
  clearMessagePolling();
  if (appState.isLiveStreaming || !appState.activeConversationId) {
    return;
  }

  const hasInFlightMessage = appState.activeMessages.some((message) =>
    ["pending", "streaming"].includes(message.status),
  );
  if (!hasInFlightMessage) {
    return;
  }

  appState.messagePollTimer = window.setTimeout(async () => {
    appState.messagePollTimer = null;
    try {
      await loadConversationMessages(appState.activeConversationId);
    } catch (error) {
      scheduleMessagePolling();
    }
  }, 1500);
}

function setComposerError(message = "") {
  elements.composerError.hidden = !message;
  elements.composerError.textContent = message;
}

function setLoginError(message = "") {
  elements.loginError.hidden = !message;
  elements.loginError.textContent = message;
}

function updateSendingState(isSending) {
  appState.isSending = isSending;
  elements.sendButton.disabled = isSending;
  elements.promptInput.disabled = isSending;
  if (elements.attachButton) elements.attachButton.disabled = isSending;
  renderStatusPill();
}

function renderAttachmentChips() {
  if (!elements.attachmentChips) return;
  elements.attachmentChips.innerHTML = "";
  elements.attachmentChips.hidden = appState.pendingAttachments.length === 0;

  for (const att of appState.pendingAttachments) {
    const chip = document.createElement("div");
    chip.className = "attachment-chip";

    const icon = att.content_type.startsWith("image/") ? "🖼" :
                 att.content_type === "application/pdf" ? "📄" : "📎";

    const label = document.createElement("span");
    label.textContent = `${icon} ${att.filename}`;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "attachment-chip__remove";
    remove.textContent = "✕";
    remove.title = "Remove attachment";
    remove.addEventListener("click", () => {
      appState.pendingAttachments = appState.pendingAttachments.filter((a) => a.id !== att.id);
      renderAttachmentChips();
    });

    chip.append(label, remove);
    elements.attachmentChips.append(chip);
  }
}

async function handleFileSelect(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) return;

  // Reset input so the same file can be re-selected
  event.target.value = "";

  for (const file of files) {
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await fetch("/api/upload", {
        method: "POST",
        credentials: "same-origin",
        body: formData,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        setComposerError(payload.detail || "Upload failed.");
        continue;
      }
      const att = await response.json();
      appState.pendingAttachments.push(att);
      renderAttachmentChips();
    } catch {
      setComposerError("Upload failed — check your connection.");
    }
  }
}

async function bootstrap() {
  const health = await request("/api/health");
  appState.defaultModel = health.model || null;
  appState.ollamaStatus = health.ollama || "unknown";
  appState.statusError = "";
  renderStatusPill();

  const auth = await request("/api/auth/me");
  appState.authenticated = auth.authenticated;
  renderAuthState();
  if (appState.authenticated) {
    await Promise.all([refreshConversations(), refreshModels()]);
  }
}

async function refreshModels() {
  try {
    const data = await request("/api/models");
    appState.availableModels = data.models || [];
    appState.defaultModel = data.default || appState.defaultModel || null;
    appState.selectedModel = appState.selectedModel || appState.defaultModel || appState.availableModels[0] || null;
    renderModelSelect();
    appState.ollamaStatus = "ok";
    appState.statusError = "";
    renderConversationMeta();
  } catch {
    // non-fatal — model selector stays hidden
  }
}

function renderModelSelect() {
  const select = elements.modelSelect;
  if (!select) return;
  select.innerHTML = "";
  for (const name of appState.availableModels) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    if (name === appState.selectedModel) opt.selected = true;
    select.append(opt);
  }
  updateModelSelectVisibility();
}

function updateModelSelectVisibility() {
  if (!elements.modelSelectWrapper) return;
  // Only show selector when no active conversation (new chat)
  elements.modelSelectWrapper.hidden = Boolean(appState.activeConversationId);
  renderConversationMeta();
}

async function refreshConversations() {
  appState.conversations = await request("/api/conversations");
  renderConversations();
  renderConversationMeta();

  if (!appState.activeConversationId && appState.conversations.length) {
    await selectConversation(appState.conversations[0].id);
    return;
  }

  if (appState.activeConversationId) {
    const stillExists = appState.conversations.some(
      (conversation) => conversation.id === appState.activeConversationId,
    );
    if (stillExists) {
      return;
    }
  }

  if (!appState.conversations.length) {
    resetConversationView();
  }
}

async function loadConversationMessages(conversationId) {
  const messages = await request(`/api/conversations/${conversationId}/messages`);
  renderMessages(messages);
  return messages;
}

async function selectConversation(conversationId) {
  appState.activeConversationId = conversationId;
  const active = appState.conversations.find(
    (conversation) => conversation.id === conversationId,
  );
  elements.conversationTitle.textContent = active?.title || "Conversation";
  renderConversations();
  updateModelSelectVisibility();
  toggleSidebar(false);
  await loadConversationMessages(conversationId);
}

async function handleLogin(event) {
  event.preventDefault();
  setLoginError();
  try {
    await request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: elements.username.value,
        password: elements.password.value,
      }),
    });
    appState.authenticated = true;
    renderAuthState();
    elements.password.value = "";
    await Promise.all([refreshConversations(), refreshModels()]);
  } catch (error) {
    setLoginError(error.message);
  }
}

async function handleLogout() {
  clearMessagePolling();
  await request("/api/auth/logout", { method: "POST" });
  appState.authenticated = false;
  appState.conversations = [];
  appState.activeConversationId = null;
  appState.activeMessages = [];
  renderAuthState();
  renderConversations();
  elements.messageList.innerHTML = "";
  renderConversationMeta();
}

function resetConversationView() {
  clearMessagePolling();
  appState.activeConversationId = null;
  appState.activeMessages = [];
  elements.conversationTitle.textContent = "New conversation";
  elements.messageList.innerHTML = "";
  setComposerError();
  updateModelSelectVisibility();
}

function getMessageById(messageId) {
  return appState.activeMessages.find((message) => message.id === messageId) || null;
}

async function handleSend(event) {
  event.preventDefault();
  if (appState.isSending) {
    return;
  }

  const prompt = elements.promptInput.value.trim();
  if (!prompt) {
    setComposerError("Please enter a prompt.");
    return;
  }

  const requestId = createRequestId();
  const attachmentIds = appState.pendingAttachments.map((a) => a.id);
  setComposerError();
  clearMessagePolling();
  updateSendingState(true);
  appState.isLiveStreaming = true;
  elements.promptInput.value = "";
  appState.pendingAttachments = [];
  renderAttachmentChips();

  let assistantMessageId = null;
  let conversationId = appState.activeConversationId;

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        conversation_id: appState.activeConversationId,
        request_id: requestId,
        model: appState.activeConversationId ? null : (elements.modelSelect?.value || appState.selectedModel),
        attachment_ids: attachmentIds.length ? attachmentIds : null,
      }),
    });

    if (!response.ok || !response.body) {
      throw new Error("Unable to start streaming response.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        const eventMatch = part.match(/^event: (.+)$/m);
        const dataMatch = part.match(/^data: (.+)$/m);
        if (!eventMatch || !dataMatch) {
          continue;
        }

        const eventName = eventMatch[1];
        const payload = JSON.parse(dataMatch[1]);

        if (eventName === "conversation") {
          conversationId = payload.conversation_id;
          assistantMessageId = payload.assistant_message_id;
          appState.activeConversationId = conversationId;
          elements.conversationTitle.textContent = payload.title;
          await refreshConversations();
          renderConversations();
          updateModelSelectVisibility();
          toggleSidebar(false);
          await loadConversationMessages(conversationId);
        } else if (eventName === "chunk" && assistantMessageId) {
          const targetMessage = getMessageById(assistantMessageId);
          if (targetMessage) {
            targetMessage.status = "streaming";
            const node = elements.messageList.querySelector(`[data-message-id="${assistantMessageId}"]`);
            if (node) {
              setMessageContent(node, targetMessage);
            }
            renderStatusPill();
          }
        } else if (eventName === "error") {
          throw new Error(payload.detail);
        } else if (eventName === "done" && conversationId) {
          await loadConversationMessages(conversationId);
        }
      }
    }
  } catch (error) {
    if (conversationId) {
      const messages = await loadConversationMessages(conversationId).catch(() => null);
      const assistantMessage = assistantMessageId ? messages?.find((message) => message.id === assistantMessageId) : null;
      if (!assistantMessage) {
        setComposerError(error.message);
      }
    } else {
      setComposerError(error.message);
    }
  } finally {
    appState.isLiveStreaming = false;
    updateSendingState(false);
    scheduleMessagePolling();
  }
}

function toggleSidebar(open) {
  const isOpen = open ?? !elements.sidebar.classList.contains("is-open");
  elements.sidebar.classList.toggle("is-open", isOpen);
  elements.sidebarOverlay.classList.toggle("is-open", isOpen);
}

elements.loginForm.addEventListener("submit", handleLogin);
elements.logoutButton.addEventListener("click", handleLogout);
elements.newChatButton.addEventListener("click", resetConversationView);
elements.composerForm.addEventListener("submit", handleSend);
elements.sidebarToggle.addEventListener("click", () => toggleSidebar());
elements.sidebarOverlay.addEventListener("click", () => toggleSidebar(false));
elements.modelSelect?.addEventListener("change", () => {
  appState.selectedModel = elements.modelSelect.value;
  renderConversationMeta();
});
elements.attachButton?.addEventListener("click", () => elements.fileInput?.click());
elements.fileInput?.addEventListener("change", handleFileSelect);

bootstrap().catch((error) => {
  appState.statusError = `Startup error: ${error.message}`;
  renderStatusPill();
});

async function deleteConversation(conversationId) {

	if (!confirm("Delete this conversation?")) {
		return;
	}

	await request(`/api/conversations/${conversationId}`, { method: "DELETE" });
	if (appState.activeConversationId === conversationId) {
		resetConversationView();
	}

	await refreshConversations();
}
