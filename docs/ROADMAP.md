# Work in progress

## Current public foundation

- Training-free Jev orchestration and a five-unit checked pipeline.
- Existing OpenAI-family reasoning models, with an explicit high-effort checker.
- One-use approvals, source/artifact identities, immutable run policy, and a post-checker Jev decision.
- A structured-record reference task, offline tests, and usage/journal auditing.

## Next practical work

1. Generalize task adapters beyond the structured-record example.
2. Implement source-span retrieval and focused evidence packets for large corpora, preserving recall of omitted material.
3. Separate verified facts, missing evidence, and uncertainty so correct answers are not withheld by arbitrary score floors.
4. Add direct provider/API or connector implementations behind the same contracts, with explicit capability tests.
5. Evaluate OpenAI model/effort routes on representative tasks using measured results, without training a model.
6. Run a new paired efficiency study on multi-step projects, counting every gate and reviewer.
7. Add resumable runs and concurrency only after approval/commit invariants remain valid under parallel execution.

The project does not currently train on data, optimize neural weights, implement a learned Transformer, or promise foolproof results. Layered-network and Transformer concepts guide modular data flow and selective context handling.
