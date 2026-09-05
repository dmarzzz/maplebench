# Cosmic patches

This directory contains small proposed patches against `NDBellisario/cosmic` required to create a policy-neutral benchmark control plane.

They are kept as patches rather than vendored server source so the MapleBench framework stays cleanly separated from the AGPL server implementation.

Current patch:

- `0001-expose-requested-attack-plan.patch` — exposes a package-private planner for one *requested* basic/skill attack, avoiding the upstream bot AI's automatic best-skill choice.

The patch is based on the current `master` shape observed while bootstrapping MapleBench and should be revalidated against a pinned upstream commit before application.
