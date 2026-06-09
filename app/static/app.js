const appState = {
  authenticated: Boolean(window.__APP_BOOTSTRAP__?.authenticated),
  conversations: [],
  activeConversationId: null,
  isSending: false,
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

function renderMessages(messages) {
  elements.messageList.innerHTML = "";
  for (const message of messages) {
    appendMessage(message.role, message.content);
  }
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
}

function appendMessage(role, content) {
  const article = document.createElement("article");
  article.className = `message message--${role}`;
  setMessageContent(article, role, content);
  elements.messageList.append(article);
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
  return article;
}

function setMessageContent(node, role, content) {
  if (role === "assistant") {
    node.dataset.rawContent = content;
    renderMarkdown(node, content);
    return;
  }

  node.textContent = content;
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

  if (!appState.conversations.length) {
    appState.activeConversationId = null;
    elements.conversationTitle.textContent = "New conversation";
    elements.messageList.innerHTML = "";
  }
}

async function selectConversation(conversationId) {
  appState.activeConversationId = conversationId;
  const active = appState.conversations.find(
    (conversation) => conversation.id === conversationId,
  );
  elements.conversationTitle.textContent = active?.title || "Conversation";
  renderConversations();

  const messages = await request(`/api/conversations/${conversationId}/messages`);
  renderMessages(messages);
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
  await request("/api/auth/logout", { method: "POST" });
  appState.authenticated = false;
  appState.conversations = [];
  appState.activeConversationId = null;
  renderAuthState();
  renderConversations();
  renderMessages([]);
}

function resetConversationView() {
  appState.activeConversationId = null;
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

  setComposerError();
  updateSendingState(true);
  appendMessage("user", prompt);
  const assistantNode = appendMessage("assistant", "");
  elements.promptInput.value = "";

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        conversation_id: appState.activeConversationId,
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
          appState.activeConversationId = payload.conversation_id;
          elements.conversationTitle.textContent = payload.title;
          await refreshConversations();
        } else if (eventName === "chunk") {
          const nextContent = `${assistantNode.dataset.rawContent || ""}${payload.content}`;
          setMessageContent(assistantNode, "assistant", nextContent);
        } else if (eventName === "error") {
          throw new Error(payload.detail);
        }
      }
    }
  } catch (error) {
    assistantNode.textContent = "";
    assistantNode.remove();
    setComposerError(error.message);
  } finally {
    updateSendingState(false);
  }
}

elements.loginForm.addEventListener("submit", handleLogin);
elements.logoutButton.addEventListener("click", handleLogout);
elements.newChatButton.addEventListener("click", resetConversationView);
elements.composerForm.addEventListener("submit", handleSend);

bootstrap().catch((error) => {
  setStatus(`Startup error: ${error.message}`);
});
