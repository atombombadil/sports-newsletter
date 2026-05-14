# Daily Sports Newsletter

Sends a clean HTML email every morning with the previous day's box scores for **NHL**, **MLB**, and **NFL** — powered by the ESPN public API (no API key required) and delivered via Gmail.

---

## What you get

- One email per day, sent automatically at **8 AM EST** (9 AM EDT in summer)
- Scores for every completed game in NHL, MLB, and NFL
- Winner highlighted in bold; game status shown in green (Final) or orange (in-progress/postponed)
- Graceful "No games scheduled" message during off-season

---

## Setup

### 1. Create a Gmail App Password

Gmail requires an **App Password** when sending email from a script (regular passwords won't work if 2-Step Verification is enabled, which it must be).

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Under *How you sign in to Google*, click **2-Step Verification** and make sure it's on
3. Return to the Security page and search for **App passwords** (or go directly to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords))
4. Create a new app password — name it anything (e.g. *Sports Newsletter*)
5. Copy the 16-character password shown — you won't see it again

### 2. Add GitHub Secrets

In your repository on GitHub:

1. Go to **Settings → Secrets and variables → Actions → New repository secret**
2. Add these three secrets:

| Secret name | Value |
|---|---|
| `GMAIL_ADDRESS` | Your Gmail address (e.g. `you@gmail.com`) |
| `GMAIL_APP_PASSWORD` | The 16-character App Password from step 1 |
| `TO_EMAIL` | The address to deliver the newsletter to |

`TO_EMAIL` can be the same as `GMAIL_ADDRESS` or any other address you control.

### 3. Push to GitHub and enable Actions

```bash
git add .
git commit -m "Add daily sports newsletter"
git push
```

Then go to the **Actions** tab in your repository and confirm workflows are enabled.

---

## Test it manually

After pushing, you can trigger an immediate send without waiting for the scheduled time:

1. Go to **Actions → Daily Sports Newsletter**
2. Click **Run workflow → Run workflow**

Check your inbox in about 30 seconds.

---

## Adjust the send time

The workflow runs at `0 13 * * *` UTC (= 8 AM EST, 9 AM EDT).

To change the time, edit `.github/workflows/daily-newsletter.yml` and update the `cron` line.  
UTC offset reference:

| Target time | Cron (UTC) |
|---|---|
| 7 AM EST / 8 AM EDT | `0 12 * * *` |
| **8 AM EST / 9 AM EDT** | `0 13 * * *` ← default |
| 9 AM EST / 10 AM EDT | `0 14 * * *` |

---

## Run locally

```bash
export GMAIL_ADDRESS="you@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
export TO_EMAIL="you@gmail.com"

python send_newsletter.py
```

No dependencies beyond the Python standard library (Python 3.9+ required).

---

## File overview

```
send_newsletter.py                  # Main script
.github/
  workflows/
    daily-newsletter.yml            # GitHub Actions schedule
README.md                           # This file
```
