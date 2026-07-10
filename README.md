# CROUS Grenoble monitor

This script monitors three CROUS searches separately:

- Grenoble
- Saint-Martin-d'Hères
- La Tronche

It sends Telegram notifications when a listing appears, disappears, or when the displayed result count changes.

## GitHub secrets

Create these repository secrets under **Settings → Secrets and variables → Actions**:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Running

The GitHub Actions workflow runs automatically every 20 minutes. You can also launch it manually from **Actions → CROUS monitor (Grenoble area) → Run workflow**.

The first successful run creates `crous_grenoble_state.json` and sends one initialization message for each monitored location. Later runs only send updates.
