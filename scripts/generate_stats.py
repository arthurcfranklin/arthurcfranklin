from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

ROOT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT_DIR / "assets"

USERNAME = os.getenv("GITHUB_USERNAME", "arthurcfranklin")
TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

CARD_WIDTH = 580
CARD_HEIGHT = 260

BACKGROUND_START = "#08090c"
BACKGROUND_END = "#111319"
PRIMARY_TEXT = "#f4f6f8"
SECONDARY_TEXT = "#aab3c0"
MUTED_TEXT = "#818b9b"
ACCENT = "#b6becb"
BORDER = "#ffffff"

LANGUAGE_COLORS: dict[str, str] = {
    "Python": "#3572A5",
    "HTML": "#E34C26",
    "CSS": "#663399",
    "JavaScript": "#F1E05A",
    "TypeScript": "#3178C6",
    "Shell": "#89E051",
    "PowerShell": "#012456",
    "Java": "#B07219",
    "C": "#555555",
    "C++": "#F34B7D",
    "C#": "#178600",
    "PHP": "#4F5D95",
    "Ruby": "#701516",
    "Go": "#00ADD8",
    "Rust": "#DEA584",
    "Kotlin": "#A97BFF",
    "Swift": "#F05138",
    "Vue": "#41B883",
    "Jupyter Notebook": "#DA5B0B",
}


@dataclass
class LanguageStat:
    name: str
    size: int
    percentage: float
    color: str


@dataclass
class GitHubStats:
    username: str
    public_repositories: int
    followers: int
    following: int
    total_contributions: int
    commit_contributions: int
    issue_contributions: int
    pull_request_contributions: int
    pull_request_review_contributions: int
    restricted_contributions: int
    stars: int
    forks: int
    watchers: int
    current_streak: int
    longest_streak: int
    active_days: int
    contribution_start: str
    contribution_end: str
    languages: list[LanguageStat]
    updated_at: str
    demo_mode: bool = False


