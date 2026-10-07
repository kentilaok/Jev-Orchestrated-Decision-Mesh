# Arsenal Manifest and Skill Admission

CIDM Arsenal V1 separates **discoverability** from **execution authority**.

Any valid `SKILL.md` may be indexed so CIDM can discover relevant procedures before spending frontier tokens. A skill cannot qualify for Fast Path merely because its own files claim to be trusted.

## Files

An Arsenal-aware skill folder may contain:

```text
some-skill/
  SKILL.md
  ARSENAL.json
```

`SKILL.md` is the human/agent procedural document.

`ARSENAL.json` is machine-readable metadata for matching, scope, requested permissions, risk, validators, and predeclared operations.

The actual owner admission is stored separately in the local Arsenal database and is bound to the current hashes of both files.

## Searchable is not executable

The compiler treats an unmanifested `SKILL.md` conservatively:

- scope: `unscoped`
- risk: `high`
- frontier required: `true`
- validators: none
- operations: none
- admitted: false

It may still be found by lexical search or an exact trigger discovered from its `## Trigger` section.

A manifest does **not** grant trust by itself. Even a downloaded skill that writes:

```json
{
  "admission": {
    "status": "admitted",
    "owner_approved": true
  }
}
```

remains unadmitted until the operator performs the local admission command.

## Schema v1

Example:

```json
{
  "schema_version": 1,
  "id": "wordpress-public-protection",
  "type": "recovery-skill",
  "version": 1,
  "description": "Repair a previously verified anonymous-content visibility failure.",
  "project_scope": ["wordpress"],
  "triggers": {
    "bug_keys": ["wordpress.memberpress.logged_out_visibility"],
    "phrases": ["protected content is visible while signed out"],
    "keywords": ["memberpress", "anonymous access"]
  },
  "permissions": {
    "read_files": true,
    "write_files": false,
    "network": false
  },
  "risk": "low",
  "frontier_required": false,
  "validators": ["anonymous_browser_check"],
  "operations": ["inspect_content"],
  "admission": {
    "status": "candidate",
    "owner_approved": false
  },
  "source": {
    "kind": "owner-reviewed"
  }
}
```

Allowed skill types:

- `methodology-skill`
- `recovery-skill`
- `tool-skill`
- `project-skill`

Allowed risk values:

- `low`
- `medium`
- `high`
- `critical`

## Local registry

Default database:

```text
~/.jev/arsenal/arsenal.db
```

Scan a Hermes skill directory:

```bash
python scripts/arsenal_registry.py scan --skills-dir ~/.hermes/skills
```

List compiled skills:

```bash
python scripts/arsenal_registry.py list
```

Match a task locally:

```bash
python scripts/arsenal_registry.py match \
  --task "Protected WooCommerce product is visible while signed out" \
  --project-scope wordpress \
  --bug-key wordpress.memberpress.logged_out_visibility \
  --operation inspect_content
```

The result is either:

- `known_skill` — a local candidate matched strongly enough to load/use as context; or
- `escalate_to_jev` — the local layer did not resolve the route confidently.

A `known_skill` result does **not** imply Fast Path eligibility.

## Owner admission

After inspecting the skill, manifest, provenance, requested permissions, validators, and operation boundaries:

```bash
python scripts/arsenal_registry.py admit --skill-id wordpress-public-protection
```

The registry stores:

- skill ID
- exact `SKILL.md` hash
- exact normalized `ARSENAL.json` hash

This local database record is the authority for admission.

If either file changes and the skill directory is scanned again, the stored hashes no longer match and the skill becomes unadmitted automatically.

Explicit revocation:

```bash
python scripts/arsenal_registry.py revoke --skill-id wordpress-public-protection
```

## Fast Path eligibility

The current V1 registry only reports whether a skill is eligible. It does not yet execute the operation.

A matched skill is Fast Path eligible only when all of these are true:

1. current skill+manifest hashes have a matching local admission record;
2. `frontier_required` is false;
3. risk is `low`;
4. at least one deterministic validator is declared;
5. project scope matches, or the skill is explicitly global;
6. the caller supplies an operation;
7. that operation appears in the manifest's preapproved operations;
8. the local match reaches the configured threshold, unless an exact bug key matched.

Failure of any condition produces explicit reasons such as:

- `skill_not_admitted`
- `frontier_required`
- `risk_not_low`
- `deterministic_validators_required`
- `project_scope_required`
- `project_scope_mismatch`
- `operation_required`
- `operation_not_preapproved`
- `confidence_below_threshold`

The next execution milestone should bind these conditions to CIDM permits and actual validator receipts before any automatic commit is allowed.

## Experience Distiller integration

Verified CIDM recovery lessons can already become Hermes skills.

The distiller now also writes a sibling `ARSENAL.json`. Generated manifests are intentionally conservative:

- type: `recovery-skill`
- risk: `medium`
- frontier required: `true`
- validators: empty
- operations: empty
- admission: `candidate`
- owner approved: false

This means learned experience becomes locally searchable without granting itself execution authority.

The operator may later edit/review the manifest, add a real deterministic validator and bounded operation, rescan, and explicitly admit that exact version.

## V1 security rule

> A skill package can request capabilities. It cannot grant itself capabilities.

Public registries, generated skills, model-written manifests, and copied project skills therefore remain useful as discovery/context sources while CIDM keeps execution authority outside the skill package.
