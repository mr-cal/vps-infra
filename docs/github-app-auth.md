# GitHub App Authentication Setup for Bot Automation

This guide explains how to set up a dedicated, repository-scoped GitHub App to replace classic personal access tokens for bot automation across `mr-cal/vps-infra`, `mr-cal/craft-dashboard`, and other websites.

---

## Overview: How Token Ownership & Attribution Work

### Who owns the token?
The **GitHub App itself** owns the token. When `mint_bot_token.py` exchanges an RS256 JWT for a token, GitHub returns an **Installation Access Token** (prefixed with `ghs_`).
- This token is **not** a Personal Access Token (PAT).
- It does **not** belong to `mr-cal` or any individual user.
- Actions taken by this token in the GitHub API and Git push events appear as **`mr-cal-bot[bot]`**.

### Who registers the App (`mr-cal` vs `mr-cal-bot`)?
You can register the GitHub App under **either account**:
- **Option A (Registered under `mr-cal-bot`)**: The App definition lives in `mr-cal-bot`'s Developer Settings. You then log into `mr-cal` and install it on `mr-cal/craft-dashboard` and `mr-cal/vps-infra`. This completely separates the app registration from your main account.
- **Option B (Registered under `mr-cal`)**: The App definition is created in `mr-cal`'s Developer Settings. `mr-cal` is merely the administrative creator/maintainer of the app. The token generated still belongs to the App (`[bot]`), not `mr-cal`.

In both cases, GitHub requires the repository owner (`mr-cal`) to approve installing the App onto the repositories.

### Who gets credit for commits?
**`mr-cal-bot` gets 100% of the credit.**
Git commit attribution is determined entirely by the author email in the commit metadata:
- Git sets `GIT_AUTHOR_NAME="mr-cal-bot"` and `GIT_AUTHOR_EMAIL="callahanlovesshopping@gmail.com"`.
- GitHub maps this email to `mr-cal-bot`.
- The commit history, code blame, and contribution activity display exclusively under `mr-cal-bot`. Your personal account (`mr-cal`) is never credited or linked to the code.

---

## Step 1: Register the GitHub App

1. Log in to GitHub (either as `mr-cal-bot` or `mr-cal`) and navigate to:
   **Settings → Developer settings → GitHub Apps → [New GitHub App](https://github.com/settings/apps/new)**
2. Fill in the App Details:
   - **GitHub App name**: `mr-cal-bot-craft` (or a name of your choice, e.g. `mr-cal-bot-infra`)
   - **Homepage URL**: `https://github.com/mr-cal/vps-infra`
3. Webhook:
   - **Active**: **Uncheck** / Disable (no webhook URL needed).
4. Repository Permissions:
   - **Contents**: `Access: Read and write` (to push commits and tags)
   - **Workflows**: `Access: Read and write` (to update GitHub Actions workflow files)
   - **Metadata**: `Access: Read-only` (selected automatically)
5. Where can this GitHub App be installed?
   - If registered under `mr-cal`: Select **"Only on this account"**.
   - If registered under `mr-cal-bot`: Select **"Any account"** (so you can install it into `mr-cal`'s repos).
6. Click **Create GitHub App**.

---

## Step 2: Generate Private Key and Note App ID

1. On the app settings page, locate the **App ID** near the top (e.g., `1234567`). Note this value.
2. Scroll down to the **Private keys** section and click **Generate a private key**.
3. An RSA `.pem` file will download automatically (e.g. `mr-cal-bot-craft.2026-09-28.private-key.pem`).
4. Save this file to a secure, uncommitted location (e.g., `~/.config/github-apps/mr-cal-bot-craft.pem`). Restrict file permissions:
   ```bash
   chmod 0600 ~/.config/github-apps/mr-cal-bot-craft.pem
   ```

---

## Step 3: Install the App on Selected Repositories

1. Navigate to the App's **Install App** tab:
   - If registered under `mr-cal`: Click **Install App** in the left sidebar, then click **Install** next to `mr-cal`.
   - If registered under `mr-cal-bot`: Click **Public link** (or go to `https://github.com/apps/<app-slug>`) while logged in as `mr-cal`, and click **Install**.
2. Select **"Only select repositories"** and choose:
   - `craft-dashboard`
   - `vps-infra`
3. Click **Install**.
4. Once installed, note the numeric `<INSTALLATION_ID>` from your browser URL:
   `https://github.com/settings/installations/<INSTALLATION_ID>`

---

## Step 4: Configure `.env.llm`

In `.env.llm` (in `vps-infra/.env.llm` and/or `craft-dashboard/.env.llm`), configure:

```bash
GITHUB_APP_ID=1234567
GITHUB_APP_INSTALLATION_ID=89101112
GITHUB_APP_PRIVATE_KEY_PATH=/home/callahan.kovacs@canonical.com/.config/github-apps/mr-cal-bot-craft.pem
```

---

## Step 5: Verify and Push

1. Run the check command to verify your credentials:
   ```bash
   /home/callahan.kovacs@canonical.com/dev/cal/vps-infra/scripts/mint_bot_token.py --check
   ```
2. Push changes:
   ```bash
   # Auto-detects current repo (craft-dashboard or vps-infra):
   git push "$(/home/callahan.kovacs@canonical.com/dev/cal/vps-infra/scripts/mint_bot_token.py --print-remote-url)" main
   ```
