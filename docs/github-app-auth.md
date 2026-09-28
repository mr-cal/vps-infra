# GitHub App Authentication Setup

This guide walks through creating a scoped GitHub App under your main account (`mr-cal`) to generate bot tokens for `mr-cal-bot`.

The app is installed only on `craft-dashboard` and `vps-infra`. Commits and pushes will appear as `mr-cal-bot`, keeping your personal account unassociated with automated code changes.

## Step 1: Register the GitHub App

1. Log in to GitHub as **`mr-cal`** and go to **Settings → Developer settings → GitHub Apps → [New GitHub App](https://github.com/settings/apps/new)**.
2. Fill in the required fields:
   - **GitHub App name**: `mr-cal-bot-craft`
   - **Homepage URL**: `https://github.com/mr-cal/vps-infra`
   - **Webhook**: Uncheck **Active** (no webhook needed).
3. Set repository permissions:
   - **Contents**: `Read and write`
   - **Workflows**: `Read and write`
   - **Metadata**: `Read-only` (selected automatically)
4. Under **Where can this GitHub App be installed?**, select **Only on this account**.
5. Click **Create GitHub App**.

## Step 2: Download the Private Key

1. Copy the numeric **App ID** displayed near the top of the app page.
2. Scroll down to **Private keys** and click **Generate a private key**.
3. A `.pem` file will download. Save it securely on your machine (for example, `~/.config/github-apps/mr-cal-bot-craft.pem`) and restrict its permissions:
   ```bash
   chmod 0600 ~/.config/github-apps/mr-cal-bot-craft.pem
   ```

## Step 3: Install the App on Repositories

1. Click **Install App** in the left sidebar of the app settings.
2. Click **Install** next to the `mr-cal` account.
3. Choose **Only select repositories** and select:
   - `craft-dashboard`
   - `vps-infra`
4. Click **Install**.
5. Note the numeric **Installation ID** in your browser URL (`https://github.com/settings/installations/<ID>`).

## Step 4: Configure .env.llm

Add these variables to your `.env.llm` file:

```bash
GITHUB_APP_ID=<app_id>
GITHUB_APP_INSTALLATION_ID=<installation_id>
GITHUB_APP_PRIVATE_KEY_PATH=/home/callahan.kovacs@canonical.com/.config/github-apps/mr-cal-bot-craft.pem
```

## Step 5: Test and Push

Verify the setup:
```bash
/home/callahan.kovacs@canonical.com/dev/cal/vps-infra/scripts/mint_bot_token.py --check
```

Push using the token:
```bash
git push "$(/home/callahan.kovacs@canonical.com/dev/cal/vps-infra/scripts/mint_bot_token.py --print-remote-url)" main
```
