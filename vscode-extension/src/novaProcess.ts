/**
 * NovaProcess — manages the Python `nova serve` child process.
 *
 * Spawns the process, reads JSON-lines from stdout, and emits typed events.
 * Callers write JSON-lines to stdin via send().
 *
 * Event flow (Python → TypeScript):
 *   "ready"            — process started and session is initialised
 *   "message" (msg)    — any JSON-lines message from the Python process
 *   "stderr"  (text)   — stderr output (for logging / debug)
 *   "exit"    (code)   — process exited
 */

import * as cp from 'child_process';
import * as readline from 'readline';
import { EventEmitter } from 'events';

export interface NovaMessage {
  type: string;
  [key: string]: unknown;
}

export interface NovaProcessOptions {
  env?: Record<string, string>;  // extra env vars merged into process.env
}

export class NovaProcess extends EventEmitter {
  private readonly _proc: cp.ChildProcess;
  private _ready = false;
  private _exited = false;

  constructor(pythonPath: string, options: NovaProcessOptions = {}) {
    super();

    const args = ['-m', 'novacode', 'serve'];

    this._proc = cp.spawn(pythonPath, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, ...(options.env ?? {}) },
    });

    // Forward stderr for debugging (visible in "Output > Nova Code")
    this._proc.stderr?.on('data', (chunk: Buffer) => {
      this.emit('stderr', chunk.toString());
    });

    // Parse stdout as newline-delimited JSON
    const rl = readline.createInterface({ input: this._proc.stdout! });
    rl.on('line', (line) => {
      const trimmed = line.trim();
      if (!trimmed) {
        return;
      }
      let msg: NovaMessage;
      try {
        msg = JSON.parse(trimmed) as NovaMessage;
      } catch {
        // Ignore non-JSON lines (e.g. Python tracebacks before JSON starts)
        return;
      }
      if (msg.type === 'ready') {
        this._ready = true;
        this.emit('ready');
      }
      this.emit('message', msg);
    });

    this._proc.on('exit', (code) => {
      this._exited = true;
      this.emit('exit', code);
    });

    this._proc.on('error', (err) => {
      this.emit('stderr', `Process error: ${err.message}\n`);
    });
  }

  /** Send a JSON message to the Python process (writes one JSON line to stdin). */
  send(msg: object): void {
    if (this._exited) {
      return;
    }
    try {
      this._proc.stdin?.write(JSON.stringify(msg) + '\n');
    } catch {
      // stdin may be closed if process already exited
    }
  }

  get ready(): boolean {
    return this._ready;
  }

  get exited(): boolean {
    return this._exited;
  }

  dispose(): void {
    if (!this._exited) {
      this.send({ type: 'exit' });
      setTimeout(() => {
        if (!this._exited) {
          this._proc.kill();
        }
      }, 1000);
    }
  }
}
