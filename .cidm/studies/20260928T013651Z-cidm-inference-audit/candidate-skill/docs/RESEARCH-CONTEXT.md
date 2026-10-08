# Research context and attribution

**Kenneth Vic A. Caber** is credited as the creator and main contributor of this CIDM project. This is attribution for the proposed combination, implementation, and skill, not an established first-invention claim for model routing, verification, or neural architectures. The following is a focused related-work list, not an exhaustive novelty review.

- [TypeSafe: Introducing System One Models & Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) describes unstructured state mapped to predefined typed decisions. CIDM uses that decision interface for routing. Provider performance claims do not establish CIDM's end-to-end performance, and valid output types do not prove a decision correct.
- [FrugalGPT](https://arxiv.org/abs/2305.05176) studies cost-aware combinations of language models. It is related to the goal of avoiding unnecessary expensive inference; its measured results do not transfer automatically to this project.
- [RouteLLM](https://arxiv.org/abs/2406.18665) studies learned model routing from preference data. CIDM's current runtime uses existing models and fixed policies without training a router.
- [Attention Is All You Need](https://arxiv.org/abs/1706.03762) introduces the Transformer. CIDM takes selective use of relevant context as conceptual inspiration; its five-stage software graph is not an implementation of Transformer attention or a trainable neural network.

The operational contribution explored here is Jev interposed before bounded work and after every completed unit output, with optional high-effort review returning to Jev and deterministic eligibility before committing context. Whether this combination improves quality at a given total token or cost budget remains an empirical question.
