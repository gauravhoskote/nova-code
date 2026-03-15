# Nova Code

An AI coding assistant powered by **Amazon Bedrock Nova models**, available as both a Python CLI and a VS Code extension.

## Requirements

- Python 3.8+
- An AWS account with Bedrock Nova model access enabled
- AWS credentials (see [Configuration](#configuration) below)

## Installation

```bash
pip install -e .
```

## Configuration

Nova Code calls Amazon Bedrock using AWS credentials tied to an IAM user. Follow the steps below from scratch.

> **Security recommendation:** Follow the [principle of least privilege](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html#grant-least-privilege) — create a dedicated IAM user with only the permissions Nova Code needs. Avoid using your root account or attaching `AdministratorAccess`.

---

### Step 1 — Create a dedicated IAM user

1. Sign in to the [AWS Console](https://console.aws.amazon.com/)
2. Go to **IAM → Users → Create user**
3. Enter a username (e.g. `nova-code-user`)
4. On the permissions screen, select **"Attach policies directly"**
5. Choose one of the two permission options below (**Option A is strongly recommended**)

#### Option A — Least privilege (recommended)

Click **"Create policy"**, switch to the **JSON** tab, and paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockNovaAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/amazon.nova-*",
        "arn:aws:bedrock:*:*:inference-profile/amazon.nova-*",
        "arn:aws:bedrock:*:*:inference-profile/global.amazon.nova-*"
      ]
    }
  ]
}
```

Name it `BedrockNovaAccess`, save it, then attach it to the user.

#### Option B — AdministratorAccess (not recommended)

Search for and attach the built-in `AdministratorAccess` policy. This grants full access to your entire AWS account. Only use this for quick personal testing — never in a shared or production environment.

6. Complete the user creation wizard.

---

### Step 2 — Generate an access key

1. Open the newly created user → **Security credentials** tab
2. Under **"Access keys"**, click **"Create access key"**
3. Select **"Command Line Interface (CLI)"** as the use case
4. Copy both values — **you will not be able to see the secret again after closing this page**:
   - Access Key ID (starts with `AKIA…`)
   - Secret Access Key

---

### Step 3 — Enable Bedrock model access

Nova Code uses Amazon Nova models, which require explicit opt-in:

1. Go to **Amazon Bedrock → Model access** (make sure you are in the **`us-east-1`** region)
2. Click **"Modify model access"**
3. Enable all **Amazon Nova** models
4. Submit and wait a few minutes for activation

---

### Step 4 — Export your credentials

Choose one of the two options below.

#### Option A — Setup script (recommended)

Open `setup-env.sh` in this repo, fill in your credentials, then source it before running the app:

```bash
# 1. Fill in your Access Key ID and Secret Access Key in setup-env.sh
# 2. Then run:
source setup-env.sh

nova chat
```

> Use `source` (or `.`), not `./` — running it directly spawns a subshell and the exports won't carry over to your terminal.

Keep your credentials out of version control:

```bash
echo "setup-env.sh" >> .gitignore
```

#### Option B — Export manually each session

```bash
export AWS_ACCESS_KEY_ID="your-access-key-id"
export AWS_SECRET_ACCESS_KEY="your-secret-access-key"
export AWS_DEFAULT_REGION="us-east-1"

nova chat
```

---

### Verify the setup

```bash
aws sts get-caller-identity
```

You should see your AWS account ID and the IAM user ARN. If this works, Nova Code will work.

## Model

Nova Code uses **`global.amazon.nova-2-lite-v1:0`** (Amazon Nova 2 Lite) via Amazon Bedrock.

## Usage

### Help

```bash
nova --help
nova chat --help
```

### `nova chat` — interactive session

```bash
nova chat                       # start a new session (default)
nova chat -c                    # continue the most recent session
nova chat -r                    # pick a past session from an interactive list
nova chat --no-tools            # plain chat, no tool access
nova chat --auto-approve        # skip all tool approval prompts
nova chat --thinking high       # enable extended thinking (low/medium/high/auto)
```

Sessions are saved automatically after every exchange to:

```
~/.novacode/
└── projects/
    └── -Users-you-myproject/   # current directory (/ replaced with -)
        ├── 20260223T103000.json
        └── 20260223T154500.json