GRAPHQL_QUERY = """
query ProfileStatistics(
  $login: String!,
  $from: DateTime!,
  $to: DateTime!,
  $repositoryCursor: String
) {
  user(login: $login) {
    login
    followers {
      totalCount
    }
    following {
      totalCount
    }
    repositories(
      first: 100,
      after: $repositoryCursor,
      ownerAffiliations: OWNER,
      privacy: PUBLIC,
      isFork: false,
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      totalCount
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        isArchived
        forkCount
        stargazerCount
        watchers {
          totalCount
        }
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
              color
            }
          }
        }
      }
    }
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def graphql_request(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not configured.")

    request_body = json.dumps(
        {
            "query": query,
            "variables": variables,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        GITHUB_GRAPHQL_URL,
        data=request_body,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": f"{USERNAME}-github-profile-stats",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API returned HTTP {exc.code}: {response_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not connect to the GitHub API: {exc}") from exc

    if payload.get("errors"):
        messages = "; ".join(
            error.get("message", "Unknown GraphQL error")
            for error in payload["errors"]
        )
        raise RuntimeError(f"GitHub GraphQL error: {messages}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise TypeError("GitHub API returned an invalid response type.")

    return data


def iso_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def contribution_period() -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365)
    return start, end


def calculate_streaks(
    contribution_days: list[dict[str, Any]],
) -> tuple[int, int, int]:
    contributions_by_date: dict[date, int] = {}

    for item in contribution_days:
        try:
            day = date.fromisoformat(str(item["date"]))
            count = int(item.get("contributionCount", 0))
        except (KeyError, TypeError, ValueError):
            continue

        contributions_by_date[day] = count

    if not contributions_by_date:
        return 0, 0, 0

    ordered_dates = sorted(contributions_by_date)
    active_days = sum(
        1 for count in contributions_by_date.values() if count > 0
    )

    longest_streak = 0
    running_streak = 0

    for day in ordered_dates:
        if contributions_by_date[day] > 0:
            running_streak += 1
            longest_streak = max(longest_streak, running_streak)
        else:
            running_streak = 0

    current_streak = 0
    today = datetime.now(timezone.utc).date()

    last_available_day = ordered_dates[-1]

    if last_available_day < today:
        streak_cursor = last_available_day
    else:
        streak_cursor = today

    if contributions_by_date.get(streak_cursor, 0) == 0:
        previous_day = streak_cursor - timedelta(days=1)

        if contributions_by_date.get(previous_day, 0) > 0:
            streak_cursor = previous_day
        else:
            return 0, longest_streak, active_days

    while contributions_by_date.get(streak_cursor, 0) > 0:
        current_streak += 1
        streak_cursor -= timedelta(days=1)

    return current_streak, longest_streak, active_days


def aggregate_languages(
    repository_nodes: list[dict[str, Any]],
    limit: int = 5,
) -> list[LanguageStat]:
    totals: defaultdict[str, int] = defaultdict(int)
    colors: dict[str, str] = {}

    for repository in repository_nodes:
        if repository.get("isArchived"):
            continue

        language_edges = (
            repository.get("languages", {}).get("edges", [])
            if isinstance(repository.get("languages"), dict)
            else []
        )

        for edge in language_edges:
            node = edge.get("node") or {}
            name = node.get("name")
            size = edge.get("size", 0)

            if not name:
                continue

            try:
                numeric_size = int(size)
            except (TypeError, ValueError):
                continue

            totals[name] += numeric_size

            api_color = node.get("color")
            colors[name] = (
                api_color
                or LANGUAGE_COLORS.get(name)
                or "#8f99a8"
            )

    total_size = sum(totals.values())

    if total_size <= 0:
        return []

    ordered = sorted(
        totals.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:limit]

    return [
        LanguageStat(
            name=name,
            size=size,
            percentage=(size / total_size) * 100,
            color=colors.get(name, "#8f99a8"),
        )
        for name, size in ordered
    ]


def fetch_github_stats() -> GitHubStats:
    start, end = contribution_period()
    repository_cursor: str | None = None

    repositories: list[dict[str, Any]] = []
    user_data: dict[str, Any] | None = None
    contributions: dict[str, Any] | None = None

    while True:
        variables = {
            "login": USERNAME,
            "from": iso_datetime(start),
            "to": iso_datetime(end),
            "repositoryCursor": repository_cursor,
        }

        data = graphql_request(GRAPHQL_QUERY, variables)
        current_user = data.get("user")

        if not current_user:
            raise RuntimeError(f"GitHub user '{USERNAME}' was not found.")

        if user_data is None:
            user_data = current_user
            contributions = current_user["contributionsCollection"]

        repository_connection = current_user["repositories"]
        repositories.extend(repository_connection.get("nodes") or [])

        page_info = repository_connection["pageInfo"]

        if not page_info.get("hasNextPage"):
            break

        repository_cursor = page_info.get("endCursor")

        if not repository_cursor:
            break

    assert user_data is not None
    assert contributions is not None

    calendar = contributions["contributionCalendar"]

    contribution_days = [
        contribution_day
        for week in calendar.get("weeks", [])
        for contribution_day in week.get("contributionDays", [])
    ]

    current_streak, longest_streak, active_days = calculate_streaks(
        contribution_days
    )

    stars = sum(
        int(repository.get("stargazerCount", 0))
        for repository in repositories
    )
    forks = sum(
        int(repository.get("forkCount", 0))
        for repository in repositories
    )
    watchers = sum(
        int((repository.get("watchers") or {}).get("totalCount", 0))
        for repository in repositories
    )

    languages = aggregate_languages(repositories)

    return GitHubStats(
        username=str(user_data["login"]),
        public_repositories=int(user_data["repositories"]["totalCount"]),
        followers=int(user_data["followers"]["totalCount"]),
        following=int(user_data["following"]["totalCount"]),
        total_contributions=int(calendar["totalContributions"]),
        commit_contributions=int(
            contributions["totalCommitContributions"]
        ),
        issue_contributions=int(
            contributions["totalIssueContributions"]
        ),
        pull_request_contributions=int(
            contributions["totalPullRequestContributions"]
        ),
        pull_request_review_contributions=int(
            contributions["totalPullRequestReviewContributions"]
        ),
        restricted_contributions=int(
            contributions["restrictedContributionsCount"]
        ),
        stars=stars,
        forks=forks,
        watchers=watchers,
        current_streak=current_streak,
        longest_streak=longest_streak,
        active_days=active_days,
        contribution_start=start.date().isoformat(),
        contribution_end=end.date().isoformat(),
        languages=languages,
        updated_at=end.strftime("%b %d, %Y"),
        demo_mode=False,
    )


def demo_stats() -> GitHubStats:
    today = datetime.now(timezone.utc)

    return GitHubStats(
        username=USERNAME,
        public_repositories=10,
        followers=12,
        following=18,
        total_contributions=325,
        commit_contributions=132,
        issue_contributions=8,
        pull_request_contributions=1,
        pull_request_review_contributions=0,
        restricted_contributions=0,
        stars=1,
        forks=0,
        watchers=1,
        current_streak=1,
        longest_streak=6,
        active_days=74,
        contribution_start=(today - timedelta(days=365)).date().isoformat(),
        contribution_end=today.date().isoformat(),
        languages=[
            LanguageStat("Python", 4530, 45.30, "#3572A5"),
            LanguageStat("HTML", 3468, 34.68, "#E34C26"),
            LanguageStat("CSS", 1604, 16.04, "#663399"),
            LanguageStat("JavaScript", 398, 3.98, "#F1E05A"),
        ],
        updated_at=today.strftime("%b %d, %Y"),
        demo_mode=True,
    )


def card_shell(title: str, subtitle: str, content: str) -> str:
    safe_title = escape(title)
    safe_subtitle = escape(subtitle)

    return f"""<svg
  xmlns="http://www.w3.org/2000/svg"
  width="{CARD_WIDTH}"
  height="{CARD_HEIGHT}"
  viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}"
  role="img"
  aria-label="{safe_title}"
