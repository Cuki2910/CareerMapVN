# Label validation: instructions for annotators

Two team members label the same 150 job ads **independently**. Their labels are
compared with each other and with the LLM's labels to measure label quality.

## Steps

1. Annotator 1 opens `annotator_1.csv` and annotator 2 opens `annotator_2.csv`. Both open
   fine in Excel, Google Sheets or Numbers.
2. Read `job_title`, `technical_skills`, `description` and `requirements_text`.
3. Fill the three columns `tier`, `role` and `domain` for **every row**. `note` is optional.
   Use only the exact values listed below (lowercase, with underscores).
4. **Do not** discuss rows with the other annotator and **do not** look at the LLM labels
   until both files are done.
5. Save the file as CSV, keeping the same name, columns and UTF-8 encoding, and commit it.
6. When both files are done, run `make validation-report`. The result is written to
   `report.md` in this folder.

## `tier`

| Value | Use when |
|---|---|
| `A` | The job **itself** is a data job (see roles below). |
| `B` | The main job is something else, but the ad names at least one **concrete data skill**: SQL (also for developers/testers), Python/R for data, Power BI/Tableau/Looker, Google Analytics, A/B testing, statistics/SPSS, advanced Excel (Pivot, VLOOKUP, Power Query, VBA), ML frameworks, ETL/data warehouse, or practical use of AI tools (ChatGPT, Midjourney, prompting, AI trainer). |
| `none` | No concrete data skill. Plain "tin học văn phòng"/basic Excel, "nhập liệu" (data entry), "data có sẵn" (sales leads), or vague "khả năng phân tích" do **not** count. |

## `role`

- If `tier = A`, use one of:
  `da_bi` (data/BI/reporting analyst), `ds_ml_ai` (data scientist, ML/AI engineer),
  `de` (data engineer), `ba` (business analyst / phân tích nghiệp vụ),
  `dba_governance` (DBA, data governance/quality, master data),
  `quant_risk` (risk/credit/quant modelling, actuarial, pricing analytics).
- If `tier = B`, use the **main occupation**:
  `software_it`, `marketing_digital`, `finance_accounting`, `operations_supply_chain`,
  `sales_business`, `hr_admin`, `research_education`, `engineering_manufacturing`,
  `ai_applied` (AI tool use is the core of the job), `other`.
- If `tier = none`, use `none`.

## `domain`

The industry of the **hiring company**, not the job function. For example, an accountant at
a bank is `banking_finance_insurance`. Use `unknown` if the ad does not say.

`banking_finance_insurance`, `ecommerce_retail_fmcg`, `tech_software_telecom`,
`manufacturing_industrial`, `logistics_transport`, `real_estate_construction`,
`healthcare_pharma`, `education`, `media_marketing_agency`, `consulting_outsourcing_services`,
`energy_agriculture`, `hospitality_tourism`, `public_sector`, `other`, `unknown`

## Tips

- If you are unsure between two values, pick the closer one and explain in `note`.
- Each file takes about 1.5–2 hours. You can split it over several sessions; just save often.
