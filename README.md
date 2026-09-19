# Quant Risk Finance

A personal Python project for quantitative finance experiments and risk metrics.

- `src/`: reusable Python code for market analysis, portfolios, and utilities.
- `notebooks/`: exploratory analysis and examples.
- `tests/`: checks for reusable calculations.
- `config/`: project configuration files.
- `data/`: local datasets, excluded from Git.
- `.venv/`: local Python environment, excluded from Git.

To set up a fresh clone with Python 3.13 or later, run from the repository root
(macOS/Linux). This installs the project and development tools from `pyproject.toml`:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
mkdir -p data
```

Place your datasets in `data/`; it stays local and is ignored by Git.

See [the instrument master](docs/instruments.md) for metadata lookup and updates
to `data/instruments.xlsx`.
