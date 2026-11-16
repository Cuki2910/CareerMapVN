# Fifteen-minute live crawler review

- Started: 2026-11-14 20:21:46 +07:00.
- Finished: 2026-11-14 20:36:46 +07:00.
- Measured duration: 900.006 seconds.
- Discovery: one live TopCV Data Analyst search page, then 15 distinct job URLs.
- Pace: approximately one job per minute; one extraction attempt per job.
- Gemini model: gemini-3.5-flash-lite, using the configured real key.
- Live results: 15 successes, zero failures; median job latency 10.476 seconds.
- Original run input tokens: 1,072,417. No billing/free-tier guarantee is inferred.

## Findings and fixes

1. English TopCV headings `Candidate Requirements` and `Work Schedule` were
   unrecognized, silently discarding requirements and work hours for record 6.
   Added the observed headings and a regression check.
2. AI output shortened the main title and degree/major/certificate details.
   TopCV titles now come from the main heading. Explicit source qualification
   lines, separate major lists, and decomposed Vietnamese accents are preserved.
3. `13 - 25 trieu VND` (accented in the source) had no derived salary values.
   Added that currency spelling: minimum 13, maximum 25, midpoint 19 million VND.
4. Full navigation and footer content inflated requests to about 71,000 input
   tokens per job. TopCV requests now retain the main job and company/general
   information, excluding navigation and unrelated footer links.

## Verification and artifacts

- `jobs.json`, numbered source markdown, and numbered model response JSON files
  preserve the ORIGINAL run, which used the code loaded before the fixes.
- `audit.json` reviews original output against the updated checks. Ten records
  contain a detected omission or normalization issue. One original salary record
  fails the NEW salary consistency rule because its formerly-null derived values
  are now computable; this is not a failed HTTP/API call during the run.
- `jobs.corrected.json` is all 15 original model responses re-normalized against
  their saved real source pages with the final code. No new model call is made
  for this replay, and original evidence remains untouched.
- `audit.corrected.json`: 15/15 validate against the current 25-field schema;
  all recognized source sections are retained; no flagged issue under these
  specific checks. This is NOT proof of 100% semantic accuracy.
- `recheck/` contains TWO additional live browser + real Gemini verifications
  after the initial fixes. Both succeed. Their combined input tokens drop from
  143,900 to 11,316 (92.14%). These are not another fifteen-minute run. Their
  output also receives final deterministic normalization.
- Focused stdlib unittest suite: 22 tests pass. Shell syntax and git diff
  whitespace checks pass. Regression tests remain in crawling/test_llm_extract.py.

## Limits

The sample covers only 15 TopCV jobs, not all sites, categories or heading styles.
Metadata such as skills and experience still depends partly on model extraction.
Dataset category stays null without a known operator-provided taxonomy label;
unknown dates and ambiguous/negotiable salaries remain null rather than invented.
Source equality checks use the same section parser, with manual source review
and explicit regression cases supplementing them; they are not an independent
human-labelled benchmark. A complete semantic-accuracy claim needs such a set.
