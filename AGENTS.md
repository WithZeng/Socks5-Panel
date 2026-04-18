# Project Working Rules

This repository follows `karpathy-guidelines` style by default for all future edits.

## Core Rules

- Prefer simple, readable code over clever abstractions.
- Keep functions short and single-purpose.
- Use explicit names for variables, functions, and routes.
- Minimize hidden state and side effects.
- Add comments sparingly, only when they explain intent or a non-obvious tradeoff.
- Prefer straightforward data flow over deep indirection.
- Avoid premature generalization and over-engineering.
- Keep HTML, CSS, and backend code easy to trace during debugging.
- When fixing bugs, prefer the smallest correct change first.
- Preserve production behavior unless the change is intentional and documented.

## Backend

- Keep route handlers thin and move business logic into services.
- Validate inputs close to the boundary.
- Prefer deterministic transformations and easy-to-test functions.
- Use persistent storage intentionally and make timestamps explicit.

## Frontend

- Keep UI state understandable and local when possible.
- Favor clear information hierarchy and obvious user feedback.
- Use motion to support orientation and status, not decoration.
- Avoid fragile DOM coupling and overly complex client logic.

## Delivery

- Update README when setup, deployment, or operator workflow changes.
- Keep scripts idempotent where practical.
- Make operational defaults explicit in code and docs.
