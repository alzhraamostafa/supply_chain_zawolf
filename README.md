# Demand Forecasting Component

A demand forecasting component developed as part of an AI-powered Industrial Supply Chain & Procurement Platform for a cosmetics factory.

The component analyzes historical demand data and generates forecasts at different aggregation levels, helping support inventory planning and demand analysis.

## Project Scope

The forecasting component covers:

- Weekly demand forecasting at **Family** and **Brand** levels.
- Weekly demand forecasting at **SKU** level.
- Monthly SKU demand forecasting.
- Intermittent demand analysis.
- Rolling-origin backtesting and model evaluation.
- Family-to-SKU forecast allocation using historical demand shares.
- Prediction intervals based on historical forecast errors.

## Dataset

The component uses historical commercial demand data from the project database.

| Attribute | Description |
|---|---|
| Historical period | January–June 2026 |
| Records | 4,287 |
| SKUs | 63 |
| Product families | 15 |
| Brands | 9 |
| Main source table | `fact_commercial_demand_m5` |
| Product information | `dim_products` |

The database is expected at:

```text
data/logistic_in_cosmatic.db
```

**Note:** The database is excluded from Git through `.gitignore`. Obtain the required database file from the project team and place it in the `data/` directory before running the pipeline.

## Forecasting Models

### Baseline Models

- Naive Forecast
- Moving Average (MA4 and MA8)
- Croston
- Syntetos–Boylan Approximation (SBA)
- Teunter–Syntetos–Babai (TSB)

### Machine Learning Models

- Ridge Regression
- Histogram-based Gradient Boosting Regressor

### Forecasting Strategy

- Weekly Family and Brand forecasts are evaluated using rolling-origin backtesting.
- SKU-level forecasting combines direct SKU forecasting methods with family-level forecasts allocated according to recent historical SKU demand shares.
- SKU model selection uses a validation period to select a model for each SKU, followed by evaluation on a separate final test period.
- Monthly SKU forecasting is evaluated separately.

## Evaluation Metrics

| Metric | Purpose |
|---|---|
| WAPE | Measures weighted absolute forecasting error |
| Bias | Measures systematic over- or under-forecasting |
| Interval Coverage | Measures how often actual demand falls within prediction intervals |
| Mean Interval Width | Measures the average width of prediction intervals |

Lower WAPE is better. Bias close to zero indicates less systematic forecasting error.

## Backtesting Results

The following results were obtained from the implemented backtesting experiments.

### Weekly Family Forecasting

| Model | WAPE | Bias |
|---|---:|---:|
| Naive | 40.1% | -1.5% |
| MA4 | 26.1% | -3.5% |
| MA8 | 26.3% | -5.9% |
| Ridge | **16.0%** | -3.2% |
| Gradient Boosting | 17.5% | 0.4% |

### Weekly Brand Forecasting

| Model | WAPE | Bias |
|---|---:|---:|
| Naive | 31.2% | -1.5% |
| MA4 | 19.7% | -3.5% |
| MA8 | 20.0% | -5.9% |
| Ridge | **14.1%** | 3.3% |
| Gradient Boosting | 16.5% | 0.9% |

### Weekly SKU Forecasting — Final Test

The SKU model-selection experiment used five validation weeks and evaluated the selected models on the remaining six final test weeks.

| Model | WAPE | Bias |
|---|---:|---:|
| Family–GBM allocation | **69.97%** | 2.38% |
| Family–Ridge allocation | 70.14% | 2.25% |
| Per-SKU selected models | 70.27% | -2.21% |
| Croston | 77.79% | -7.68% |
| SBA | 77.88% | -12.30% |
| TSB | 80.35% | -7.87% |
| MA8 | 80.78% | -8.19% |
| MA4 | 89.83% | -1.79% |

### Monthly SKU Forecasting

| Model | WAPE | Bias |
|---|---:|---:|
| Naive | 27.8% | -0.9% |
| Expanding Mean | **22.1%** | -11.0% |

*Note: Results are based on the historical backtesting experiments documented for this component. The weekly family and brand results and the SKU final-test results represent different evaluation experiments and should not be interpreted as one directly comparable test.*

## Project Structure

```text
forecasting/
│
├── data/
│   └── logistic_in_cosmatic.db
│
├── outputs/
│
├── scripts/
│   └── run_backtest.py
│
├── src/
│   └── forecasting/
│       ├── __init__.py
│       ├── config.py
│       ├── data.py
│       ├── features.py
│       ├── baselines.py
│       ├── models.py
│       ├── intervals.py
│       ├── metrics.py
│       ├── backtest.py
│       └── reporting.py
│
├── tests/
│
├── .gitignore
├── requirements.txt
├── README.md
└── FORECASTING_GUIDE.md
```

## Setup and Execution

### 1. Clone the repository

```bash
git clone <repository-url>
cd <repository-folder>/forecasting
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add the database

Place the database file in:

```text
data/logistic_in_cosmatic.db
```

### 5. Run the backtesting pipeline

From the `forecasting/` directory:

```bash
python scripts/run_backtest.py data/logistic_in_cosmatic.db
```

The pipeline runs the forecasting experiments and saves the resulting CSV reports in the `outputs/` directory.

### 6. Run tests

```bash
pytest -q
```

## Generated Outputs

The pipeline generates reports including:

- `backtest_results.csv` — Main backtesting metrics.
- `experiments.csv` — Append-only experiment log.
- `sku_model_comparison.csv` — Per-SKU model comparisons.
- `sku_best_models.csv` — Best-performing models per SKU in the comparison experiment.
- `sku_validation_comparison.csv` — Validation-period model comparison.
- `sku_selected_models.csv` — Models selected using validation data.
- `sku_final_test_results.csv` — Final test results per SKU.
- `sku_final_overall_comparison.csv` — Overall final-test comparison.

Generated outputs are excluded from Git by the current `.gitignore` configuration.

## Current Limitations

- The available historical data covers only six months, limiting long-term seasonality analysis.
- Weekly SKU forecasting remains challenging because demand is intermittent for many SKUs.
- SKU allocation relies on recent historical demand shares, which may change over time.
- Prediction interval coverage is below the nominal 80% target, particularly at SKU level. Further calibration is required.
- The available backtesting windows are relatively short, so results should be interpreted with caution.
- Passing automated tests does not independently establish production forecasting accuracy.

## Documentation

For implementation details, module explanations, configuration, technical decisions, and additional handover notes, see:

[`FORECASTING_GUIDE.md`](FORECASTING_GUIDE.md)

## Testing Status

The current test suite contains **20 passing tests**.

The tests validate the implemented component's functionality using the available test cases. They should not be interpreted as a substitute for broader evaluation on additional historical factory data.