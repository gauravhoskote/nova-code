/**
 * Nova Code VS Code Extension — entry point.
 *
 * Commands (accessible via Cmd+Shift+P):
 *   Nova Code: Open Chat      — opens the chat panel
 *   Nova Code: Configure      — prompts for Python path + AWS credentials
 */

import * as vscode from 'vscode';
import { NovaProcess } from './novaProcess';
import { ChatPanel } from './chatPanel';

// Secret storage keys
const SECRET_KEY_ID     = 'novacode.awsKeyId';
const SECRET_SECRET_KEY = 'novacode.awsSecretKey';
const SECRET_SESSION    = 'novacode.awsSessionToken';

// Global state keys (non-sensitive)
const STATE_PYTHON_PATH = 'novacode.pythonPath';
const STATE_REGION      = 'novacode.region';

let novaProcess: NovaProcess | undefined;
let outputChannel: vscode.OutputChannel | undefined;

export function activate(context: vscode.ExtensionContext): void {
  outputChannel = vscode.window.createOutputChannel('Nova Code');
  context.subscriptions.push(outputChannel);

  context.subscriptions.push(
    vscode.commands.registerCommand('novacode.openChat', () => openChat(context)),
    vscode.commands.registerCommand('novacode.configure', () => configure(context)),
  );
}

export function deactivate(): void {
  novaProcess?.dispose();
  novaProcess = undefined;
}

// ── Configure command ────────────────────────────────────────────────────────

async function configure(context: vscode.ExtensionContext): Promise<void> {
  const currentPython = context.globalState.get<string>(STATE_PYTHON_PATH) || 'python3';
  const currentRegion = context.globalState.get<string>(STATE_REGION) || 'us-east-1';

  const pythonPath = await vscode.window.showInputBox({
    title: 'Nova Code: Python Path',
    prompt: 'Full path to the Python interpreter that has novacode installed',
    value: currentPython,
    ignoreFocusOut: true,
  });
  if (pythonPath === undefined) { return; }  // cancelled

  const region = await vscode.window.showInputBox({
    title: 'Nova Code: AWS Region',
    prompt: 'AWS region for Amazon Bedrock (e.g. us-east-1)',
    value: currentRegion,
    ignoreFocusOut: true,
  });
  if (region === undefined) { return; }

  const keyId = await vscode.window.showInputBox({
    title: 'Nova Code: AWS Access Key ID',
    prompt: 'AWS_ACCESS_KEY_ID',
    password: true,
    ignoreFocusOut: true,
    placeHolder: 'Leave blank to keep existing value',
  });
  if (keyId === undefined) { return; }

  const secretKey = await vscode.window.showInputBox({
    title: 'Nova Code: AWS Secret Access Key',
    prompt: 'AWS_SECRET_ACCESS_KEY',
    password: true,
    ignoreFocusOut: true,
    placeHolder: 'Leave blank to keep existing value',
  });
  if (secretKey === undefined) { return; }

  const sessionToken = await vscode.window.showInputBox({
    title: 'Nova Code: AWS Session Token (optional)',
    prompt: 'AWS_SESSION_TOKEN — leave blank if not using temporary credentials',
    password: true,
    ignoreFocusOut: true,
    placeHolder: 'Optional — press Enter to clear / skip',
  });
  if (sessionToken === undefined) { return; }

  // Persist non-sensitive values in global state
  await context.globalState.update(STATE_PYTHON_PATH, pythonPath || currentPython);
  await context.globalState.update(STATE_REGION, region || currentRegion);

  // Persist sensitive values in SecretStorage (encrypted by VS Code)
  if (keyId)        { await context.secrets.store(SECRET_KEY_ID, keyId); }
  if (secretKey)    { await context.secrets.store(SECRET_SECRET_KEY, secretKey); }
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

async function openChat(context: vscode.ExtensionContext): Promise<void> {
  const nova = await getOrCreateProcess(context);
  if (!nova) { return; }
  ChatPanel.createOrShow(context.extensionUri, nova);
}

// ── Process lifecycle ────────────────────────────────────────────────────────

async function getOrCreateProcess(
  context: vscode.ExtensionContext,
): Promise<NovaProcess | undefined> {
  if (novaProcess && !novaProcess.exited) {
    return novaProcess;
  }

  const pythonPath = context.globalState.get<string>(STATE_PYTHON_PATH) || 'python3';
  const region     = context.globalState.get<string>(STATE_REGION) || '';

  // Load credentials from SecretStorage
  const keyId        = await context.secrets.get(SECRET_KEY_ID) ?? '';
  const secretKey    = await context.secrets.get(SECRET_SECRET_KEY) ?? '';
  const sessionToken = await context.secrets.get(SECRET_SESSION) ?? '';

  // Build env overrides (only include non-empty values)
  const env: Record<string, string> = {};
  if (keyId)        { env['AWS_ACCESS_KEY_ID']     = keyId; }
  if (secretKey)    { env['AWS_SECRET_ACCESS_KEY'] = secretKey; }
  if (sessionToken) { env['AWS_SESSION_TOKEN']     = sessionToken; }
  if (region)       { env['AWS_DEFAULT_REGION']    = region; }

  if (!keyId || !secretKey) {
    const choice = await vscode.window.showWarningMessage(
      'Nova Code: AWS credentials are not configured.',
      'Configure Now',
      'Continue Anyway',
    );
    if (choice === 'Configure Now') {
      await configure(context);
      // Only proceed if credentials were actually saved — prevents an infinite
      // loop when the user cancels mid-configure and credentials are still missing.
      const newKeyId     = await context.secrets.get(SECRET_KEY_ID) ?? '';
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

  outputChannel?.appendLine(
    `Starting Nova Code: ${pythonPath} -m novacode serve` +
    (region ? ` (region: ${region})` : ''),
  );

  let proc: NovaProcess;
  try {
    proc = new NovaProcess(pythonPath, { env });
  } catch (err) {
    vscode.window.showErrorMessage(
      `Nova Code: failed to spawn Python — ${err}. Run "Nova Code: Configure" to set the Python path.`,
    );
    return undefined;
  }

  proc.on('ready', () => {
    outputChannel?.appendLine('Nova Code process ready.');
  });

  proc.on('stderr', (text: string) => {
    outputChannel?.append(text);
  });

  proc.on('exit', (code: number | null) => {
    outputChannel?.appendLine(`Nova Code process exited (code ${code ?? 'null'}).`);
    novaProcess = undefined;
  });

  novaProcess = proc;
  return proc;
}
