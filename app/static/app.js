const appState = {
  authenticated: Boolean(window.__APP_BOOTSTRAP__?.authenticated),
  conversations: [],
  activeConversationId: null,
  activeMessages: [],
  isSending: false,
  isLiveStreaming: false,
  messagePollTimer: null,
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
  conversationList: document.querySelector("#conversation-list"),
  messageList: document.querySelector("#message-list"),
  composerForm: document.querySelector("#composer-form"),
  promptInput: document.querySelector("#prompt-input"),
  composerError: document.querySelector("#composer-error"),
  sendButton: document.querySelector("#send-button"),
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
    const button = document.createElement("button");
    button.type = "button";
    button.className = "conversation-button";
    if (conversation.id === appState.activeConversationId) {
      button.classList.add("is-active");
    }
    button.textContent = conversation.title;
    button.addEventListener("click", () => selectConversation(conversation.id));
    elements.conversationList.append(button);
  }
}

function getAssistantPlaceholder(message) {
  if (message.status === "failed") {
    return message.error || "Generation failed.";
  }
  if (message.status === "pending") {
    return "Thinking…";
  }
  if (message.status === "streaming" && !message.content) {
    return "Thinking…";
  }
  return "";
}

function appendMessage(message) {
  const article = document.createElement("article");
  article.className = `message message--${message.role}`;
  article.dataset.messageId = String(message.id);
  setMessageContent(article, message);

  if (message.status !== "completed") {
    const status = document.createElement("p");
    status.className = "message-status";
    status.textContent =
      message.status === "failed" ? message.error || "Failed" : "In progress…";
    article.append(status);
  }

  elements.messageList.append(article);
  return article;
}

function setMessageContent(node, message) {
  if (message.role === "assistant") {
    const placeholder = getAssistantPlaceholder(message);
    node.dataset.rawContent = message.content || "";
    if (message.content) {
      renderMarkdown(node, message.content);
      return;
    }
    node.textContent = placeholder;
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
  scheduleMessagePolling();
}

function updateMessageNode(messageId, nextContent) {
  const node = elements.messageList.querySelector(`[data-message-id="${messageId}"]`);
  if (!node) {
    return;
  }

  const message = appState.activeMessages.find((entry) => entry.id === messageId);
  if (!message) {
    return;
  }

  message.content = nextContent;
  message.status = "streaming";
  node.innerHTML = "";
  setMessageContent(node, message);
  const status = document.createElement("p");
  status.className = "message-status";
  status.textContent = "In progress…";
  node.append(status);
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
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
      setComposerError(error.message);
      scheduleMessagePolling();
    }
  }, 1500);
}

function setStatus(text) {
  elements.statusPill.textContent = text;
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
}

async function bootstrap() {
  const health = await request("/api/health");
  setStatus(`Model: ${health.model} · Ollama: ${health.ollama}`);

  const auth = await request("/api/auth/me");
  appState.authenticated = auth.authenticated;
  renderAuthState();
  if (appState.authenticated) {
    await refreshConversations();
  }
}

async function refreshConversations() {
  appState.conversations = await request("/api/conversations");
  renderConversations();

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
    await refreshConversations();
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
}

function resetConversationView() {
  clearMessagePolling();
  appState.activeConversationId = null;
  appState.activeMessages = [];
  elements.conversationTitle.textContent = "New conversation";
  elements.messageList.innerHTML = "";
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
  setComposerError();
  clearMessagePolling();
  updateSendingState(true);
  appState.isLiveStreaming = true;
  elements.promptInput.value = "";

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
          await selectConversation(conversationId);
        } else if (eventName === "chunk" && assistantMessageId) {
          const targetMessage = appState.activeMessages.find(
            (message) => message.id === assistantMessageId,
          );
          const currentContent = targetMessage?.content || "";
          updateMessageNode(assistantMessageId, `${currentContent}${payload.content}`);
        } else if (eventName === "error") {
          throw new Error(payload.detail);
        } else if (eventName === "done" && conversationId) {
          await loadConversationMessages(conversationId);
        }
      }
    }
  } catch (error) {
    setComposerError(error.message);
    if (conversationId) {
      await loadConversationMessages(conversationId);
    }
  } finally {
    appState.isLiveStreaming = false;
    updateSendingState(false);
    scheduleMessagePolling();
  }
}

elements.loginForm.addEventListener("submit", handleLogin);
elements.logoutButton.addEventListener("click", handleLogout);
elements.newChatButton.addEventListener("click", resetConversationView);
elements.composerForm.addEventListener("submit", handleSend);

bootstrap().catch((error) => {
  setStatus(`Startup error: ${error.message}`);
});
