"use strict";
/**
 * Nova Code VS Code Extension — entry point.
 *
 * Commands (accessible via Cmd+Shift+P):
 *   Nova Code: Open Chat      — opens the chat panel
 *   Nova Code: Configure      — prompts for Python path + AWS credentials
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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const novaProcess_1 = require("./novaProcess");
const chatPanel_1 = require("./chatPanel");
// Secret storage keys
const SECRET_KEY_ID = 'novacode.awsKeyId';
const SECRET_SECRET_KEY = 'novacode.awsSecretKey';
const SECRET_SESSION = 'novacode.awsSessionToken';
// Global state keys (non-sensitive)
const STATE_PYTHON_PATH = 'novacode.pythonPath';
const STATE_REGION = 'novacode.region';
let novaProcess;
let outputChannel;
function activate(context) {
    outputChannel = vscode.window.createOutputChannel('Nova Code');
    context.subscriptions.push(outputChannel);
    context.subscriptions.push(vscode.commands.registerCommand('novacode.openChat', () => openChat(context)), vscode.commands.registerCommand('novacode.configure', () => configure(context)));
}
function deactivate() {
    novaProcess?.dispose();
    novaProcess = undefined;
}
// ── Configure command ────────────────────────────────────────────────────────
async function configure(context) {
    const currentPython = context.globalState.get(STATE_PYTHON_PATH) || 'python3';
    const currentRegion = context.globalState.get(STATE_REGION) || 'us-east-1';
    const pythonPath = await vscode.window.showInputBox({
        title: 'Nova Code: Python Path',
        prompt: 'Full path to the Python interpreter that has novacode installed',
        value: currentPython,
        ignoreFocusOut: true,
    });
    if (pythonPath === undefined) {
        return;
    } // cancelled
    const region = await vscode.window.showInputBox({
        title: 'Nova Code: AWS Region',
        prompt: 'AWS region for Amazon Bedrock (e.g. us-east-1)',
        value: currentRegion,
        ignoreFocusOut: true,
    });
    if (region === undefined) {
        return;
    }
    const keyId = await vscode.window.showInputBox({
        title: 'Nova Code: AWS Access Key ID',
        prompt: 'AWS_ACCESS_KEY_ID',
        password: true,
        ignoreFocusOut: true,
        placeHolder: 'Leave blank to keep existing value',
    });
    if (keyId === undefined) {
        return;
    }
    const secretKey = await vscode.window.showInputBox({
        title: 'Nova Code: AWS Secret Access Key',
        prompt: 'AWS_SECRET_ACCESS_KEY',
        password: true,
        ignoreFocusOut: true,
        placeHolder: 'Leave blank to keep existing value',
    });
    if (secretKey === undefined) {
        return;
    }
    const sessionToken = await vscode.window.showInputBox({
        title: 'Nova Code: AWS Session Token (optional)',
        prompt: 'AWS_SESSION_TOKEN — leave blank if not using temporary credentials',
        password: true,
        ignoreFocusOut: true,
        placeHolder: 'Optional — press Enter to clear / skip',
    });
    if (sessionToken === undefined) {
        return;
    }
    // Persist non-sensitive values in global state
    await context.globalState.update(STATE_PYTHON_PATH, pythonPath || currentPython);
    await context.globalState.update(STATE_REGION, region || currentRegion);
    // Persist sensitive values in SecretStorage (encrypted by VS Code)
    if (keyId) {
        await context.secrets.store(SECRET_KEY_ID, keyId);
    }
    if (secretKey) {
        await context.secrets.store(SECRET_SECRET_KEY, secretKey);
    }
    // Empty session token = clear it (user explicitly left blank)
    await context.secrets.store(SECRET_SESSION, sessionToken);
    vscode.window.showInformationMessage('Nova Code configuration saved.');
    // Restart the Python process with new credentials
    if (novaProcess && !novaProcess.exited) {
        outputChannel?.appendLine('Restarting Nova Code process with new configuration...');
        novaProcess.dispose();
        novaProcess = undefined;
    }
}
// ── Open chat ────────────────────────────────────────────────────────────────
async function openChat(context) {
    const nova = await getOrCreateProcess(context);
    if (!nova) {
        return;
    }
    chatPanel_1.ChatPanel.createOrShow(context.extensionUri, nova);
}
// ── Process lifecycle ────────────────────────────────────────────────────────
async function getOrCreateProcess(context) {
    if (novaProcess && !novaProcess.exited) {
        return novaProcess;
    }
    const pythonPath = context.globalState.get(STATE_PYTHON_PATH) || 'python3';
    const region = context.globalState.get(STATE_REGION) || '';
    // Load credentials from SecretStorage
    const keyId = await context.secrets.get(SECRET_KEY_ID) ?? '';
    const secretKey = await context.secrets.get(SECRET_SECRET_KEY) ?? '';
    const sessionToken = await context.secrets.get(SECRET_SESSION) ?? '';
    // Build env overrides (only include non-empty values)
    const env = {};
    if (keyId) {
        env['AWS_ACCESS_KEY_ID'] = keyId;
    }
    if (secretKey) {
        env['AWS_SECRET_ACCESS_KEY'] = secretKey;
    }
    if (sessionToken) {
        env['AWS_SESSION_TOKEN'] = sessionToken;
    }
    if (region) {
        env['AWS_DEFAULT_REGION'] = region;
    }
    if (!keyId || !secretKey) {
        const choice = await vscode.window.showWarningMessage('Nova Code: AWS credentials are not configured.', 'Configure Now', 'Continue Anyway');
        if (choice === 'Configure Now') {
            await configure(context);
            // Only proceed if credentials were actually saved — prevents an infinite
            // loop when the user cancels mid-configure and credentials are still missing.
            const newKeyId = await context.secrets.get(SECRET_KEY_ID) ?? '';
            const newSecretKey = await context.secrets.get(SECRET_SECRET_KEY) ?? '';
            if (!newKeyId || !newSecretKey) {
                return undefined;
            }
            return getOrCreateProcess(context);
        }
        if (choice !== 'Continue Anyway') {
            return undefined;
        }
    }
    outputChannel?.appendLine(`Starting Nova Code: ${pythonPath} -m novacode serve` +
        (region ? ` (region: ${region})` : ''));
    let proc;
    try {
        proc = new novaProcess_1.NovaProcess(pythonPath, { env });
    }
    catch (err) {
        vscode.window.showErrorMessage(`Nova Code: failed to spawn Python — ${err}. Run "Nova Code: Configure" to set the Python path.`);
        return undefined;
    }
    proc.on('ready', () => {
        outputChannel?.appendLine('Nova Code process ready.');
    });
    proc.on('stderr', (text) => {
        outputChannel?.append(text);
    });
    proc.on('exit', (code) => {
        outputChannel?.appendLine(`Nova Code process exited (code ${code ?? 'null'}).`);
        novaProcess = undefined;
    });
    novaProcess = proc;
    return proc;
}
//# sourceMappingURL=extension.js.map