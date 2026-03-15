"use strict";
/**
 * ChatPanel — VS Code WebviewPanel for the Nova Code chat UI.
 *
 * Responsibilities:
 *  - Render the chat UI in a WebviewPanel (opens in ViewColumn.Two)
 *  - Forward user messages / approval responses from the webview → NovaProcess
 *  - Forward Nova events from NovaProcess → the webview
 *
 * The webview sends:
 *   {type:"turn",   input:"..."}
 *   {type:"approval", approved: bool}
 *   {type:"rejection_direction", direction:"stop|skip|<instruction>"}
 *   {type:"clear"}
 *
 * The extension host re-emits NovaProcess messages straight into the webview.
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.ChatPanel = void 0;
const vscode = __importStar(require("vscode"));
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
class ChatPanel {
    /** Create or reveal the singleton chat panel.
     *  If the panel already exists but the process changed, re-wires it. */
    static createOrShow(extensionUri, nova) {
        if (ChatPanel._instance) {
            // Re-wire to new process if it changed (e.g. after restart)
            if (ChatPanel._instance._nova !== nova) {
                ChatPanel._instance._wireNova(nova);
            }
            ChatPanel._instance._panel.reveal(vscode.ViewColumn.Two, true);
            return ChatPanel._instance;
        }
        const panel = vscode.window.createWebviewPanel(ChatPanel.viewType, 'Nova Code', { viewColumn: vscode.ViewColumn.Two, preserveFocus: true }, {
            enableScripts: true,
            retainContextWhenHidden: true,
            // Allow serving the logo from the repo root (one level above the extension dir)
            localResourceRoots: [vscode.Uri.joinPath(extensionUri, '..')],
        });
        ChatPanel._instance = new ChatPanel(panel, nova, extensionUri);
        return ChatPanel._instance;
    }
    constructor(panel, nova, extensionUri) {
        this._disposables = [];
        // Webview load gate: messages from nova are queued until the webview JS
        // signals it is ready (webviewReady), preventing dropped messages during
        // the async HTML/JS load phase.
        this._webviewLoaded = false;
        this._pendingMessages = [];
        this._panel = panel;
        this._nova = nova;
        this._extensionUri = extensionUri;
        // Seed with whatever is active at construction time, then keep it updated.
        // When the webview gains focus activeTextEditor becomes undefined, but we
        // hold onto the last real editor here so context capture still works.
        this._lastEditor = vscode.window.activeTextEditor;
        vscode.window.onDidChangeActiveTextEditor((editor) => { if (editor) {
            this._lastEditor = editor;
        } }, null, this._disposables);
        this._panel.webview.html = this._buildHtml();
        // Webview → extension host → Python process
        this._panel.webview.onDidReceiveMessage((msg) => {
            switch (msg.type) {
                // Webview JS finished loading — flush any queued nova messages,
                // then sync current process state if nothing was queued.
                case 'webviewReady':
                    this._webviewLoaded = true;
                    if (this._pendingMessages.length > 0) {
                        for (const m of this._pendingMessages) {
                            this._panel.webview.postMessage(m);
                        }
                        this._pendingMessages = [];
                    }
                    else if (this._nova.ready) {
                        this._panel.webview.postMessage({ type: 'ready' });
                    }
                    else if (this._nova.exited) {
                        this._panel.webview.postMessage({
                            type: 'error',
                            message: 'Nova Code process is not running. Use "Nova Code: Open Chat" to restart.',
                        });
                    }
                    // else: process still starting — the queued 'ready' will arrive above
                    break;
                case 'turn': {
                    if (this._nova.exited) {
                        this._panel.webview.postMessage({
                            type: 'error',
                            message: 'Nova Code process has stopped. Use "Nova Code: Open Chat" to restart.',
                        });
                        break;
                    }
                    const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
                    // Capture active editor context: open file path + any selection.
                    // vscode.window.activeTextEditor still reflects the last-focused text
                    // editor even when the chat webview has focus, so this is reliable.
                    const contextParts = [];
                    const editor = this._lastEditor;
                    if (editor) {
                        contextParts.push(`--- Open file: ${editor.document.uri.fsPath} ---`);
                        if (!editor.selection.isEmpty) {
                            const selectedText = editor.document.getText(editor.selection);
                            const startLine = editor.selection.start.line + 1;
                            const endLine = editor.selection.end.line + 1;
                            contextParts.push(`--- Selected lines ${startLine}-${endLine} ---\n${selectedText}\n---`);
                        }
                    }
                    const context = contextParts.length > 0 ? contextParts.join('\n') : null;
                    // Notify the webview so it can show a context badge on the message.
                    if (editor) {
                        const fileName = editor.document.uri.fsPath.split('/').pop() ?? editor.document.uri.fsPath;
                        const selDesc = !editor.selection.isEmpty
                            ? `, lines ${editor.selection.start.line + 1}-${editor.selection.end.line + 1}`
                            : '';
                        this._panel.webview.postMessage({
                            type: 'context_attached',
                            description: `${fileName}${selDesc}`,
                        });
                    }
                    this._nova.send({
                        type: 'turn',
                        input: msg.input,
                        cwd,
                        context,
                    });
                    break;
                }
                case 'approval':
                    this._nova.send({ type: 'approval', approved: msg.approved });
                    break;
                case 'rejection_direction':
                    this._nova.send({
                        type: 'rejection_direction',
                        direction: msg.direction,
                    });
                    break;
                case 'switch_thinking':
                    this._nova.send({ type: 'switch_thinking', effort: msg.effort ?? null });
                    break;
                case 'stop':
                    this._nova.send({ type: 'stop' });
                    break;
                case 'clear':
                    this._nova.send({ type: 'clear' });
                    break;
                case 'set_auto_approve':
                    this._nova.send({ type: 'set_auto_approve', enabled: msg.enabled ?? false });
                    break;
                case 'show_conversations':
                    this._nova.send({ type: 'list_sessions' });
                    break;
            }
        }, null, this._disposables);
        this._wireNova(nova);
        this._panel.onDidDispose(() => this._dispose(), null, this._disposables);
    }
    /** Detach from old process, attach to new one, and sync webview state. */
    _wireNova(nova) {
        // Remove old listeners
        if (this._novaListener) {
            this._nova.off('message', this._novaListener);
        }
        if (this._novaExitListener) {
            this._nova.off('exit', this._novaExitListener);
        }
        this._nova = nova;
        this._novaListener = (msg) => {
            if (msg.type === 'sessions_list') {
                this._handleSessionsList(msg);
                return;
            }
            if (!this._webviewLoaded) {
                // Webview JS hasn't loaded yet — queue the message so it isn't dropped.
                this._pendingMessages.push(msg);
                return;
            }
            this._panel.webview.postMessage(msg);
        };
        this._novaExitListener = () => {
            this._panel.webview.postMessage({
                type: 'error',
                message: 'Nova Code process stopped. Run "Nova Code: Open Chat" to reconnect.',
            });
        };
        nova.on('message', this._novaListener);
        nova.on('exit', this._novaExitListener);
        // Only send ready immediately if the webview JS is already loaded (re-wire
        // path: panel existed, JS running). In the constructor path _webviewLoaded
        // is still false, so the queued 'ready' will be flushed by webviewReady.
        if (this._webviewLoaded && nova.ready) {
            this._panel.webview.postMessage({ type: 'ready' });
        }
    }
    async _handleSessionsList(msg) {
        const items = [
            { label: '+ New Conversation', description: 'Start a fresh session', path: null },
            ...msg.sessions.map((s) => ({
                label: s.title || s.path,
                description: s.created_at?.slice(0, 19).replace('T', ' ') || '',
                path: s.path,
            })),
        ];
        const selected = await vscode.window.showQuickPick(items, {
            placeHolder: 'Select a conversation',
            matchOnDescription: true,
        });
        if (!selected) {
            return;
        }
        if (!selected.path) {
            this._nova.send({ type: 'clear' });
            this._panel.webview.postMessage({ type: 'cleared' });
        }
        else {
            this._nova.send({ type: 'resume_session', path: selected.path });
        }
    }
    _dispose() {
        if (this._novaListener) {
            this._nova.off('message', this._novaListener);
        }
        if (this._novaExitListener) {
            this._nova.off('exit', this._novaExitListener);
        }
        ChatPanel._instance = undefined;
        this._disposables.forEach((d) => d.dispose());
    }
    // ── Webview HTML ────────────────────────────────────────────────────────────
    _buildHtml() {
        let markedJs = '';
        try {
            markedJs = fs.readFileSync(path.join(this._extensionUri.fsPath, 'node_modules', 'marked', 'marked.min.js'), 'utf8');
        }
        catch {
            // marked not installed — fall back to plain text
            markedJs = 'window.marked = { parse: function(t) { return t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); } };';
        }
        // Resolve logo — sits one level above the extension directory (repo root)
        const logoFsPath = path.join(this._extensionUri.fsPath, '..', 'novacode.png');
        const logoUri = fs.existsSync(logoFsPath)
            ? this._panel.webview.asWebviewUri(vscode.Uri.file(logoFsPath))
            : null;
        return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src ${this._panel.webview.cspSource};">
<title>Nova Code</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    display: flex;
    flex-direction: column;
    height: 100vh;
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    background: var(--vscode-editor-background);
    color: var(--vscode-editor-foreground);
  }

  /* ── Message thread ── */
  #thread {
    flex: 1;
    overflow-y: auto;
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .msg { display: flex; flex-direction: column; max-width: 90%; }
  .msg.user  { align-self: flex-end; align-items: flex-end; }
  .msg.nova  { align-self: flex-start; align-items: flex-start; }

  .bubble {
    padding: 8px 12px;
    border-radius: 8px;
    line-height: 1.5;
    word-break: break-word;
  }
  .msg.user .bubble {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    white-space: pre-wrap;
  }
  .msg.nova .bubble {
    background: var(--vscode-input-background);
    border: 1px solid var(--vscode-input-border, transparent);
  }
  /* Markdown elements inside Nova bubbles */
  .msg.nova .bubble p { margin: 0.4em 0; }
  .msg.nova .bubble p:first-child { margin-top: 0; }
  .msg.nova .bubble p:last-child { margin-bottom: 0; }
  .msg.nova .bubble pre {
    background: var(--vscode-textBlockQuote-background);
    border-radius: 4px;
    padding: 8px 10px;
    overflow-x: auto;
    margin: 6px 0;
  }
  .msg.nova .bubble pre code { background: none; padding: 0; }
  .msg.nova .bubble code {
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 0.9em;
    background: var(--vscode-textBlockQuote-background);
    border-radius: 3px;
    padding: 1px 4px;
  }
  .msg.nova .bubble ul, .msg.nova .bubble ol { padding-left: 1.5em; margin: 0.4em 0; }
  .msg.nova .bubble li { margin: 0.2em 0; }
  .msg.nova .bubble h1, .msg.nova .bubble h2, .msg.nova .bubble h3 {
    font-weight: 600; margin: 0.6em 0 0.3em;
  }
  .msg.nova .bubble blockquote {
    border-left: 3px solid var(--vscode-panel-border);
    padding-left: 10px; opacity: 0.8; margin: 0.4em 0;
  }
  .msg.nova .bubble table { border-collapse: collapse; margin: 6px 0; }
  .msg.nova .bubble th, .msg.nova .bubble td {
    border: 1px solid var(--vscode-panel-border); padding: 4px 8px;
  }

  .label {
    font-size: 0.75em;
    opacity: 0.6;
    margin-bottom: 2px;
    padding: 0 4px;
  }

  /* streaming cursor */
  .cursor::after { content: '▌'; animation: blink .8s step-end infinite; }
  @keyframes blink { 50% { opacity: 0; } }

  /* plan */
  .plan { font-size: 0.85em; opacity: 0.75; padding: 4px 0; }
  .plan ol { padding-left: 1.2em; }

  /* tool call / result */
  .tool-call, .tool-result {
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 0.82em;
    background: var(--vscode-textBlockQuote-background);
    border-left: 3px solid var(--vscode-textLink-foreground);
    padding: 6px 10px;
    border-radius: 4px;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .tool-result { border-color: var(--vscode-charts-green, #4caf50); opacity: 0.85; }

  /* approval prompt */
  .approval-box {
    background: var(--vscode-editor-background);
    border: 1px solid var(--vscode-panel-border);
    border-radius: 6px;
    padding: 10px 12px;
    max-width: 95%;
  }
  .approval-box .tool-name { font-weight: bold; margin-bottom: 4px; }
  .approval-box .args {
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 0.8em;
    max-height: 200px;
    overflow-y: auto;
    overflow-x: hidden;
    margin: 6px 0;
    border: 1px solid var(--vscode-panel-border);
    border-radius: 3px;
  }
  /* diff lines inside the approval args box */
  .diff-del {
    display: block;
    background: var(--vscode-diffEditor-removedLineBackground, rgba(255, 50, 50, 0.2));
    white-space: pre-wrap;
    word-break: break-all;
    padding: 0 6px;
  }
  .diff-add {
    display: block;
    background: var(--vscode-diffEditor-insertedLineBackground, rgba(80, 200, 80, 0.2));
    white-space: pre-wrap;
    word-break: break-all;
    padding: 0 6px;
  }
  .args-expand-toggle {
    font-size: 0.75em;
    opacity: 0.55;
    cursor: pointer;
    padding: 2px 8px;
    text-align: center;
    border-top: 1px solid var(--vscode-panel-border);
    user-select: none;
  }
  .args-expand-toggle:hover { opacity: 1; }
  .approval-box .btns { display: flex; gap: 8px; margin-top: 8px; }
  button {
    padding: 4px 14px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.9em;
  }
  .btn-approve {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
  }
  .btn-reject {
    background: var(--vscode-button-secondaryBackground);
    color: var(--vscode-button-secondaryForeground);
  }
  button:hover { opacity: 0.85; }

  /* rejection prompt */
  .rejection-box {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 95%;
  }
  .rejection-box input {
    background: var(--vscode-input-background);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 0.9em;
  }

  /* step badge */
  .step-badge {
    font-size: 0.78em;
    opacity: 0.6;
    padding: 2px 6px;
    border: 1px solid currentColor;
    border-radius: 10px;
    align-self: flex-start;
  }

  /* context badge — shown below the user's message bubble when a file is attached */
  .context-badge {
    font-size: 0.72em;
    opacity: 0.55;
    margin-top: 3px;
    padding: 1px 6px;
    border: 1px solid var(--vscode-panel-border);
    border-radius: 10px;
    font-family: var(--vscode-editor-font-family, monospace);
    align-self: flex-end;
  }

  /* inline code */
  code { font-family: var(--vscode-editor-font-family, monospace); }

  /* ── Input row ── */
  #input-row {
    display: flex;
    gap: 8px;
    padding: 10px 16px;
    border-top: 1px solid var(--vscode-panel-border);
  }
  #user-input {
    flex: 1;
    background: var(--vscode-input-background);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border);
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 1em;
    resize: none;
    min-height: 38px;
    max-height: 120px;
    overflow-y: auto;
  }
  #user-input:focus { outline: 1px solid var(--vscode-focusBorder); }
  #send-btn {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    padding: 6px 14px;
    align-self: flex-end;
  }
  #stop-btn {
    background: var(--vscode-button-secondaryBackground);
    color: var(--vscode-button-secondaryForeground);
    padding: 6px 14px;
    align-self: flex-end;
    display: none;
  }

  /* ── Header / thinking selector ── */
  #header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 5px 12px;
    border-bottom: 1px solid var(--vscode-panel-border);
    flex-shrink: 0;
  }
  .hdr-title { font-weight: 600; font-size: 0.85em; opacity: 0.75; }
  .thinking-selector { display: flex; align-items: center; gap: 3px; }
  .think-label { font-size: 0.75em; opacity: 0.55; margin-right: 4px; }
  .think-btn {
    font-size: 0.72em;
    padding: 2px 9px;
    border-radius: 10px;
    background: transparent;
    color: var(--vscode-editor-foreground);
    border: 1px solid var(--vscode-panel-border);
    cursor: pointer;
    opacity: 0.65;
  }
  .think-btn.active {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border-color: transparent;
    opacity: 1;
  }
  .think-btn:hover:not(.active) { opacity: 1; }

  #conv-btn {
    font-size: 0.72em;
    padding: 2px 10px;
    border-radius: 10px;
    background: transparent;
    color: var(--vscode-editor-foreground);
    border: 1px solid var(--vscode-panel-border);
    cursor: pointer;
    opacity: 0.65;
  }
  #conv-btn:hover { opacity: 1; }

  #auto-approve-btn {
    font-size: 0.72em;
    padding: 2px 10px;
    border-radius: 10px;
    cursor: pointer;
    border: 1px solid var(--vscode-panel-border);
  }
  #auto-approve-btn.auto-approve-off {
    background: transparent;
    color: var(--vscode-editor-foreground);
    opacity: 0.65;
  }
  #auto-approve-btn.auto-approve-on {
    background: var(--vscode-inputValidation-warningBackground);
    color: var(--vscode-inputValidation-warningForeground, var(--vscode-editor-foreground));
    border-color: var(--vscode-inputValidation-warningBorder);
    opacity: 1;
  }
  #auto-approve-btn:hover { opacity: 1; }

  #status {
    font-size: 0.78em;
    opacity: 0.55;
    padding: 2px 16px 4px;
    min-height: 18px;
  }