>
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{BACKGROUND_START}" />
      <stop offset="100%" stop-color="{BACKGROUND_END}" />
    </linearGradient>

    <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
      <path
        d="M28 0H0V28"
        fill="none"
        stroke="#ffffff"
        stroke-opacity="0.025"
        stroke-width="1"
      />
    </pattern>
  </defs>

  <rect
    width="{CARD_WIDTH}"
    height="{CARD_HEIGHT}"
    rx="16"
    fill="url(#background)"
  />

  <rect
    width="{CARD_WIDTH}"
    height="{CARD_HEIGHT}"
    rx="16"
    fill="url(#grid)"
  />

  <rect
    x="26"
    y="25"
    width="50"
    height="3"
    rx="1.5"
    fill="{ACCENT}"
  />

  <text
    x="26"
    y="61"
    fill="{PRIMARY_TEXT}"
    font-family="Inter, Segoe UI, Arial, sans-serif"
    font-size="21"
    font-weight="700"
  >{safe_title}</text>

  <text
    x="26"
    y="84"
    fill="{MUTED_TEXT}"
    font-family="Inter, Segoe UI, Arial, sans-serif"
    font-size="11"
    font-weight="500"
  >{safe_subtitle}</text>

  <path
    d="M26 101H554"
    stroke="#ffffff"
    stroke-opacity="0.075"
  />

{content}

  <rect
    x="0.75"
    y="0.75"
    width="578.5"
    height="258.5"
    rx="15.25"
    fill="none"
    stroke="{BORDER}"
    stroke-opacity="0.09"
    stroke-width="1.5"
  />
</svg>
"""


def metric(
    x: int,
    y: int,
    value: str | int,
    label: str,
) -> str:
    return f"""  <text
    x="{x}"
    y="{y}"
    fill="{PRIMARY_TEXT}"
    font-family="Inter, Segoe UI, Arial, sans-serif"
    font-size="25"
    font-weight="700"
  >{escape(str(value))}</text>

  <text
    x="{x}"
    y="{y + 20}"
    fill="{MUTED_TEXT}"
    font-family="Inter, Segoe UI, Arial, sans-serif"
    font-size="10"
    font-weight="600"
    letter-spacing="0.7"
  >{escape(label.upper())}</text>
"""


def generate_github_overview(stats: GitHubStats) -> str:
    content = (
        metric(26, 145, stats.total_contributions, "Contributions")
        + metric(205, 145, stats.commit_contributions, "Commits")
        + metric(382, 145, stats.pull_request_contributions, "Pull requests")
        + metric(26, 211, stats.issue_contributions, "Issues")
        + metric(205, 211, stats.public_repositories, "Repositories")
        + metric(382, 211, stats.followers, "Followers")
    )

    return card_shell(
        "GitHub Overview",
        "Development activity across public repositories.",
        content,
    )


def generate_repository_overview(stats: GitHubStats) -> str:
    content = (
        metric(26, 145, stats.public_repositories, "Public repositories")
        + metric(205, 145, stats.stars, "Stars earned")
        + metric(382, 145, stats.forks, "Repository forks")
        + metric(26, 211, stats.watchers, "Watchers")
        + metric(205, 211, stats.followers, "Followers")
        + metric(382, 211, stats.following, "Following")
    )

    return card_shell(
        "Repository Overview",
        "Public repository reach and engagement.",
        content,
    )


def generate_contribution_streak(stats: GitHubStats) -> str:
    content = (
        metric(26, 145, stats.current_streak, "Current streak")
        + metric(205, 145, stats.longest_streak, "Longest streak")
        + metric(382, 145, stats.active_days, "Active days")
        + f"""  <text
    x="26"
    y="211"
    fill="{SECONDARY_TEXT}"
    font-family="Inter, Segoe UI, Arial, sans-serif"
    font-size="12"
    font-weight="500"
  >{escape(stats.contribution_start)} — {escape(stats.contribution_end)}</text>

  <text
    x="26"
    y="233"
    fill="{MUTED_TEXT}"
    font-family="Inter, Segoe UI, Arial, sans-serif"
    font-size="10"
    font-weight="500"
  >Updated {escape(stats.updated_at)}</text>
