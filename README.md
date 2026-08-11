# LinkedIn Mesh Contact Priority

A read-only discovery workflow that turns LinkedIn data exports into a bounded, reviewable queue of potentially orphaned senior contacts. It can use Apollo for role validation and the OAuth-enabled me.sh MCP for exact contact and recency checks. It never creates contacts or sends outreach during discovery.

Drop one LinkedIn Connections export and one LinkedIn Messages export in this folder for each review run. The supplied exports establish the expected schema.

For the normal workflow, start a new Codex chat and attach or reference this folder, then use [RUN_WITH_CODEX.md](RUN_WITH_CODEX.md). That workflow uses the live, OAuth-authorized me.sh MCP to check exact LinkedIn-profile matches and exclude contacts with interaction inside the last 90 days.

Run the processor with explicit file paths so historical exports are never selected by accident:

```sh
python3 linkedin_orphan_discovery.py \
  --connections-file "LinkedIn Orphan Discovery/YYYY-MM LinkedIn Connections.csv" \
  --messages-file "LinkedIn Orphan Discovery/YYYY-MM LinkedIn messages.csv" \
  --self-profile-url "https://www.linkedin.com/in/your-profile" \
  --output-dir "LinkedIn Orphan Discovery" \
  --inactivity-days 90 \
  --history-days 730 \
  --max-candidates 75
```

The processor excludes contacts with a meaningful LinkedIn message inside the inactivity window, ranks the remainder by title and relationship evidence, and caps the live-enrichment queue. Each output filename has a UTC run timestamp, so rerunning it does not overwrite an earlier review.

The Python processor is intentionally a local, read-only pre-filter. Its optional `--me-sh-snapshot` mode remains useful as an offline fallback, but Codex should perform Apollo validation and live me.sh lookups before you review or apply any result.

Do not place a generated review CSV back into LinkedIn as if it were a source export. Review its `decision` column (`approve`, `reject`, or `edit`) before Codex applies any me.sh changes. Files with the older date-only naming scheme were generated before run-safe timestamping and should not be used for a new review.

## Privacy

LinkedIn exports, me.sh snapshots, and generated prospect reports can contain personal data. The repository `.gitignore` excludes CSV files and generated review reports. Keep real exports outside version control and inspect staged files before every push.
