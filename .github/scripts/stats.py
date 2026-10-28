"""Render GitHub stats cards (stats, top languages, streak, contribution graph) as SVGs.

Usage: python stats.py <login> <output-dir>   (reads GITHUB_TOKEN from the environment)
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from html import escape

BG, GOLD, BRIGHT, TEXT, MUTED, STROKE = "#0D0D0D", "#D4AF62", "#F5C76B", "#F4EBDD", "#8A8070", "#3A3226"
HEAT = ["#1C1A16", "#4A3E22", "#7A6332", "#A98A45", "#D4AF62"]
FONT = "font-family=\"'Segoe UI', Ubuntu, 'Helvetica Neue', Sans-Serif\""


def gql(query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {os.environ['GITHUB_TOKEN']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        body = json.load(r)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def fetch(login):
    user = gql("""
    query($login: String!) {
      user(login: $login) {
        createdAt
        pullRequests { totalCount }
        issues { totalCount }
        repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount }
        repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
          nodes {
            stargazerCount
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } }
          }
        }
      }
    }""", login=login)["user"]

    # Contribution calendars are capped at one year per query, so walk year by year since signup.
    days, commits_year = {}, 0
    start = dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    while start < now:
        end = min(start + dt.timedelta(days=365), now)
        cc = gql("""
        query($login: String!, $from: DateTime!, $to: DateTime!) {
          user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
              totalCommitContributions
              restrictedContributionsCount
              contributionCalendar { weeks { contributionDays { date contributionCount } } }
            }
          }
        }""", login=login, **{"from": start.isoformat(), "to": end.isoformat()})["user"]["contributionsCollection"]
        for w in cc["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
        if end == now:
            commits_year = cc["totalCommitContributions"] + cc["restrictedContributionsCount"]
        start = end
    user["days"] = dict(sorted(days.items()))
    user["commits_year"] = commits_year
    return user


def card(width, height, body, title=None):
    head = f'<text x="25" y="35" fill="{GOLD}" font-size="18" font-weight="600" {FONT}>{escape(title)}</text>' if title else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<rect width="{width}" height="{height}" rx="8" fill="{BG}"/>{head}{body}</svg>')


def stats_card(u):
    stars = sum(r["stargazerCount"] for r in u["repositories"]["nodes"])
    rows = [("Total Stars Earned", stars), ("Total Commits (last year)", u["commits_year"]),
            ("Total PRs", u["pullRequests"]["totalCount"]), ("Total Issues", u["issues"]["totalCount"]),
            ("Contributed to (last year)", u["repositoriesContributedTo"]["totalCount"])]
    body = "".join(
        f'<circle cx="32" cy="{68 + i * 25}" r="4" fill="{BRIGHT}"/>'
        f'<text x="45" y="{73 + i * 25}" fill="{TEXT}" font-size="14" {FONT}>{escape(k)}:</text>'
        f'<text x="400" y="{73 + i * 25}" fill="{TEXT}" font-size="14" font-weight="700" {FONT}>{v}</text>'
        for i, (k, v) in enumerate(rows))
    return card(467, 195, body, "Khushi Choudhary's GitHub Stats")


def langs_card(u, top=8):
    sizes = {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            n = e["node"]
            sizes.setdefault(n["name"], [0, n["color"] or MUTED])[0] += e["size"]
    ranked = sorted(sizes.items(), key=lambda kv: -kv[1][0])[:top]
    total = sum(s for _, (s, _) in ranked) or 1
    ranked = [kv for kv in ranked if kv[1][0] / total >= 0.001]  # drop languages that would read 0.0%
    bar, x = "", 25
    for _, (s, c) in ranked:
        w = 270 * s / total
        bar += f'<rect x="{x:.2f}" y="55" width="{w:.2f}" height="8" fill="{c}"/>'
        x += w
    legend = "".join(
        f'<circle cx="{30 + (i % 2) * 155}" cy="{87 + (i // 2) * 22}" r="5" fill="{c}"/>'
        f'<text x="{42 + (i % 2) * 155}" y="{91 + (i // 2) * 22}" fill="{TEXT}" font-size="12" {FONT}>{escape(n)} {100 * s / total:.1f}%</text>'
        for i, (n, (s, c)) in enumerate(ranked))
    clip = '<defs><clipPath id="r"><rect x="25" y="55" width="270" height="8" rx="4"/></clipPath></defs>'
    return card(320, 195, f'{clip}<g clip-path="url(#r)">{bar}</g>{legend}', "Most Used Languages")


def streaks(days):
    dates = list(days)
    today = dt.date.today().isoformat()
    longest = run = 0
    for d in dates:
        run = run + 1 if days[d] else 0
        longest = max(longest, run)
    current, i = 0, len(dates) - 1
    if i >= 0 and dates[i] == today and not days[today]:
        i -= 1  # today not over yet, so an empty today doesn't break the streak
    while i >= 0 and days[dates[i]]:
        current, i = current + 1, i - 1
    return sum(days.values()), current, longest


def streak_card(u):
    total, current, longest = streaks(u["days"])
    since = dt.date.fromisoformat(next(iter(u["days"]))).strftime("%b %-d, %Y" if os.name != "nt" else "%b %#d, %Y")
    cols = [(total, "Total Contributions", f"Since {since}"), (current, "Current Streak", "days"), (longest, "Longest Streak", "days")]
    body = ""
    for i, (num, label, sub) in enumerate(cols):
        cx = 82 + i * 166
        colour = BRIGHT if i == 1 else TEXT
        if i == 1:
            body += f'<circle cx="{cx}" cy="71" r="40" fill="none" stroke="{GOLD}" stroke-width="5"/>'
        body += (f'<text x="{cx}" y="{80 if i == 1 else 79}" text-anchor="middle" fill="{colour}" font-size="28" font-weight="700" {FONT}>{num}</text>'
                 f'<text x="{cx}" y="{140}" text-anchor="middle" fill="{GOLD if i == 1 else TEXT}" font-size="14" font-weight="600" {FONT}>{label}</text>'
                 f'<text x="{cx}" y="{162}" text-anchor="middle" fill="{MUTED}" font-size="12" {FONT}>{sub}</text>')
    body += "".join(f'<line x1="{x}" y1="28" x2="{x}" y2="170" stroke="{STROKE}" stroke-width="1"/>' for x in (165, 331))
    return card(495, 195, body)


def graph_card(u, weeks=53):
    end = dt.date.today()
    start = end - dt.timedelta(days=end.weekday() + 1 + 7 * (weeks - 1))  # Sunday, `weeks` weeks back
    peak = max(u["days"].values() or [1]) or 1
    cells, months, d = "", "", start
    while d <= end:
        col, row = (d - start).days // 7, (d - start).days % 7
        n = u["days"].get(d.isoformat(), 0)
        level = 0 if n == 0 else min(4, 1 + int(3 * n / peak))
        cells += f'<rect x="{30 + col * 15}" y="{30 + row * 15}" width="12" height="12" rx="2" fill="{HEAT[level]}"><title>{n} on {d}</title></rect>'
        if d.day <= 7 and row == 0:
            months += f'<text x="{30 + col * 15}" y="22" fill="{MUTED}" font-size="10" {FONT}>{d.strftime("%b")}</text>'
        d += dt.timedelta(days=1)
    return card(30 + weeks * 15 + 15, 145, months + cells)


def main():
    login, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    u = fetch(login)
    for name, svg in [("stats", stats_card(u)), ("top-langs", langs_card(u)), ("streak", streak_card(u)), ("contributions", graph_card(u))]:
        with open(os.path.join(out, f"{name}.svg"), "w", encoding="utf-8") as f:
            f.write(svg)
    print("wrote", out)


if __name__ == "__main__":
    main()
