# Blind grading audit

An independent agent examined the source documents, frozen gold values, and grading code for E-C02, E-C03, and E-C04 without seeing arm outputs or costs. It changed no files.

All expected values were confirmed:

- E-C02: 400 production items, 20 defects, 50 defects per 1,000, `warn`.
- E-C03: endpoint null, unresolved conflict, 14-day retention, `hold`.
- E-C04: known subtotal 345 credits; full total null; missing SKU S84F8; 5 priced lines; 108 units; `incomplete`.

The audit found over-restrictive citation requirements:

- E-C02 count fields require D2B80 even though the query, production manifest, and both production count records suffice. That source is needed for the rate convention and threshold, but not necessarily the raw counts.
- E-C04 total_units requires D712E although the manifest and six quantity records suffice. known_subtotal_credits also requires D712E although DA16A independently supplies the allowance rule.
- E-C04 full_total_credits and quote_state reject DA16A as outside the citation whitelist even though it corroborates that the allowance does not complete the quotation.

E-C03's requirements were judged defensible: both conflicting endpoint sheets plus the conflict procedure establish why the hold rule applies. E-C04's positive-price records are defensible support for proving a unique missing SKU and exact priced-line count.

The auditor confirmed the limitations with constructed examples, without inspecting predictions. Frozen primary grades were retained. Answer-value accuracy is separately reported; a strict citation failure must not be represented as a wrong factual answer. No post-run alternate rubric was used to improve the headline scores.
