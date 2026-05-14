#!/usr/bin/env python3
"""Daily sports scores newsletter — NHL, MLB, NFL via ESPN public API."""

import json
import os
import smtplib
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SPORTS = [
    {
        "path": "hockey/nhl",
        "label": "NHL Hockey",
        "color": "#000000",
        "accent": "#FCB514",
        "icon": "🏒",
    },
    {
        "path": "baseball/mlb",
        "label": "MLB Baseball",
        "color": "#003087",
        "accent": "#D50032",
        "icon": "⚾",
    },
    {
        "path": "football/nfl",
        "label": "NFL Football",
        "color": "#013369",
        "accent": "#D50A0A",
        "icon": "🏈",
    },
]

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def yesterday_eastern():
    """Return (YYYYMMDD, 'Month DD, YYYY') for yesterday in US/Eastern.

    The cron fires at 13:00 UTC which is 8 AM EST / 9 AM EDT.  Either way
    subtracting one day from UTC noon always lands on the correct calendar
    date for Eastern yesterday.
    """
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    return yesterday.strftime("%Y%m%d"), yesterday.strftime("%B %d, %Y")


# ---------------------------------------------------------------------------
# ESPN API
# ---------------------------------------------------------------------------

def fetch_scoreboard(sport_path: str, date_str: str) -> dict | None:
    url = f"{ESPN_BASE}/{sport_path}/scoreboard?dates={date_str}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sports-newsletter/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        print(f"  Warning: failed to fetch {sport_path}: {exc}")
        return None


def parse_games(data: dict | None) -> list[dict]:
    if not data or "events" not in data:
        return []

    games = []
    for event in data["events"]:
        comp = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        status_block = comp.get("status", {})
        status_type = status_block.get("type", {})

        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue

        home_score = home.get("score", "")
        away_score = away.get("score", "")
        completed = status_type.get("completed", False)
        status_text = status_block.get("type", {}).get("shortDetail", "")

        winner = None
        if completed and home_score and away_score:
            try:
                if int(float(home_score)) > int(float(away_score)):
                    winner = "home"
                elif int(float(away_score)) > int(float(home_score)):
                    winner = "away"
            except ValueError:
                pass

        games.append(
            {
                "home_team": home.get("team", {}).get("displayName", "TBD"),
                "home_score": home_score,
                "away_team": away.get("team", {}).get("displayName", "TBD"),
                "away_score": away_score,
                "status": status_text,
                "completed": completed,
                "winner": winner,
            }
        )

    return games


# ---------------------------------------------------------------------------
# HTML building
# ---------------------------------------------------------------------------

def _game_row(game: dict) -> str:
    def style(side: str) -> str:
        bold = "font-weight:700;" if game["winner"] == side else "font-weight:400;"
        return bold

    status_color = "#27ae60" if game["completed"] else "#e67e22"

    return f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td style="font-size:14px;{style('away')}color:#1a1a1a;padding-bottom:4px;">
                  {game['away_team']}
                </td>
                <td style="font-size:20px;{style('away')}color:#1a1a1a;text-align:right;
                           padding-bottom:4px;min-width:36px;">
                  {game['away_score']}
                </td>
              </tr>
              <tr>
                <td style="font-size:14px;{style('home')}color:#1a1a1a;">
                  {game['home_team']}
                  <span style="font-size:11px;color:#aaa;font-weight:400;"> HOME</span>
                </td>
                <td style="font-size:20px;{style('home')}color:#1a1a1a;text-align:right;
                           min-width:36px;">
                  {game['home_score']}
                </td>
              </tr>
            </table>
            <div style="margin-top:6px;">
              <span style="font-size:11px;font-weight:600;color:{status_color};
                           text-transform:uppercase;letter-spacing:0.4px;">
                {game['status']}
              </span>
            </div>
          </td>
        </tr>"""


def _sport_section(sport: dict, games: list[dict], date_display: str) -> str:
    if games:
        rows = "\n".join(_game_row(g) for g in games)
        count_label = f"{len(games)} game{'s' if len(games) != 1 else ''}"
    else:
        rows = f"""
        <tr>
          <td style="padding:20px 16px;text-align:center;color:#999;font-size:14px;
                     font-style:italic;">
            No games scheduled for {date_display}
          </td>
        </tr>"""
        count_label = "No games"

    return f"""
  <div style="margin-bottom:24px;border-radius:10px;overflow:hidden;
              box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <!-- Sport header -->
    <div style="background:{sport['color']};padding:14px 16px;
                display:flex;align-items:center;justify-content:space-between;">
      <span style="color:#fff;font-size:15px;font-weight:700;letter-spacing:0.3px;">
        {sport['icon']}&nbsp; {sport['label']}
      </span>
      <span style="color:rgba(255,255,255,0.65);font-size:12px;">{count_label}</span>
    </div>
    <!-- Games -->
    <div style="background:#fff;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        {rows}
      </table>
    </div>
  </div>"""


def build_html(sections_html: list[str], date_display: str) -> str:
    body = "\n".join(sections_html)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Daily Sports Scores — {date_display}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
             Helvetica,Arial,sans-serif;">

  <div style="max-width:560px;margin:0 auto;padding:24px 16px 32px;">

    <!-- ── Header ── -->
    <div style="background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);
                border-radius:12px;padding:28px 24px;margin-bottom:24px;
                text-align:center;">
      <div style="font-size:32px;margin-bottom:10px;">🏆</div>
      <h1 style="margin:0 0 6px;color:#fff;font-size:22px;font-weight:700;
                 letter-spacing:0.5px;">
        Daily Sports Scores
      </h1>
      <p style="margin:0;color:#a0aec0;font-size:14px;">{date_display}</p>
    </div>

    <!-- ── Sport sections ── -->
    {body}

    <!-- ── Footer ── -->
    <div style="text-align:center;padding-top:8px;">
      <p style="margin:0;color:#bbb;font-size:12px;">
        Scores sourced from ESPN &middot; Sent automatically every morning
      </p>
    </div>

  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(
    to_addr: str,
    from_addr: str,
    app_password: str,
    subject: str,
    html_body: str,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_addr, app_password)
        server.sendmail(from_addr, to_addr, msg.as_string())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    to_addr = os.environ.get("REPORT_RECIPIENT", "").strip()
    from_addr = os.environ.get("GMAIL_ADDRESS", "").strip()
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    missing = [
        name
        for name, val in [
            ("REPORT_RECIPIENT", to_addr),
            ("GMAIL_ADDRESS", from_addr),
            ("GMAIL_APP_PASSWORD", app_password),
        ]
        if not val
    ]
    if missing:
        raise SystemExit(f"Missing environment variable(s): {', '.join(missing)}")

    date_str, date_display = yesterday_eastern()
    print(f"Fetching scores for {date_display} ({date_str})")

    sections = []
    for sport in SPORTS:
        print(f"  Fetching {sport['label']} ...", end=" ", flush=True)
        data = fetch_scoreboard(sport["path"], date_str)
        games = parse_games(data)
        print(f"{len(games)} game(s)")
        sections.append(_sport_section(sport, games, date_display))

    html = build_html(sections, date_display)
    subject = f"🏆 Sports Scores — {date_display}"

    print(f"Sending newsletter to {to_addr} ...")
    send_email(to_addr, from_addr, app_password, subject, html)
    print("Done.")


if __name__ == "__main__":
    main()
