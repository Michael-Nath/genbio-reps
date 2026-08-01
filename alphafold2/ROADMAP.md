# AlphaFold2, zero to hero — the ladder

A from-scratch, build-the-mechanism-yourself path through the machinery of
AlphaFold2, in the same spirit as the rest of this repo: **one mechanism per
notebook, toy data first, you write the core.** By the end you will have
reimplemented a tiny end-to-end AlphaFold on toy proteins, then dissected the
real thing.

Assumes general deep-learning proficiency (attention, autograd, training loops)
but **not** prior AlphaFold knowledge — the early rungs start from "what is an
MSA and why does folding become a coevolution problem."

Legend: [x] done · [ ] planned

## Track A — The trunk (Evoformer): reasoning over an MSA
- [x] 01 Folding as a coevolution problem — MSAs, mutual-information contacts,
      the average-product correction, indirect (transitive) couplings, and the
      two objects AF2 carries everywhere: the **MSA representation** `[N,L,c]`
      and the **pair representation** `[L,L,c]`.
- [x] 02 Axial attention over the MSA — row attention **with a pair bias**, and
      column attention. Why attention is factorised over the two axes.
- [x] 03 The pair representation & triangle operations — outer-product-mean
      (MSA → pair), the **triangle multiplicative update**, and **triangle
      self-attention**. The geometric-consistency engine; the deep-learning
      answer to the indirect-coupling problem from rung 01.
- [x] 04 The Evoformer block + distogram head — assemble the trunk, decode a
      **distance histogram** from the pair representation, and verify on toy
      data that the trunk recovers contacts a plain MI baseline cannot.

## Track B — The structure module: from a pair graph to 3D
- [x] 05 Residue frames & the structure module — per-residue **SE(3) frames**
      (building on `0.1`/`1.6`), the "residue gas", and going between frames and
      atom coordinates.
- [x] 06 Invariant Point Attention (IPA) — attention on points expressed in each
      residue's local frame, provably invariant to global rotation/translation.
      The single hardest mechanism, in isolation.
- [x] 07 FAPE loss & backbone generation — iterative **frame updates**, building
      a backbone from frames, and the **Frame-Aligned Point Error** that makes
      the whole structure module trainable.

## Track C — Putting it together
- [x] 08 Recycling & confidence — feeding predictions back through the trunk,
      and the **pLDDT** / **PAE** heads: how AF2 knows what it knows.
- [x] 09 End-to-end toy AlphaFold — wire trunk + structure module + recycling
      into one model, train it with FAPE on toy structures, and fold a
      held-out toy protein.
- [x] 10 Capstone: dissect real AlphaFold2 — run ColabFold on a real sequence
      and map pLDDT / PAE / recycles back to every mechanism you built.
      (Needs Colab/GPU — the only notebook that does.)

## Notebook contract
Every notebook: **Concept → reps (`raise NotImplementedError`) → checkpoints
(`assert`) → toy payoff → reflection (what transfers to the real system) →
solutions appendix.** Everything through rung 09 runs on a laptop CPU.
