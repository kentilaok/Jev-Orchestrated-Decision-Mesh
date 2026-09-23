"""Generate the frozen, entirely fictional CIDM pilot dataset (stdlib only)."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random

VERSION = "cidm-synthetic-pilot-1.0"
SEED = 1729
OUTPUT_CONTRACT = {
    "shape": {"answers": "object keyed by every answer_fields entry", "evidence": "object mapping each answer field to a list of document IDs", "status": "complete or partial"},
    "rules": [
        "Return one JSON object only. Use the exact categorical encodings requested in the query.",
        "Return numbers as JSON numbers, never numeric strings. Return unavailable or unresolved answers as JSON null.",
        "Cite the document IDs necessary to support each answer, including null answers. Do not cite unrelated documents.",
        "Set status to partial if any requested answer is null; otherwise set it to complete.",
        "Use only the supplied fictional documents. No external facts are needed or permitted.",
    ],
}

SOURCE_CONTEXT = [
    "This entry belongs to the studio operations archive. Its scope is the named service and period; names that resemble other services do not merge their settings. The archive preserves separate entries for planning, released work, and completed jobs. Operators retain the recorded units when copying values into a summary. Any change to a setting is recorded in a separate signed entry, and informal discussion does not amend the values printed here.",
    "The operations team stores this record as a separate source unit so that its scope remains visible when an excerpt is reused. A project label identifies the object being described, while a run label identifies one execution. Similar labels are not aliases. The filing process records successful handoff of the document but does not imply approval of a different project. Values in this entry apply only within its stated scope and should retain their original units.",
    "Archive handling follows the ordinary internal process: a clerk checks the title, a reviewer checks the scope, and the record is then made available to the service desk. This handling note supplies no additional configuration values. Cross references must be followed by their exact identifier rather than by resemblance of names. A source copied into another folder retains the scope written in its body. The original entry remains available for verification of any operational summary.",
    "The document is part of a fictional internal exercise for an ordinary creative production service. Its terms describe local workflow choices rather than external standards. The team keeps separate records for different locations and periods because a rule from one location need not apply at another. A summary should keep the named scope attached to each value. Supporting attachments are independent records; this filing note does not silently import values from a similarly titled attachment.",
]


class Builder:
    def __init__(self):
        self.rng = random.Random(SEED)
        self.used = set()
        self.tasks = []
        self.gold = {}
        self.context_index = 0

    def code(self, prefix):
        while True:
            value = f"{prefix}{self.rng.randrange(0x1000, 0xffff):04X}"
            if value not in self.used:
                self.used.add(value)
                return value

    def doc(self, text, long=False):
        if long:
            text += " " + SOURCE_CONTEXT[self.context_index % len(SOURCE_CONTEXT)]
            self.context_index += 1
            while len(text.split()) < 100:
                text += " The entry remains scoped to the named object and stated reporting period."
            assert 100 <= len(text.split()) <= 200, (len(text.split()), text)
        return {"id": self.code("D"), "text": text}

    def noise(self, count, subject):
        documents = []
        for index in range(count):
            project = self.code("P")
            run = self.code("R")
            mode = ["amber", "cobalt", "slate", "teal"][index % 4]
            body = (
                f"{subject}: separate service {project}, execution {run}. This record covers the "
                f"south annex rehearsal workflow in period 2026-08. Its queue is {mode}, its retry "
                f"limit is {index % 5 + 1}, and its maximum image width is {960 + index * 32} pixels. "
                f"The run received {200 + index * 13} items and released {180 + index * 11} items. "
                "The export preset uses PNG with metadata retained. This service is independent "
                "of every other project identifier; the record does not amend their settings or reports."
            )
            documents.append(self.doc(body, long=True))
        return documents

    def add(self, task_id, split, stratum, query, documents, answers, supports, features=(), allowed_extra=None):
        """Each support value is a list of required document IDs or OR-groups."""
        evidence = {}
        for field, sources in supports.items():
            groups = [[source] if isinstance(source, str) else list(source) for source in sources]
            allowed = {s for group in groups for s in group}
            allowed.update((allowed_extra or {}).get(field, []))
            evidence[field] = {"groups": groups, "allowed": sorted(allowed)}
        self.rng.shuffle(documents)
        query += (
            " Return answers with exactly these fields: " + ", ".join(answers) + ". "
            "Use JSON numbers for numeric fields and JSON null for any unavailable or unresolved answer. "
            "For each field, cite the necessary document IDs in evidence. Set status to partial if "
            "any answer is null, otherwise complete. Return the prescribed JSON object only."
        )
        task = {"id": task_id, "split": split, "phase": split, "stratum": stratum, "query": query, "documents": documents, "answer_fields": list(answers)}
        self.tasks.append(task)
        self.gold[task_id] = {
            "id": task_id, "split": split, "stratum": stratum, "answers": answers,
            "evidence": evidence, "status": "partial" if any(v is None for v in answers.values()) else "complete",
            "features": list(features),
        }


def generate():
    b = Builder()

    # Development cases are disjoint from the twelve evaluation cases.
    p = b.code("P")
    d = b.doc(f"Released rehearsal configuration for service {p}: delivery mode is batch. The interval is 15 minutes. This record is the complete current schedule for this service.")
    other = b.doc(f"The separate service {b.code('P')} uses stream delivery with a 2 minute interval. Its schedule does not apply to other service identifiers.")
    b.add("DEV-01", "development", "short_direct", f"For service {p}, report mode as batch or stream, and interval_minutes in minutes.", [d, other], {"mode": "batch", "interval_minutes": 15}, {"mode": [d['id']], "interval_minutes": [d['id']]})

    p, plan = b.code("P"), b.code("L")
    a = b.doc(f"Current account register: service {p} uses plan {plan}. A storage add-on of 40 GB is active for this account. The account is a standard rehearsal workspace and has no other storage add-ons. Capacity is the plan allowance plus the active add-on.", True)
    c = b.doc(f"Released plan {plan} includes 35 GB of storage. Its storage class is warm. Plan capacity is expressed in GB and is added directly to account add-ons expressed in the same unit. The class applies to accounts using this exact plan identifier.", True)
    missing = b.doc(f"Expiry register for service {p}: expiry_days is unrecorded. This register and the supplied account and plan entries are the complete current records for this service. No default expiry is defined. An unrecorded expiry must be returned as unavailable rather than estimated.", True)
    b.add("DEV-02", "development", "cross_document", f"For service {p}, report storage_class using warm or cold, quota_gb as total GB, and expiry_days as the recorded expiry in days or null when unavailable.", [a, c, missing] + b.noise(13, "Workspace note"), {"storage_class": "warm", "quota_gb": 75, "expiry_days": None}, {"storage_class": [a['id'], c['id']], "quota_gb": [a['id'], c['id']], "expiry_days": [missing['id']]}, ["reference_join", "explicit_absence"])

    p = b.code("P")
    active = b.doc(f"Released export profile for service {p}. Encode the image as WebP, set maximum width to 1600 pixels, and preserve alpha. The profile is current and has no per-job override. In summaries encode its format as webp and alpha handling as preserve.")
    old = b.doc(f"Retired export profile for separate service {b.code('P')}. This historical profile used JPEG, 1200 pixels, and discarded alpha. It does not govern the current service.")
    b.add("E-S01", "evaluation", "short_direct", f"Read the current export profile for {p}. Return format in lowercase, max_width_px as pixels, and alpha as preserve or discard.", [active, old], {"format": "webp", "max_width_px": 1600, "alpha": "preserve"}, {k: [active['id']] for k in ['format', 'max_width_px', 'alpha']}, ["direct_lookup"])

    r = b.code("R")
    report = b.doc(f"Closed packing report for run {r}: packed_crates = 96, rejected_crates = 8, and released_crates = 88. These are disjoint quality outcomes within the packed count. The reporting unit for every count is crate. The report is final.")
    handoff = b.doc(f"Handoff register for run {r}: the packing report is the final count authority. A preliminary dispatch note counted 90 planned releases before quality checking. That planned count was not a released count.")
    b.add("E-S02", "evaluation", "short_direct", f"For final run {r}, return released_crates and rejected_crates as counts, and unit as the singular lowercase unit name.", [report, handoff], {"released_crates": 88, "rejected_crates": 8, "unit": "crate"}, {k: [report['id']] for k in ['released_crates', 'rejected_crates', 'unit']}, ["direct_lookup"], {k: [handoff['id']] for k in ['released_crates', 'rejected_crates', 'unit']})

    p = b.code("P")
    policy = b.doc("Released dispatch rule: orders with at least 20 items use bulk mode, a 6 hour collection window, and desk approval. Orders below 20 items use parcel mode, a 2 hour window, and automatic approval. Equality is included in the bulk condition.")
    order = b.doc(f"Order {p} contains exactly 20 items. It is governed by the released dispatch rule. There are no exceptions or priority flags on this order.")
    b.add("E-S03", "evaluation", "short_direct", f"Apply the dispatch rule to order {p}. Return mode as bulk or parcel, window_hours as hours, and approver as desk or automatic.", [policy, order], {"mode": "bulk", "window_hours": 6, "approver": "desk"}, {k: [policy['id'], order['id']] for k in ['mode', 'window_hours', 'approver']}, ["inclusive_boundary", "all_sources_needed"])

    release = b.code("V")
    components = [("renderer", "enabled"), ("indexer", "disabled"), ("notifier", "enabled"), ("archiver", "disabled")]
    docs = [b.doc(f"Final component record for release {release}: the {name} component is {state}. This signed component record is authoritative for that component. Its state is independent of the other components in the release.") for name, state in components]
    b.add("E-S04", "evaluation", "short_direct", f"Return each component state for release {release}, using exactly enabled or disabled.", docs, dict(components), {name: [doc['id']] for (name, _), doc in zip(components, docs)}, ["direct_lookup", "all_sources_needed"])

    p = b.code("P")
    target = b.doc(f"Released media preset for service {p}, period 2026-09, north studio. The output codec is AVIF, maximum width is 1440 pixels, metadata stripping is enabled, and the retry limit is 3 attempts. Encode metadata stripping as yes. These settings are final for the named service and period, and there are no overrides in this packet.", True)
    b.add("E-N01", "evaluation", "noisy_retrieval", f"Find the released 2026-09 media preset for service {p}. Return codec in lowercase, max_width_px, strip_metadata as yes or no, and retry_limit as a count.", [target] + b.noise(19, "Media preset ledger"), {"codec": "avif", "max_width_px": 1440, "strip_metadata": "yes", "retry_limit": 3}, {k: [target['id']] for k in ['codec', 'max_width_px', 'strip_metadata', 'retry_limit']}, ["selective_retrieval"])

    p, r = b.code("P"), b.code("R")
    target = b.doc(f"Final execution report for service {p}, run {r}, period 2026-09. Received items total 420, successful items total 392, and failed items total 28. The queue used for this run was cobalt. These are final observed counts, with no pending items, and replace the estimates used before execution. Counts from other runs are separate and must not be combined with this one.", True)
    b.add("E-N02", "evaluation", "noisy_retrieval", f"For service {p}, run {r}, report received, successful, and failed as final item counts, and queue as its lowercase name.", [target] + b.noise(19, "Execution report"), {"received": 420, "successful": 392, "failed": 28, "queue": "cobalt"}, {k: [target['id']] for k in ['received', 'successful', 'failed', 'queue']}, ["selective_retrieval"])

    p = b.code("P")
    index = b.doc(f"Revision registry for service {p}. The complete revision list is revision 2 released, revision 3 released, and revision 4 draft. The governing revision is the highest numbered released revision. A draft is never effective, even if its number is larger. No other revisions or special overrides exist for this service in the current period.", True)
    r2 = b.doc(f"Service {p}, revision 2, released: timeout is 30 seconds and queue is slate. This revision remains archived after later releases so that prior executions can be reproduced. It is selected only when the revision registry identifies it as the highest released revision for the requested period.", True)
    r3 = b.doc(f"Service {p}, revision 3, released: timeout is 45 seconds and queue is amber. These values govern when revision 3 is the highest released revision in the revision registry. The timeout is measured in whole seconds; the queue name is an exact configuration value, not a description of an interface color.", True)
    r4 = b.doc(f"Service {p}, revision 4, draft: proposed timeout is 12 seconds and proposed queue is teal. This draft has not been released. Its proposed settings are available for planning but are not effective configuration. The revision registry controls the choice between released and draft entries in this packet.", True)
    b.add("E-N03", "evaluation", "noisy_retrieval", f"Find the currently governing configuration for service {p}. Return selected_revision as its number, timeout_seconds, and queue as the exact lowercase name.", [index, r2, r3, r4] + b.noise(16, "Configuration ledger"), {"selected_revision": 3, "timeout_seconds": 45, "queue": "amber"}, {"selected_revision": [index['id']], "timeout_seconds": [index['id'], r3['id']], "queue": [index['id'], r3['id']]}, ["release_precedence", "draft_caveat"], {k: [r2['id'], r3['id'], r4['id']] for k in ['selected_revision', 'timeout_seconds', 'queue']})

    p = b.code("P")
    target = b.doc(f"Final packing card for exhibition project {p}. Destination is the north gallery and shipment class is display. Use 6 inserts per box, label mode monochrome, and seal code R2. The carton limit is 18 kilograms. This card includes all approved packing exceptions for this exact project, and none change the values printed here. Cards for the south annex rehearsal workflow apply to different projects.", True)
    b.add("E-N04", "evaluation", "noisy_retrieval", f"For the final packing card of project {p}, return inserts_per_box, label_mode as its lowercase code, seal_code with original case, and carton_limit_kg in kilograms.", [target] + b.noise(19, "Packing archive"), {"inserts_per_box": 6, "label_mode": "monochrome", "seal_code": "R2", "carton_limit_kg": 18}, {k: [target['id']] for k in ['inserts_per_box', 'label_mode', 'seal_code', 'carton_limit_kg']}, ["selective_retrieval"])

    p, plan = b.code("P"), b.code("L")
    assignment = b.doc(f"Account assignment for project {p}: plan {plan}, region north, job type preview. The surge flag is active. The requested capacity date is 2026-09-10. This entry is the complete current assignment for the project; it has no other quota adjustments or region aliases. Follow the named plan and region rules to calculate its effective capacity.", True)
    plan_doc = b.doc(f"Released capacity plan {plan} provides a base allocation of 10 workers. The base allocation is counted in workers, not execution slots. A qualifying surge rule can increase this allocation before the region limit is enforced. The plan record supplies no exemption from a region limit, and no account-level override is part of this plan.", True)
    cap = b.doc("Released north region limit: effective allocation must not exceed 12 workers. First compute the base allocation with any permitted surge increase, then apply this region limit. The limit remains active for preview jobs and for accounts with an active surge flag. A value above the limit is reduced to 12 workers before converting workers to slots.", True)
    surge = b.doc("Released temporary surge rule: a preview job with an active surge flag receives 4 extra workers if its requested capacity date is on or before 2026-09-12. All three conditions are required. Other jobs receive no extra workers. Encode allocation_mode as surge when the rule applies, even if a region limit subsequently reduces the allocation; otherwise encode it as base.", True)
    units = b.doc("Released execution unit dictionary: one worker provides exactly 3 execution slots. Convert only the final effective worker allocation after all increases and region limits have been applied. There are no fractional workers or additional slot allowances in this policy packet. The slot conversion does not change which allocation mode was selected by the surge rule.", True)
    base_support = [assignment['id'], plan_doc['id'], cap['id'], surge['id']]
    b.add("E-C01", "evaluation", "cross_document", f"Compute capacity for project {p} at its requested date. Return effective_workers, execution_slots, allocation_mode as surge or base, and cap_applied as yes if the region cap reduces the increased allocation or no otherwise.", [assignment, plan_doc, cap, surge, units] + b.noise(15, "Capacity archive"), {"effective_workers": 12, "execution_slots": 36, "allocation_mode": "surge", "cap_applied": "yes"}, {"effective_workers": base_support, "execution_slots": base_support + [units['id']], "allocation_mode": [assignment['id'], surge['id']], "cap_applied": base_support}, ["reference_join", "unit_conversion", "exception", "cap_caveat"])

    run = b.code("R")
    segs = [b.code("B") for _ in range(3)]
    manifest = b.doc(f"Final manifest for reporting run {run}: production segments are {segs[0]} and {segs[1]}; trial segment is {segs[2]}. These are the only segments in this run. Each segment has a separate final count record. Segment classifications in this manifest are authoritative; similar segment identifiers in other runs do not belong to this report.", True)
    policy = b.doc("Released summary rule: include production segments only and exclude trial segments. Add included inspected counts for the denominator and included defect counts for the numerator. rate_per_1000 equals total included defects divided by total included inspected items, multiplied by 1000. Set alert to warn when rate_per_1000 is greater than 40; otherwise set it to clear. Do not round intermediate values.", True)
    countdocs = [b.doc(f"Final count record for segment {s}, run {run}: inspected_items = {total}; defect_items = {bad}. Defect items are included within the inspected count, not additional items. This record is final and has no later adjustment. Use the reporting manifest to decide whether this segment belongs in a production-only summary; the count record itself does not change its segment classification.", True) for s, total, bad in zip(segs, [240, 160, 50], [12, 8, 10])]
    support = [manifest['id'], policy['id'], countdocs[0]['id'], countdocs[1]['id']]
    b.add("E-C02", "evaluation", "cross_document", f"Produce the production-only summary for run {run}. Return included_items and defects as counts, rate_per_1000 using the named rate unit, and alert as warn or clear.", [manifest, policy] + countdocs + b.noise(15, "Segment report archive"), {"included_items": 400, "defects": 20, "rate_per_1000": 50, "alert": "warn"}, {k: support for k in ['included_items', 'defects', 'rate_per_1000', 'alert']}, ["reference_join", "excluded_segment", "rate_denominator"], {k: [countdocs[2]['id']] for k in ['included_items', 'defects', 'rate_per_1000', 'alert']})

    p, version = b.code("P"), b.code("V")
    rule = b.doc(f"Resolution procedure for service {p}: the two signed endpoint sheets in release {version} have equal authority. Neither has timestamp or ordering priority, and no tie-break record exists. If their endpoint values disagree, report endpoint as null, conflict as unresolved, and action as hold. A separate retention policy is unaffected by an endpoint conflict. Do not select a value by its place in the packet.", True)
    sheet_a = b.doc(f"Signed endpoint sheet for service {p}, release {version}, authority level approved: endpoint = cedar. This sheet covers the current main endpoint. It has the same release scope and authority as the other signed endpoint sheet in this packet, and it contains no withdrawal or supersession statement. Cedar is an internal route code, not a network address.", True)
    sheet_b = b.doc(f"Signed endpoint sheet for service {p}, release {version}, authority level approved: endpoint = birch. This sheet covers the current main endpoint. It has the same release scope and authority as the other signed endpoint sheet in this packet, and it contains no withdrawal or supersession statement. Birch is an internal route code, not a network address.", True)
    retention = b.doc(f"Released retention policy for service {p}: retain rehearsal logs for 14 days. This retention value is complete and unambiguous for the current release. It is maintained independently from endpoint routing and remains in force while an endpoint disagreement is being resolved. No other document in this packet overrides this retention policy.", True)
    conflict_support = [rule['id'], sheet_a['id'], sheet_b['id']]
    b.add("E-C03", "evaluation", "cross_document", f"Resolve service {p} under its supplied procedure. Return endpoint as its lowercase code or null, conflict as unresolved or none, retention_days in days, and action as hold or proceed.", [rule, sheet_a, sheet_b, retention] + b.noise(16, "Endpoint archive"), {"endpoint": None, "conflict": "unresolved", "retention_days": 14, "action": "hold"}, {"endpoint": conflict_support, "conflict": conflict_support, "retention_days": [retention['id']], "action": conflict_support}, ["contradiction", "null_required", "equal_authority"], {"retention_days": [rule['id']]})

    quote = b.code("Q")
    skus = [b.code("S") for _ in range(6)]
    amounts = [8, 12, 16, 20, 24, 28]
    prices = [11, 13, 17, 19, 23, None]
    manifest = b.doc(f"Complete line manifest for quotation {quote}: the required SKU identifiers are {', '.join(skus)}. Each appears once. Every required quantity entry and current price entry is included in this packet. No unlisted SKU belongs in the quotation. The quantity records describe individual units; use the packaging dictionary to convert them before applying current pack prices.", True)
    qty_docs = [b.doc(f"Quantity record for quotation {quote}, SKU {sku}: requested quantity is {qty} individual units. This is the final quantity for this SKU and supersedes planning estimates. The entry does not state a price or package count. Use the packaging dictionary and the matching current price entry when calculating a cost. Quantities for all manifest lines are required for the total requested-unit count.", True) for sku, qty in zip(skus, amounts)]
    price_docs = []
    for sku, price in zip(skus, prices):
        if price is None:
            body = f"Current price register for quotation {quote}, SKU {sku}: the pack price is unavailable. The register contains no current numeric price for this SKU, and no fallback price is authorized. This is an explicit missing entry, not a zero-price offer. All current pricing records are included in this packet. The final quantity entry remains valid even though this price is missing."
        else:
            body = f"Current price register for quotation {quote}, SKU {sku}: the price is {price} credits per pack. This is the only current price for this SKU. It is a pack price rather than an individual-unit price. No tax, shipping, or SKU-specific adjustment applies. Use the packaging dictionary to translate the matching quantity into packs, and then apply the quotation adjustment rule to the combined known line costs."
        price_docs.append(b.doc(body, True))
    units = b.doc(f"Packaging dictionary for quotation {quote}: every listed SKU has exactly 4 individual units per pack. All requested quantities are whole multiples of a pack. For each priced line, divide its individual-unit quantity by 4 and multiply the resulting pack count by its current credits-per-pack price. Do not treat an individual unit as an entire pack.", True)
    adjustment = b.doc(f"Adjustment rule for quotation {quote}: subtract one fixed allowance of 17 credits from the sum of all currently priced line costs. Apply this allowance once to the known subtotal even when another required line lacks a price. The allowance does not supply a price for a missing line and does not make an incomplete full quotation complete. No other monetary adjustments apply.", True)
    closure = b.doc(f"Completion rule for quotation {quote}: known_subtotal_credits includes only manifest lines with a current numeric price, followed by the fixed allowance. full_total_credits must be null if any required manifest line lacks a current price. In that situation quote_state is incomplete and missing_sku is that line's exact SKU identifier. Count only numerically priced lines in priced_lines. For total_units, include all manifest quantities, including any line with a missing price.", True)
    known_support = [manifest['id'], units['id'], adjustment['id'], closure['id']] + [d['id'] for d in qty_docs[:5] + price_docs]
    complete_support = [manifest['id'], closure['id']] + [d['id'] for d in price_docs]
    b.add("E-C04", "evaluation", "cross_document", f"Assemble quotation {quote}. Return known_subtotal_credits after the allowance, full_total_credits or null, missing_sku as the exact missing-price SKU code, priced_lines as a count, total_units in individual units, and quote_state as complete or incomplete.", [manifest] + qty_docs + price_docs + [units, adjustment, closure], {"known_subtotal_credits": sum(q // 4 * p for q, p in zip(amounts, prices) if p is not None) - 17, "full_total_credits": None, "missing_sku": skus[-1], "priced_lines": 5, "total_units": sum(amounts), "quote_state": "incomplete"}, {"known_subtotal_credits": known_support, "full_total_credits": [manifest['id'], closure['id'], price_docs[-1]['id']], "missing_sku": complete_support, "priced_lines": complete_support, "total_units": [manifest['id'], closure['id']] + [d['id'] for d in qty_docs], "quote_state": [manifest['id'], closure['id'], price_docs[-1]['id']]}, ["all_sources_needed", "reference_join", "unit_conversion", "explicit_absence", "null_required"], {"known_subtotal_credits": [qty_docs[-1]['id']], "full_total_credits": [d['id'] for d in price_docs], "quote_state": [d['id'] for d in price_docs]})

    tasks = {"version": VERSION, "seed": SEED, "output_contract": OUTPUT_CONTRACT, "tasks": b.tasks}
    gold = {"version": VERSION, "seed": SEED, "tasks": b.gold}
    validate_dataset(tasks, gold)
    return tasks, gold


def validate_dataset(tasks, gold):
    cases = tasks['tasks']
    assert len(cases) == 14
    assert Counter(t['split'] for t in cases) == {'development': 2, 'evaluation': 12}
    assert Counter(t['stratum'] for t in cases if t['split'] == 'evaluation') == {'short_direct': 4, 'noisy_retrieval': 4, 'cross_document': 4}
    ids = [d['id'] for t in cases for d in t['documents']]
    assert len(ids) == len(set(ids))
    assert len({t['id'] for t in cases}) == len(cases)
    for task in cases:
        expected = gold['tasks'][task['id']]
        assert set(task['answer_fields']) == set(expected['answers']) == set(expected['evidence'])
        assert len(json.dumps({'output_contract': OUTPUT_CONTRACT, 'task': task}, ensure_ascii=True).encode('ascii')) < 25000
        doc_ids = {d['id'] for d in task['documents']}
        if task['stratum'] != 'short_direct':
            assert 16 <= len(task['documents']) <= 24
            assert all(100 <= len(d['text'].split()) <= 200 for d in task['documents'])
        for spec in expected['evidence'].values():
            assert spec['groups'] and all(spec['groups'])
            assert set(spec['allowed']) <= doc_ids
            assert {v for g in spec['groups'] for v in g} <= set(spec['allowed'])
        if 'all_sources_needed' in expected['features']:
            assert {v for spec in expected['evidence'].values() for group in spec['groups'] for v in group} == doc_ids


def serialized(data):
    return (json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + '\n').encode('ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    tasks, gold = generate()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    blobs = {'tasks.json': serialized(tasks), 'gold.json': serialized(gold)}
    for name, blob in blobs.items():
        (args.output_dir / name).write_bytes(blob)
    manifest = {
        'version': VERSION, 'seed': SEED,
        'sha256': {name: hashlib.sha256(blob).hexdigest() for name, blob in blobs.items()},
        'task_count': 14, 'evaluation_count': 12, 'development_count': 2,
        'request_sizes_ascii_bytes': {t['id']: len(json.dumps({'output_contract': OUTPUT_CONTRACT, 'task': t}, ensure_ascii=True).encode('ascii')) for t in tasks['tasks']},
        'source_counts': {t['id']: len(t['documents']) for t in tasks['tasks']},
        'notice': 'Synthetic pilot only; development cases are excluded from evaluation. Gold must never enter an evaluated model request. Hashes freeze this generated release.',
    }
    (args.output_dir / 'dataset_manifest.json').write_bytes(serialized(manifest))
    print(json.dumps({'output_dir': str(args.output_dir.resolve()), 'tasks': 14, 'maximum_request_bytes': max(manifest['request_sizes_ascii_bytes'].values()), 'sha256': manifest['sha256']}, indent=2))


if __name__ == '__main__':
    main()