"""
    )

    return card_shell(
        "Contribution Streak",
        "Consistency across the last twelve months.",
        content,
    )


def generate_language_bar(
    languages: list[LanguageStat],
    x: float,
    y: float,
    width: float,
    height: float,
) -> str:
    if not languages:
        return f"""  <rect
    x="{x}"
    y="{y}"
    width="{width}"
    height="{height}"
    rx="{height / 2}"
    fill="#242832"
  />
"""

    output: list[str] = []
    current_x = x

    for index, language in enumerate(languages):
        segment_width = width * (language.percentage / 100)

        if index == len(languages) - 1:
            segment_width = x + width - current_x

        output.append(
            f"""  <rect
    x="{current_x:.2f}"
    y="{y}"
    width="{max(segment_width, 0):.2f}"
    height="{height}"
    fill="{escape(language.color)}"
  />
"""
        )

        current_x += segment_width

    output.append(
        f"""  <rect
    x="{x}"
    y="{y}"
    width="{width}"
    height="{height}"
    rx="{height / 2}"
    fill="none"
    stroke="#ffffff"
    stroke-opacity="0.08"
  />
"""
    )

    return "".join(output)


def generate_most_used_languages(stats: GitHubStats) -> str:
    languages = stats.languages[:5]

    bar = generate_language_bar(
        languages,
        x=26,
        y=121,
        width=528,
        height=10,
    )

    legend_items: list[str] = []

    positions = [
        (26, 170),
        (292, 170),
        (26, 211),
        (292, 211),
        (26, 243),
    ]

    for language, (x, y) in zip(languages, positions):
        legend_items.append(
            f"""  <circle
    cx="{x + 5}"
    cy="{y - 4}"
    r="5"
    fill="{escape(language.color)}"
  />

  <text
    x="{x + 18}"
    y="{y}"
    fill="{SECONDARY_TEXT}"
    font-family="Inter, Segoe UI, Arial, sans-serif"
    font-size="12"
    font-weight="600"
  >{escape(language.name)}</text>

  <text
    x="{x + 18}"
    y="{y + 17}"
    fill="{MUTED_TEXT}"
    font-family="Inter, Segoe UI, Arial, sans-serif"
    font-size="10"
    font-weight="500"
  >{language.percentage:.2f}%</text>
"""
        )

    if not languages:
        legend_items.append(
            f"""  <text
    x="26"
    y="178"
    fill="{MUTED_TEXT}"
    font-family="Inter, Segoe UI, Arial, sans-serif"
    font-size="13"
  >No language data available.</text>
"""
        )

    return card_shell(
        "Most Used Languages",
        "Language distribution across public repositories.",
        bar + "".join(legend_items),
    )


def write_svg(filename: str, content: str) -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    output_path = ASSETS_DIR / filename
    output_path.write_text(content, encoding="utf-8")

    print(f"Generated: {output_path.relative_to(ROOT_DIR)}")


def generate_all_cards(stats: GitHubStats) -> None:
    write_svg(
        "github-overview.svg",
        generate_github_overview(stats),
    )
    write_svg(
        "most-used-languages.svg",
        generate_most_used_languages(stats),
    )
    write_svg(
        "contribution-streak.svg",
        generate_contribution_streak(stats),
    )
    write_svg(
        "repository-overview.svg",
        generate_repository_overview(stats),
    )


def main() -> int:
    print(f"Generating GitHub statistics for @{USERNAME}")

    if TOKEN:
        try:
            stats = fetch_github_stats()
            print("GitHub API data loaded successfully.")
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    else:
        print(
            "GITHUB_TOKEN was not found. "
            "Generating demonstration cards only."
        )
        stats = demo_stats()

    generate_all_cards(stats)

    if stats.demo_mode:
        print("Done. Demonstration data was used.")
    else:
        print("Done. Live GitHub data was used.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())