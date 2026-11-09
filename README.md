# FORMA – Smart Supply Chain Decision Support System

## Project Overview

FORMA is a Smart Supply Chain Decision Support System designed to support manufacturing operations through inventory management, material requirements calculation, and production readiness analysis.

The project is being developed as a modular application with a Python backend and a RESTful API architecture.

## Technology Stack

- Python 3.11
- FastAPI
- SQLAlchemy
- Pydantic
- SQLite
- Pytest
- Conda

## Backend Architecture

The backend follows a modular structure separating application responsibilities:

- `api/` – REST API endpoints
- `core/` – Application configuration
- `db/` – Database connection and base configuration
- `models/` – SQLAlchemy database models
- `repositories/` – Database queries
- `schemas/` – Request and response validation
- `services/` – Business logic
- `tests/` – Automated tests

## Implemented Features

- Product catalog API with filtering, search, and pagination.
- Bill of Materials (BOM) calculations.
- Raw material and packaging requirements calculations.
- Inventory balance calculations based on inventory movements.
- Stock availability and shortage calculations.
- Manufacturing readiness assessment.
- Inventory balances API.

## Project Setup

### 1. Create and activate the Conda environment

```bash
conda create -n forma-backend python=3.11 -y
conda activate forma-backend
```

### 2. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the example configuration:

```powershell
Copy-Item .env.example .env
```

### 4. Configure the database

The SQLite database is intentionally excluded from this repository.

Place an authorized database copy at the configured path or update `DATABASE_PATH` in `.env`.

### 5. Run the API

From the `backend/` directory:

```bash
python -m uvicorn app.main:app --reload
```

### 6. Open API documentation

Visit:

http://127.0.0.1:8000/docs

## Running Tests

From the `backend/` directory:

```bash
python -m pytest -v
```

## Current Development Status

The initial backend modules have been implemented and tested.

Latest test result: **31 passed**.

The next development phase focuses on procurement workflows, supplier evaluation, and goods receipt integration with inventory movements.

## Security

- Environment secrets are excluded from Git.
- SQLite database files are excluded from Git.
- The original operational database must not be modified during development.