</style>
</head>
<body>

<div id="header">
  <div style="display:flex;gap:6px;align-items:center;">
    ${logoUri ? `<img src="${logoUri}" width="22" height="22" style="flex-shrink:0;opacity:0.9;" alt="">` : ''}
    <button id="conv-btn">Conversations</button>
    <button id="auto-approve-btn" class="auto-approve-off">Auto-approve: Off</button>
  </div>
  <div class="thinking-selector">
    <span class="think-label">Thinking:</span>
    <button class="think-btn active" data-level="">Off</button>
    <button class="think-btn" data-level="auto">Auto</button>
    <button class="think-btn" data-level="low">Low</button>
    <button class="think-btn" data-level="medium">Medium</button>
    <button class="think-btn" data-level="high">High</button>
  </div>
</div>

<div id="thread"></div>
<div id="status">Connecting to Nova Code...</div>
<div id="input-row">
  <textarea id="user-input" rows="1" placeholder="Ask Nova Code..." disabled></textarea>
  <button id="send-btn" disabled>Send</button>
  <button id="stop-btn">Stop</button>
</div>

<script>${markedJs}</script>
<script>
  const vscode = acquireVsCodeApi();
  const thread  = document.getElementById('thread');
  const input   = document.getElementById('user-input');
  const sendBtn = document.getElementById('send-btn');
  const stopBtn = document.getElementById('stop-btn');
  const status  = document.getElementById('status');

  let busy = false;
  let thinkingLevel = '';   // '' | 'auto' | 'low' | 'medium' | 'high'
  let autoApprove = false;

  const autoApproveBtn = document.getElementById('auto-approve-btn');
  autoApproveBtn.addEventListener('click', () => {
    autoApprove = !autoApprove;
    updateAutoApproveUI();
    vscode.postMessage({ type: 'set_auto_approve', enabled: autoApprove });
  });
  function updateAutoApproveUI() {
    autoApproveBtn.textContent = 'Auto-approve: ' + (autoApprove ? 'On' : 'Off');
    autoApproveBtn.className = autoApprove ? 'auto-approve-on' : 'auto-approve-off';
  }

  // Tell the extension host that the webview JS is loaded and ready.
  // The host will respond with {type:'ready'} if the process is already up,
  // or an error if it has exited — resolving the "Connecting..." race condition.
  vscode.postMessage({ type: 'webviewReady' });

  // Wire conversations button
  document.getElementById('conv-btn').addEventListener('click', () => {
    vscode.postMessage({ type: 'show_conversations' });
  });

  // Wire thinking selector buttons — send switch_thinking immediately on click
  // so Python is the source of truth and can confirm via thinking_switched.
  document.querySelectorAll('.think-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      thinkingLevel = btn.dataset.level || '';
      document.querySelectorAll('.think-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      vscode.postMessage({ type: 'switch_thinking', effort: thinkingLevel || null });
    });
  });
  let streamBubble = null;   // current streaming bubble element
  let streamText = '';

  // ── DOM helpers ────────────────────────────────────────────────────────────
  function addMessage(role, html, cssClass) {
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + role;
    const lbl = document.createElement('div');
    lbl.className = 'label';
    lbl.textContent = role === 'user' ? 'You' : 'Nova';
    const bubble = document.createElement('div');
    bubble.className = 'bubble' + (cssClass ? ' ' + cssClass : '');
    bubble.innerHTML = html;
    wrap.appendChild(lbl);
    wrap.appendChild(bubble);
    thread.appendChild(wrap);
    thread.scrollTop = thread.scrollHeight;
    return bubble;
  }

  function addWidget(html) {
    const el = document.createElement('div');
    el.innerHTML = html;
    const child = el.firstElementChild || el;
    thread.appendChild(child);
    thread.scrollTop = thread.scrollHeight;
    return child;
  }

  function addInfo(text) {
    const el = document.createElement('div');
    el.style.cssText = 'font-size:0.8em;opacity:0.5;padding:2px 4px;';
    el.textContent = text;
    thread.appendChild(el);
    thread.scrollTop = thread.scrollHeight;
  }

  function setBusy(val) {
    busy = val;
    input.disabled = val;
    sendBtn.disabled = val;
    stopBtn.style.display = val ? 'block' : 'none';
    if (!val) {
      input.focus();
    }
  }

  stopBtn.addEventListener('click', () => {
    vscode.postMessage({ type: 'stop' });
    status.textContent = 'Stopping...';
  });

  // ── Handle messages from extension host ───────────────────────────────────
  window.addEventListener('message', (event) => {
    const msg = event.data;

    switch (msg.type) {

      case 'ready':
        status.textContent = '';
        setBusy(false);
        // Re-sync thinking mode with the fresh Python session (handles restarts).
        vscode.postMessage({ type: 'switch_thinking', effort: thinkingLevel || null });
        break;

      case 'text': {
        // Accumulate streaming text into the current bubble
        if (!streamBubble) {
          streamText = '';
          streamBubble = addMessage('nova', '', 'cursor');
        }
        streamText += msg.content;
        streamBubble.innerHTML = marked.parse(streamText);
        streamBubble.classList.add('cursor');
        thread.scrollTop = thread.scrollHeight;
        break;
      }

      case 'plan': {
        const steps = msg.steps;
        const items = steps.map((s, i) => '<li>' + escHtml(s) + '</li>').join('');
        addWidget(
          '<div class="msg nova"><div class="label">Nova · Plan</div>' +
          '<div class="bubble plan"><ol>' + items + '</ol></div></div>'
        );
        break;
      }

      case 'tool_approval': {
        finaliseStream();
        setBusy(true); // keep input locked but wire approve/reject buttons

        // Auto-approve: skip the dialog entirely — send approval immediately.
        if (autoApprove) {
          const label = toolLabel(msg.name, msg.args);
          addWidget(
            '<div class="tool-call">' + escHtml(label) + ' (auto-approved)</div>'
          );
          vscode.postMessage({ type: 'approval', approved: true });
          break;
        }

        const label = toolLabel(msg.name, msg.args);
        // Build args preview: coloured diff for file ops, plain JSON for others.
        let argsHtml = '';
        if (msg.name === 'edit_file') {
          argsHtml = buildDiffHtml(msg.args.old_string || '', msg.args.new_string || '');
        } else if (msg.name === 'multi_edit') {
          const edits = Array.isArray(msg.args.edits) ? msg.args.edits : [];
          argsHtml = edits.map((e, i) =>
            (edits.length > 1
              ? '<div style="opacity:0.55;font-size:0.85em;padding:1px 6px;border-top:1px solid var(--vscode-panel-border)">edit ' + (i + 1) + '</div>'
              : '') +
            buildDiffHtml(e.old_string || '', e.new_string || '')
          ).join('');
        } else if (msg.name === 'write_file') {
          argsHtml = (msg.args.content || '').split('\\n').map(l => '<div class="diff-add">+ ' + escHtml(l) + '</div>').join('');
        } else {
          const json = JSON.stringify(msg.args, null, 2);
          argsHtml = '<div style="white-space:pre-wrap;word-break:break-all;padding:2px 6px;opacity:0.85">' +
                     escHtml(json.length > 600 ? json.slice(0, 600) + '\\n\u2026' : json) +
                     '</div>';
        }
        const box = addWidget(
          '<div class="approval-box">' +
            '<div class="tool-name">' + escHtml(label) + '</div>' +
            '<div class="args"></div>' +
            '<div class="btns">' +
              '<button class="btn-approve">Approve</button>' +
              '<button class="btn-reject">Reject</button>' +
            '</div>' +
          '</div>'
        );
        const argsDiv = box.querySelector('.args');
        argsDiv.innerHTML = argsHtml;
        // Show expand toggle only when content overflows the max-height cap.
        if (argsDiv.scrollHeight > argsDiv.clientHeight) {
          const toggle = document.createElement('div');
          toggle.className = 'args-expand-toggle';
          toggle.textContent = 'Show all \u2193';
          let expanded = false;
          toggle.addEventListener('click', () => {
            expanded = !expanded;
            argsDiv.style.maxHeight = expanded ? 'none' : '';
            toggle.textContent = expanded ? 'Collapse \u2191' : 'Show all \u2193';
          });
          box.insertBefore(toggle, box.querySelector('.btns'));
        }
        const [approveBtn, rejectBtn] = box.querySelectorAll('button');
        approveBtn.addEventListener('click', () => {
          box.remove();
          vscode.postMessage({ type: 'approval', approved: true });
        });
        rejectBtn.addEventListener('click', () => {
          box.remove();
          // Show rejection direction prompt
          showRejectionPrompt(msg.name);
          vscode.postMessage({ type: 'approval', approved: false });
        });
        break;
      }

      case 'rejection_prompt': {
        // Python is now asking what to do after the rejection
        showRejectionDirection();
        break;
      }

      case 'tool_result': {
        const label = toolLabel(msg.name, msg.args || {});
        addWidget(
          '<div class="tool-call">' + escHtml(label) + '</div>'
        );
        break;
      }

      case 'step_done':
        addWidget(
          '<div class="step-badge">Step ' + msg.current + '/' + msg.total + ' done</div>'
        );
        break;

      case 'context_attached': {
        // Annotate the most recent user message bubble with a context badge.
        const userBubbles = thread.querySelectorAll('.msg.user');
        const lastUserWrap = userBubbles[userBubbles.length - 1];
        if (lastUserWrap) {
          const badge = document.createElement('span');
          badge.className = 'context-badge';
          badge.textContent = 'context: ' + msg.description;
          lastUserWrap.appendChild(badge);
        }
        break;
      }

      case 'cancelled':
        finaliseStream();
        addInfo('[Cancelled]');
        break;

      case 'turn_end':
        finaliseStream();
        setBusy(false);
        status.textContent = '';
        break;

      case 'thinking_switched': {
        // Sync button state when thinking is changed externally (e.g. switch_thinking cmd)
        const effort = msg.effort || '';
        thinkingLevel = effort;
        document.querySelectorAll('.think-btn').forEach(b => {
          b.classList.toggle('active', b.dataset.level === effort);
        });
        break;
      }

      case 'auto_approve_changed': {
        autoApprove = !!msg.enabled;
        updateAutoApproveUI();
        break;
      }

      case 'cleared':
        thread.innerHTML = '';
        status.textContent = 'Session cleared.';
        setTimeout(() => { status.textContent = ''; }, 2000);
        break;

      case 'session_resumed': {
        thread.innerHTML = '';
        const msgs = msg.messages || [];
        msgs.forEach(m => {
          if (m.role === 'user') {
            addMessage('user', escHtml(m.content), '');
          } else {
            addMessage('nova', marked.parse(m.content), '');
          }
        });
        status.textContent = 'Session resumed.';
        setTimeout(() => { status.textContent = ''; }, 2000);
        thread.scrollTop = thread.scrollHeight;
        break;
      }

      case 'error':
        finaliseStream();
        addWidget(
          '<div style="color:var(--vscode-errorForeground);padding:4px 0;">' +
          'Error: ' + escHtml(msg.message || 'Unknown error') + '</div>'
        );
        setBusy(false);
        break;
    }
  });

  function finaliseStream() {
    if (streamBubble) {
      streamBubble.classList.remove('cursor');
      streamBubble = null;
      streamText = '';
    }
  }

  function showRejectionPrompt(toolName) {
    // The rejection prompt (asking what to do) is handled by rejection_prompt event
    // which fires AFTER the user clicks Reject and approval:false is processed.
    // Nothing to do here.
  }

  function showRejectionDirection() {
    const box = addWidget(
      '<div class="rejection-box">' +
        '<div style="font-size:0.85em;opacity:0.75">Tool rejected. What next?</div>' +
        '<input type="text" placeholder="Enter to stop | \\'skip\\' | or new instruction" />' +
        '<div style="display:flex;gap:6px;">' +
          '<button class="btn-approve">Send</button>' +
          '<button class="btn-reject">Stop</button>' +
        '</div>' +
      '</div>'
    );
    const inp = box.querySelector('input');
    const [rejectSendBtn, rejectStopBtn] = box.querySelectorAll('button');
    function submit(dir) {
      box.remove();
      vscode.postMessage({ type: 'rejection_direction', direction: dir });
    }
    rejectSendBtn.addEventListener('click', () => submit(inp.value.trim() || 'stop'));
    rejectStopBtn.addEventListener('click', () => submit('stop'));
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { submit(inp.value.trim() || 'stop'); }
    });
    inp.focus();
  }

  // Build colour-coded diff HTML for the approval box.
  // All content is passed through escHtml before insertion — safe to set as innerHTML.
  function buildDiffHtml(oldStr, newStr) {
    let html = '';
    if (oldStr) {
      html += oldStr.split('\\n').map(l => '<div class="diff-del">- ' + escHtml(l) + '</div>').join('');
    }
    if (newStr) {
      html += newStr.split('\\n').map(l => '<div class="diff-add">+ ' + escHtml(l) + '</div>').join('');
    }
    return html;
  }

  // Compact Claude Code-style label for a tool call (mirrors Python _tool_label)
  function toolLabel(name, args) {
    const a = args || {};
    if (name === 'read_file')      return 'Read    ' + (a.path || '');
    if (name === 'write_file')     return 'Write   ' + (a.path || '');
    if (name === 'edit_file')      return 'Edit    ' + (a.path || '');
    if (name === 'multi_edit')     return 'Edit    ' + (a.path || '');
    if (name === 'bash')           return 'Bash    ' + (a.command || '').slice(0, 80);
    if (name === 'glob_files')     return 'Glob    ' + (a.pattern || '');
    if (name === 'grep')           return 'Grep    ' + (a.pattern || '') + '  ' + (a.path || '');
    if (name === 'list_directory') return 'LS      ' + (a.path || '.');
    if (name === 'web_search')     return 'Search  ' + (a.query || '');
    if (name === 'web_fetch')      return 'Fetch   ' + (a.url || '');
    if (name === 'todo_read')      return 'Read    todos';
    if (name === 'todo_write')     return 'Write   todos';
    if (name === 'notebook_read')  return 'Read    ' + (a.path || '');
    if (name === 'notebook_edit')  return 'Edit    ' + (a.path || '');
    if (name === 'set_thinking_mode') return 'Think   ' + (a.level || '');
    const firstVal = Object.values(a)[0] || '';
    return (name || '') + '  ' + String(firstVal).slice(0, 80);
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Send a turn ────────────────────────────────────────────────────────────
  function sendTurn() {
    const text = input.value.trim();
    if (!text || busy) { return; }
    addMessage('user', escHtml(text), '');
    input.value = '';
    input.style.height = '';
    status.textContent = thinkingLevel ? \`Thinking (\${thinkingLevel})...\` : 'Thinking...';
    setBusy(true);
    vscode.postMessage({ type: 'turn', input: text });
  }

  sendBtn.addEventListener('click', sendTurn);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendTurn();
    }
  });

  // Auto-resize textarea
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });
</script>
</body>
</html>`;
    }
}
exports.ChatPanel = ChatPanel;
ChatPanel.viewType = 'novacode.chat';
//# sourceMappingURL=chatPanel.js.map