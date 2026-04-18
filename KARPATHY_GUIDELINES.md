# Karpathy Guidelines Applied Here

This project interprets `karpathy-guidelines` as a bias toward:

- clarity first
- small understandable pieces
- minimal abstraction
- fast debugging
- direct data flow
- practical comments
- boring, dependable code

## What That Means In Practice

- Do the obvious thing unless there is a strong reason not to.
- Keep layers shallow so a bug can be traced quickly.
- Prefer explicit configuration and explicit validation.
- Avoid building generic frameworks inside the app.
- Choose maintainability over novelty.

## Review Standard

Before merging new code, check:

- Can a teammate find the main logic quickly?
- Can an operator understand how to run and deploy it from README alone?
- Can the change be explained in a few sentences?
- Would debugging this in production be straightforward?
