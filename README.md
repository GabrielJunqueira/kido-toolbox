---
title: Kido Support Toolbox
emoji: 🛠️
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Kido Support Toolbox

A web-based toolbox for the Kido support team.

## Features
- **Mall Calibration**: Circular buffer creation and visitor analysis.
- **AOI Project Generator**: Create Tourism projects with country/region/municipality selection.
- **Event Polygon Optimizer**: Measures per-node attendance on a past event day and proposes an
  optimised analysis polygon, with a node-by-node justification and an audit CSV.

## Development

```bash
pip install -r backend/requirements.txt
cd backend && uvicorn main:app --reload --port 8000
```

Run the tests from the `backend` directory:

```bash
cd backend && python -m pytest tests -q
```

## Deployment
This Space is deployed using Docker. Authorization relies on user credentials (no collected data or keys stored).
