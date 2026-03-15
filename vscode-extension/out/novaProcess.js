"use strict";
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
exports.NovaProcess = void 0;
const cp = __importStar(require("child_process"));
const readline = __importStar(require("readline"));
const events_1 = require("events");
class NovaProcess extends events_1.EventEmitter {
    constructor(pythonPath, options = {}) {
        super();
        this._ready = false;
        this._exited = false;
        const args = ['-m', 'novacode', 'serve'];
        this._proc = cp.spawn(pythonPath, args, {
            stdio: ['pipe', 'pipe', 'pipe'],
            env: { ...process.env, ...(options.env ?? {}) },
        });
        // Forward stderr for debugging (visible in "Output > Nova Code")
        this._proc.stderr?.on('data', (chunk) => {
            this.emit('stderr', chunk.toString());
        });
        // Parse stdout as newline-delimited JSON
        const rl = readline.createInterface({ input: this._proc.stdout });
        rl.on('line', (line) => {
            const trimmed = line.trim();
            if (!trimmed) {
                return;
            }
            let msg;
            try {
                msg = JSON.parse(trimmed);
            }
            catch {
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
    send(msg) {
        if (this._exited) {
            return;
        }
        try {
            this._proc.stdin?.write(JSON.stringify(msg) + '\n');
        }
        catch {
            // stdin may be closed if process already exited
        }
    }
    get ready() {
        return this._ready;
    }
    get exited() {
        return this._exited;
    }
    dispose() {
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
exports.NovaProcess = NovaProcess;
//# sourceMappingURL=novaProcess.js.map