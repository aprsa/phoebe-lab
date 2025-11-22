# PHOEBE Lab

A NiceGUI-based web UI for PHOEBE Lab to inspect and fit eclipsing-binary models against light and radial velocity curves.

## Overview

PHOEBE Lab provides an interactive web interface for students and researchers to:
- Configure binary star system parameters (masses, radii, temperatures, orbital elements)
- Load observational data (light curves, RV curves)
- Compute synthetic models using PHOEBE
- Fit models to observations using differential corrections
- Visualize results with interactive Plotly charts

## Architecture

- **Frontend**: Single-page NiceGUI application (`lab/phoebe_ui.py`)
- **Backend**: Connects to `phoebe-server` via `phoebe-client` SDK at http://localhost:8001
- **Session Management**: Persists student sessions with automatic reconnection
- **Authentication**: Simple student identification (first name, last name, email)

## Installation

### Prerequisites

- Python 3.12 or later
- Running instance of `phoebe-server` (see [phoebe.server](https://github.com/aprsa/phoebe.server))

### Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/aprsa/phoebe.lab.git
   cd phoebe.lab
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv ~/.venvs/phoebe.lab
   source ~/.venvs/phoebe.lab/bin/activate  # On Windows: ~/.venvs/phoebe.lab/Scripts/activate
   ```

3. **Install the package**:
   ```bash
   pip install .
   ```

   For development with additional tools (pytest, black, ruff, mypy):
   ```bash
   pip install -e ".[dev]"
   ```

## Usage

### Starting the Lab

Run the application:
```bash
phoebe-lab
```

Or directly with Python:
```bash
python -m lab.phoebe_ui
```

The UI will be available at: **http://localhost:8082**

### First Time Setup

1. **Start phoebe-server** (if not already running):
   ```bash
   # In a separate terminal
   phoebe-server
   ```
   Server should be accessible at http://localhost:8001

2. **Open PHOEBE Lab** in your browser:
   ```
   http://localhost:8082
   ```

3. **Student Login**: Enter your first name, last name, and optional email to begin

4. **Session Management**: Your session persists for ~30 minutes. If you refresh the page, you can continue your existing session or start a new one.

## Project Structure

```
phoebe.lab/
├── lab/
│   ├── __init__.py
│   ├── phoebe_ui.py      # Main UI application
│   ├── login.py          # Login and session dialogs
│   ├── user.py           # User model
│   └── utils.py          # Astronomy utilities (phase conversion, etc.)
├── examples/             # Example data files (empty by default)
├── pyproject.toml        # Package metadata and dependencies
├── requirements.txt      # Pip requirements
└── README.md            # This file
```

## Development

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
black lab/
```

### Linting

```bash
ruff check lab/
```

### Type Checking

```bash
mypy lab/
```

## Key Features

### Parameter Management
- Fully-qualified PHOEBE parameter addressing (twigs like `mass@primary@component`)
- Automatic constraint detection and UI state management
- Adjustable parameters for model fitting with step sizes

### Dataset Management
- Add/edit/remove light curve and RV datasets
- Upload observational data or create synthetic datasets
- Toggle visibility of data and model curves in plots
- Automatic phase calculation and aliasing

### Model Computation
- Configurable computation backend (PHOEBE, PHOEBAI)
- Model atmosphere selection (blackbody, ck2004, etc.)
- Surface discretization control
- Irradiation, dynamics, and boosting methods

### Model Fitting
- Differential corrections solver
- Select adjustable parameters with custom step sizes
- View fit results with percent change analysis
- Adopt fitted values back into parameters

### Visualization
- Interactive Plotly light curve plots
- Switch between time/phase on X-axis
- Switch between flux/magnitude on Y-axis
- Phase aliasing for better visualization

## Configuration

Currently, the backend URL is hardcoded to `http://localhost:8001`. Future versions will support configuration via `config.toml`.

## License

GNU Affero General Public License v3.0 (AGPL-3.0)

## Author

**Andrej Prša** (aprsa@villanova.edu)

## Links

- **Repository**: https://github.com/aprsa/phoebe.lab
- **Issues**: https://github.com/aprsa/phoebe.lab/issues
- **phoebe-server**: https://github.com/aprsa/phoebe.server
- **phoebe-client**: https://github.com/aprsa/phoebe.client
