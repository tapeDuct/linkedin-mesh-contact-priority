#!/usr/bin/env python3
"""Prepare a reviewed LinkedIn orphan-prospect queue.

This tool deliberately does not create records or send messages.  It turns a
LinkedIn Connections export, a LinkedIn Messages export, and (when available)
a me.sh activity snapshot into a CSV and Markdown review pack.  A separate
Codex/me.sh adapter should apply only human-approved rows.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit


CONNECTION_HEADERS = {"First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"}
MESSAGE_HEADERS = {"CONVERSATION ID", "FROM", "SENDER PROFILE URL", "TO", "RECIPIENT PROFILE URLS", "DATE", "CONTENT"}
ME_HEADERS = {"email", "linkedin_url", "full_name", "company", "last_activity_at"}
DECISION_COLUMNS = [
    "decision", "candidate_type", "priority_score", "match_confidence", "full_name", "company", "position",
    "linkedin_url", "email", "last_linkedin_activity", "linkedin_context", "me_sh_state",
    "me_sh_last_activity", "relevance_reason", "proposed_context", "recommended_action", "evidence",
]

EXECUTIVE_TITLE = re.compile(
    r"\b(chief|ceo|cfo|coo|cto|cio|cmo|cso|co[- ]?founder|founder|owner|president|"
    r"managing director|managing partner)\b", re.IGNORECASE
)
LEADERSHIP_TITLE = re.compile(
    r"\b(vice president|vp|head of|general manager|partner|principal)\b", re.IGNORECASE
)
DIRECTOR_TITLE = re.compile(r"\bdirector\b", re.IGNORECASE)
SYSTEM_MESSAGE = re.compile(r"(you are now connected|sent you a connection request|accepted your connection request)", re.IGNORECASE)


@dataclass(frozen=True)
class Connection:
    first_name: str
    last_name: str
    url: str
    email: str
    company: str
    position: str

    @property
    def name(self) -> str:
        return " ".join(x for x in (self.first_name, self.last_name) if x).strip()


@dataclass(frozen=True)
class Activity:
    timestamp: datetime
    direction: str
    content: str


def normalise(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def normalise_url(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    host = parsed.netloc.casefold().removeprefix("www.")
    path = parsed.path.rstrip("/").casefold()
    return urlunsplit(("https", host, path, "", ""))


def csv_rows(path: Path, required_headers: set[str]) -> list[dict[str, str]]:
    """Find a CSV header even when LinkedIn prepends explanatory lines."""
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))
    header_index = next(
        (index for index, row in enumerate(rows) if required_headers.issubset(set(row))), None
    )
    if header_index is None:
        raise ValueError(f"{path.name} does not contain the expected headers: {sorted(required_headers)}")
    header = rows[header_index]
    return [dict(zip(header, row)) for row in rows[header_index + 1 :] if any(cell.strip() for cell in row)]


def parse_date(value: str) -> datetime:
    value = value.strip().replace(" UTC", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def connection_key(name: str, company: str) -> tuple[str, str]:
    return normalise(name), normalise(company)


def relevance(connection: Connection) -> tuple[int, str]:
    """Conservative local pre-filter; Apollo should validate survivors before approval."""
    if EXECUTIVE_TITLE.search(connection.position):
        return 3, "Executive/founder title in LinkedIn profile; validate current role with Apollo"
    if LEADERSHIP_TITLE.search(connection.position):
        return 2, "Leadership title in LinkedIn profile; validate scope and current role with Apollo"
    if DIRECTOR_TITLE.search(connection.position):
        return 1, "Director title in LinkedIn profile; requires Apollo relevance validation"
    return 0, "No decision-maker title signal"


def message_activity(rows: Iterable[dict[str, str]], self_url: str) -> tuple[dict[str, list[Activity]], int]:
    self_url = normalise_url(self_url)
    activities: dict[str, list[Activity]] = defaultdict(list)
    skipped_group_or_system = 0
    for row in rows:
        content = re.sub(r"\s+", " ", row.get("CONTENT", "")).strip()
        sender = normalise_url(row.get("SENDER PROFILE URL"))
        recipients = [normalise_url(part) for part in re.findall(r"https?://[^\s,;]+", row.get("RECIPIENT PROFILE URLS", ""))]
        if not content or SYSTEM_MESSAGE.search(content):
            skipped_group_or_system += 1
            continue
        if sender == self_url and len(recipients) == 1 and recipients[0] != self_url:
            counterparty, direction = recipients[0], "outbound"
        elif len(recipients) == 1 and recipients[0] == self_url and sender and sender != self_url:
            counterparty, direction = sender, "inbound"
        else:
            skipped_group_or_system += 1
            continue
        if not counterparty:
            skipped_group_or_system += 1
            continue
        activities[counterparty].append(Activity(parse_date(row["DATE"]), direction, content))
    for activity_list in activities.values():
        activity_list.sort(key=lambda item: item.timestamp)
    return activities, skipped_group_or_system


def load_me_snapshot(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    rows = csv_rows(path, ME_HEADERS)
    return [{normalise(key): value.strip() for key, value in row.items()} for row in rows]


def me_match(connection: Connection, me_rows: list[dict[str, str]]) -> tuple[str, dict[str, str] | None]:
    if not me_rows:
        return "unverified", None
    by_url = [row for row in me_rows if normalise_url(row.get("linkedin_url")) and normalise_url(row.get("linkedin_url")) == normalise_url(connection.url)]
    by_email = [row for row in me_rows if connection.email and normalise(row.get("email")) == normalise(connection.email)]
    exact = by_url or by_email
    if len(exact) == 1:
        return "exact", exact[0]
    if len(exact) > 1:
        return "ambiguous", None
    name_company = [row for row in me_rows if connection_key(row.get("full_name", ""), row.get("company", "")) == connection_key(connection.name, connection.company)]
    if len(name_company) == 1:
        return "review", name_company[0]
    return ("ambiguous", None) if len(name_company) > 1 else ("missing", None)


def activity_within_90_days(row: dict[str, str] | None, cutoff: datetime) -> bool:
    if not row or not row.get("last_activity_at"):
        return False
    try:
        return parse_date(row["last_activity_at"]) >= cutoff
    except ValueError:
        return False


def build_candidates(
    connections: list[Connection],
    activities: dict[str, list[Activity]],
    me_rows: list[dict[str, str]],
    cutoff: datetime,
    history_cutoff: datetime | None = None,
    max_candidates: int | None = None,
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for connection in connections:
        title_score, relevance_reason = relevance(connection)
        if not title_score:
            continue
        activity = activities.get(normalise_url(connection.url), [])
        if history_cutoff is not None:
            activity = [item for item in activity if item.timestamp >= history_cutoff]
        latest = activity[-1] if activity else None
        # A recent LinkedIn exchange is already active, not orphaned.
        if latest and latest.timestamp >= cutoff:
            continue
        match_confidence, matched = me_match(connection, me_rows)
        if match_confidence == "exact" and activity_within_90_days(matched, cutoff):
            continue
        context = "No meaningful one-to-one LinkedIn exchange found."
        if latest:
            context = f"Last LinkedIn message was {latest.direction}: {latest.content[:240]}"
        if match_confidence == "unverified":
            candidate_type, action, me_state = "manual verification", "Verify in me.sh before any create or action", "me.sh not supplied"
        elif match_confidence == "ambiguous":
            candidate_type, action, me_state = "manual match", "Resolve me.sh identity match", "ambiguous match"
        elif match_confidence == "review":
            candidate_type, action, me_state = "manual match", "Confirm the name-and-company me.sh match", "possible name/company match"
        elif match_confidence == "exact":
            candidate_type, action, me_state = "reactivate", "Agree whether to re-engage and record the next action", "matched but dormant"
        else:
            candidate_type, action, me_state = "create and contact", "Create in me.sh and agree an initial outreach action", "no match found"
        latest_date = latest.timestamp.date().isoformat() if latest else ""
        me_date = (matched or {}).get("last_activity_at", "")
        evidence = f"LinkedIn profile: {connection.url or 'not supplied'}"
        if latest_date:
            evidence += f"; last direct LinkedIn message: {latest_date}"
        if me_date:
            evidence += f"; me.sh last activity: {me_date}"
        proposed = f"{connection.name} is a relevant LinkedIn contact at {connection.company or 'an unknown company'}. {context}"
        directions = {item.direction for item in activity}
        relationship_score = 3 if directions == {"inbound", "outbound"} else 1 if activity else 0
        priority_score = title_score * 10 + relationship_score * 3 + (1 if connection.email else 0)
        candidates.append({
            "decision": "review", "candidate_type": candidate_type, "priority_score": str(priority_score), "match_confidence": match_confidence,
            "full_name": connection.name, "company": connection.company, "position": connection.position,
            "linkedin_url": connection.url, "email": connection.email, "last_linkedin_activity": latest_date,
            "linkedin_context": context, "me_sh_state": me_state, "me_sh_last_activity": me_date,
            "relevance_reason": relevance_reason, "proposed_context": proposed,
            "recommended_action": action, "evidence": evidence,
        })
    candidates.sort(
        key=lambda row: (
            -int(row["priority_score"]),
            row["last_linkedin_activity"] == "",
            row["last_linkedin_activity"] or "9999",
            normalise(row["full_name"]),
        )
    )
    return candidates[:max_candidates] if max_candidates is not None else candidates


def markdown_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value).replace("|", "\\|")


def write_outputs(
    output_dir: Path,
    candidates: list[dict[str, str]],
    source_names: tuple[str, str],
    skipped: int,
    eligible_total: int | None = None,
) -> tuple[Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    csv_path = output_dir / f"orphan-prospect-review-{stamp}.csv"
    markdown_path = output_dir / f"orphan-prospect-review-{stamp}.md"
    with csv_path.open("x", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=DECISION_COLUMNS)
        writer.writeheader()
        writer.writerows(candidates)
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for candidate in candidates:
        groups[candidate["candidate_type"]].append(candidate)
    eligible_total = len(candidates) if eligible_total is None else eligible_total
    lines = [
        "# LinkedIn orphan-prospect review", "",
        f"Inputs: `{source_names[0]}`, `{source_names[1]}`.",
        f"Skipped {skipped} group, system, or empty message rows.", "",
        f"Candidates included: **{len(candidates)}** of **{eligible_total}** locally eligible contacts.", "",
    ]
    for group, rows in sorted(groups.items()):
        lines.extend([f"## {group.title()}", "", "| Person | Company | Last LinkedIn activity | me.sh state | Proposed action |", "| --- | --- | --- | --- | --- |"])
        for row in rows:
            cells = [row["full_name"], row["company"], row["last_linkedin_activity"] or "—", row["me_sh_state"], row["recommended_action"]]
            lines.append("| " + " | ".join(markdown_cell(cell) for cell in cells) + " |")
        lines.append("")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connections-file", type=Path, required=True)
    parser.add_argument("--messages-file", type=Path, required=True)
    parser.add_argument("--self-profile-url", required=True, help="Your LinkedIn profile URL, used to identify message direction.")
    parser.add_argument("--me-sh-snapshot", type=Path, help="Optional read-only export with email, linkedin_url, full_name, company, last_activity_at.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--inactivity-days", type=int, default=90)
    parser.add_argument("--history-days", type=int, default=730, help="LinkedIn message history used for context (default: 730 days).")
    parser.add_argument("--max-candidates", type=int, default=75, help="Maximum pre-filter candidates sent to live enrichment/matching.")
    args = parser.parse_args()
    if args.inactivity_days <= 0 or args.history_days <= 0 or args.max_candidates <= 0:
        parser.error("--inactivity-days, --history-days, and --max-candidates must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    connection_rows = csv_rows(args.connections_file, CONNECTION_HEADERS)
    message_rows = csv_rows(args.messages_file, MESSAGE_HEADERS)
    connections = [Connection(row["First Name"].strip(), row["Last Name"].strip(), row["URL"].strip(), row["Email Address"].strip(), row["Company"].strip(), row["Position"].strip()) for row in connection_rows]
    activities, skipped = message_activity(message_rows, args.self_profile_url)
    cutoff = datetime.combine(args.as_of - timedelta(days=args.inactivity_days), datetime.min.time(), tzinfo=timezone.utc)
    history_cutoff = datetime.combine(args.as_of - timedelta(days=args.history_days), datetime.min.time(), tzinfo=timezone.utc)
    all_candidates = build_candidates(
        connections, activities, load_me_snapshot(args.me_sh_snapshot), cutoff,
        history_cutoff=history_cutoff,
    )
    candidates = all_candidates[:args.max_candidates]
    csv_path, markdown_path = write_outputs(
        args.output_dir, candidates, (args.connections_file.name, args.messages_file.name), skipped,
        eligible_total=len(all_candidates),
    )
    print(f"Wrote {len(candidates)} of {len(all_candidates)} locally eligible candidates to {csv_path}")
    print(f"Wrote summary to {markdown_path}")
    if not args.me_sh_snapshot:
        print("WARNING: no me.sh snapshot was supplied; every candidate requires me.sh verification before a create/update.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
