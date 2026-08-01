# alphafold2 — zero to hero

A from-scratch reconstruction of the machinery behind **AlphaFold2**, taught the
same way as the rest of this repo: isolate one mechanism per notebook, build it
on toy data where you can print every tensor, and write the core yourself
(`raise NotImplementedError` scaffolds with `assert` checkpoints; solutions at
the bottom of each notebook).

Start at `01` and go in order — see [`ROADMAP.md`](ROADMAP.md) for the full
ladder. The series builds toward a tiny **end-to-end toy AlphaFold** (rung 09)
and finishes by dissecting the **real** model with ColabFold (rung 10).

## What you need

- **Rungs 01–09:** a laptop CPU. `numpy`, `matplotlib`, and `torch` (added to the
  repo's `requirements.txt`). The early rungs are numpy-only; the network rungs
  use torch but train in seconds to a couple of minutes.
- **Rung 10 only:** a Colab GPU runtime (it runs real AlphaFold2 via ColabFold).

## Prerequisites

General deep-learning fluency — attention, autograd, a training loop — and
ideally the SE(3)-frame idea from `00_foundations/01_proteins_as_tensors.ipynb`
and `01_generative_cores/06_se3_frame_diffusion.ipynb`, which the structure
module (rungs 05–07) builds directly on. **No prior AlphaFold knowledge is
assumed.**

## Why from scratch

AlphaFold2 looks impenetrable as one 30-page supplement. It is not: it is a
stack of a dozen comprehensible mechanisms — axial attention, a triangle
consistency rule, an invariant attention over 3D points, a clever loss — each of
which is small enough to build and test on its own. Assemble them and the whole
thing demystifies.
