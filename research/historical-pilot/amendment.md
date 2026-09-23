# Analysis accounting correction

The frozen `analyze.py` remains unchanged. `analyze_measured.py` is an explicitly amended analyzer, written after evaluation began in response to a protocol review. The author did not inspect evaluation results; the correction was checked using fabricated offline fixtures only.

The frozen analyzer incorrectly required every terminal run to have `status: complete` before admitting total-token and billed-cost comparisons. The harness also uses `partial` for a valid released answer whose expected value is unavailable and uses `failed` for a withheld candidate. Neither status makes fully recorded consumption unknown. Disqualifying those runs would conflate answer quality with metering completeness and contradict the protocol's inclusion of all attempts.

The corrected analyzer retains every scheduled task and all recorded calls in the paired totals. Terminal complete, partial, failed, and rejected outcomes receive no consumption exemption. Full token results require complete actual-call linkage and known total usage; full cost results additionally require recorded billing for every actual event. Unknown usage, including authentication failures without reported usage, remains unknown and prevents the relevant full-consumption claim. No task or failed attempt is excluded.

Released candidates require worker coverage and, for arm B, Jev coverage, including valid released partial answers. A metered early failure can terminate before later planned calls; calls never made are not treated as missing measurements. Zero-event terminal runs remain a documented coverage limitation in this pilot because the ledger alone does not establish whether a provider request occurred.

Quality grading is unchanged. Only released candidates receive served-answer credit; withheld or absent answers score zero. Correct raw candidates that were rejected are still reported separately. A literal null answer with the expected partial status and required evidence can pass both served and raw grading. A malformed release record affects quality without erasing otherwise measured consumption.

The task set, gold labels, prompts, routing/release thresholds, budgets, model settings, trial order, confidence methods, bootstrap seed and draw count are unchanged. No thresholds were tuned and no results were selected. Tables now label recorded-run coverage separately from complete/partial/failed outcome counts, preventing valid partial answers from being presented as missing runs.

Validation: four offline regression cases cover metered rejection, correctly graded null/partial answers, a fully metered early failure, and a failure with unknown usage. The original frozen analyzer and its original tests are preserved for audit.