```

#### Starting fresh (default)

```
Nova Code  |  global.amazon.nova-2-lite-v1:0  |  Region: us-east-1  |  12 tools
New session  →  ~/.novacode/projects/-Users-you-myproject/20260223T103000.json
Type /help for commands, /exit to quit.

You:
```

#### Continue most recent (`-c`)

```
Nova Code  |  global.amazon.nova-2-lite-v1:0  |  Region: us-east-1  |  12 tools
Resuming session from 2026-02-23T10:30:00  (6 messages)
Type /help for commands, /exit to quit.

You:
```

#### Resume a specific session (`-r`)

```
Saved sessions for ~/.novacode/projects/-Users-you-myproject:
  1.  2026-02-23T10:30:00  (6 msgs)  "explain binary search"
  2.  2026-02-22T15:20:00  (2 msgs)  "how do I use async/await"
  3.  2026-02-21T09:10:00  (8 msgs)  "refactor this class"

Enter session number (or press Enter to cancel): 2

Nova Code  |  global.amazon.nova-2-lite-v1:0  |  Region: us-east-1  |  12 tools
Resuming session from 2026-02-22T15:20:00  (2 messages)
Type /help for commands, /exit to quit.

You:
```

**Slash commands inside chat:**

| Command                         | Description                                           |
|---------------------------------|-------------------------------------------------------|
| `/exit`                         | Quit the session                                      |
| `/clear`                        | Clear history and start a new session                 |
| `/tools`                        | List available tools                                  |
| `/auto-approve`                 | Toggle auto-approve on/off                            |
| `/thinking <level>`             | Set thinking effort: `off` / `low` / `medium` / `high` / `auto` |
| `/history`                      | List past sessions for this project                   |
| `/file <path> <message>`        | Attach a file (or line range) as context              |
| `/file <path>:<L1>-<L2> <msg>`  | Attach specific lines from a file as context          |
| `/help`                         | Show help                                             |

## Tools

Tools are enabled by default. The LLM uses them autonomously to answer questions about your codebase. Disable with `nova chat --no-tools`.

Read-only tools (file reads, search, web) run automatically. Write and execution tools (file edits, bash) prompt for approval before running, unless `--auto-approve` is set.

### Built-in tools

#### File system

| Tool               | Description                                                      |
|--------------------|------------------------------------------------------------------|
| `read_file`        | Read file contents (with optional line range, 1-indexed)         |
| `write_file`       | Write content to a file (creates parent dirs if needed)          |
| `edit_file`        | Find-and-replace an exact string in a file (must be unique)      |
| `multi_edit`       | Apply multiple find-and-replace edits atomically                 |
| `bash`             | Run a shell command and return output (30s timeout)              |
| `glob_files`       | Find files matching a glob pattern (`**/*.py`)                   |
| `grep`             | Search file contents with a regex (supports `*.{ts,tsx}` globs) |
| `list_directory`   | List files and subdirectories at a path                          |

#### Web

| Tool          | Description                                                                  |
|---------------|------------------------------------------------------------------------------|
| `web_search`  | Search the web via DuckDuckGo and return results (no API key required)       |
| `web_fetch`   | Fetch a URL and return its content as plain text                             |

#### Task tracking

| Tool          | Description                                                                  |
|---------------|------------------------------------------------------------------------------|
| `todo_read`   | Read the current to-do list (`~/.novacode_todos.json`)                       |
| `todo_write`  | Replace the to-do list with a new set of tasks                               |

#### Jupyter notebooks

| Tool             | Description                                                               |
|------------------|---------------------------------------------------------------------------|
| `notebook_read`  | Read all cells and outputs from a `.ipynb` notebook                       |
| `notebook_edit`  | Replace, insert, or delete a cell in a `.ipynb` notebook (0-indexed)      |

## Project instructions (NOVA.md)

Nova Code loads custom instructions from `NOVA.md` files at startup:

- **Global**: `~/.novacode/NOVA.md` — applied to every project
- **Per-project**: `<project-root>/NOVA.md` — applied only in that directory

Both files are concatenated and injected into the system prompt. Use them to give Nova persistent context about your stack, conventions, or preferences:

```markdown
# My Project

- This is a TypeScript monorepo using pnpm workspaces.
- Always use `const` over `let` unless reassignment is required.
- Prefer named exports over default exports.
```

## VS Code Extension

### Installation

1. Open the `vscode-extension/` directory
2. Run `npm install` then `npm run compile`
3. Press `F5` in VS Code to launch a development Extension Host, or package with `vsce package`

### Setup

Run the **Nova Code: Configure** command (Command Palette or `Cmd+Shift+P`) to enter:

- Python interpreter path (default: `python3` — must have `novacode` installed)
- AWS Region (default: `us-east-1`)
- AWS Access Key ID
- AWS Secret Access Key
- AWS Session Token (optional, for temporary credentials)

Credentials are stored in VS Code's `SecretStorage` (OS-level keychain). The Python path and region are stored in VS Code's global settings.

### Opening the chat

| Action | Shortcut |
|--------|----------|
| Nova Code: Open Chat | `Cmd+Shift+N` (Mac) / `Ctrl+Shift+N` (Windows/Linux) |
| Nova Code: Configure | Command Palette |

The chat panel opens in a side column. Nova Code spawns the Python `nova serve` process in the background on first open.

### Chat panel features

**Header controls:**
- **Conversations** — opens a quick-pick list of past sessions; the top entry is **+ New Conversation** (clears history and starts fresh); selecting any other entry resumes it and replays all previous messages in the thread
- **Auto-approve: Off / On** — when On, write and exec tools run without asking; toggles between states visually (highlighted when On)
- **Thinking** — set extended thinking effort per session: Off / Auto / Low / Medium / High (see [Extended thinking](#extended-thinking))

**Sending messages:**
- The input box is multi-line; press **Enter** to send, **Shift+Enter** for a newline
- The currently open file is always tracked and automatically injected as context even when the chat panel has focus — Nova can see what file you are editing without you having to mention it
- If you have text **selected** in an editor when you send, the selected lines are also included as context
- A **context badge** appears below your message bubble showing which file (and lines, if a selection was made) was attached

**Clickable file paths:**
- When Nova mentions a file path in its response, it is rendered as a clickable link
- Clicking it opens the file in the editor column to the left of the chat panel (not inside the chat panel)

**Tool approval:**
- When auto-approve is off, write/exec tools pause and show an approval dialog with a label and a color-coded diff preview
- `edit_file` and `write_file` show a diff (red = removed lines, green = added lines); `write_file` for a new file shows all lines in green
- For large diffs a **Show all ↓** toggle appears — click it to expand the full change, click **Collapse ↑** to shrink it back
- Click **Approve** to let the tool run, or **Reject** to open the rejection prompt
- In the rejection prompt: press Enter (or click **Stop**) to abort the turn; type `skip` to skip just that tool and continue; or type any instruction to redirect Nova

**Sessions:**
- Each conversation is saved to `~/.novacode/projects/<cwd-key>/` after every turn automatically
- Use the **Conversations** button to browse and resume any past session
- Resumed sessions replay all previous messages so you can see the full prior context

**Stop:** A **Stop** button appears while a turn is running; clicking it cancels generation at the next safe point (tool boundary or next streaming chunk).

### Output channel

Stderr from the Python process (tracebacks, debug output) appears in **View → Output → Nova Code**.

## Running without installing

```bash
python -m novacode --help
python -m novacode chat
```

## Extended thinking

Extended thinking lets Nova reason through hard problems before answering. It increases latency and token cost but improves accuracy on complex tasks.

```bash
nova chat --thinking low    # enable with minimum effort
nova chat --thinking high   # full reasoning depth
nova chat --thinking auto   # model decides how much to think
```

Or toggle mid-session with the `/thinking` slash command:

```
/thinking high
/thinking off
```

In the VS Code extension, use the **Thinking** buttons in the chat header. The setting persists for the duration of the session and can be changed at any time.

Thinking requires `amazon.nova-2-*` models and `us-east-1` (or a region that supports extended thinking on Nova 2).
