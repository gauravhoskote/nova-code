#!/usr/bin/env bash
# setup-env.sh — Configure environment variables for Nova Code
#
# Usage:
#   source setup-env.sh        (recommended — exports persist in your shell)
#   . setup-env.sh             (shorthand for the above)
#
# Do NOT run it directly (./setup-env.sh) — exports won't carry over to your shell.

# ── Clear any stale credentials first ─────────────────────────────────────────
unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY
unset AWS_SESSION_TOKEN

# ── Required: AWS credentials ─────────────────────────────────────────────────
export AWS_ACCESS_KEY_ID="<your-access-key-id>"
export AWS_SECRET_ACCESS_KEY="<your-secret-access-key>"

# ── Required: AWS region ───────────────────────────────────────────────────────
# Must be us-east-1 for the default Nova 2 cross-region model.
export AWS_DEFAULT_REGION="us-east-1"

echo "Nova Code environment configured."
echo "  AWS_ACCESS_KEY_ID  : ${AWS_ACCESS_KEY_ID:0:8}... (masked)"
echo "  AWS_DEFAULT_REGION : $AWS_DEFAULT_REGION"
echo ""
echo "Run 'nova chat' to start."