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

- **Frontend**: Single-page NiceGUI application (`lab/phoebe_ui.py`) served on port 8082
- **Backend**: Connects to `phoebe-server` via REST API using `phoebe-client` SDK at http://localhost:8001
- **Session Management**: Persists student sessions in browser storage with automatic reconnection (~30min timeout)
- **Authentication**: Simple student identification (first name, last name, email)
- **State Model**: 
  - Parameter widgets mirror PHOEBE parameters using fully-qualified twigs (e.g., `mass@primary@component`)
  - Dataset class manages observational/model arrays and table state
  - Automatic sync between UI widgets and backend bundle

## Installation

### Prerequisites

- Python 3.12 or later
- Running instance of `phoebe-server` (see [phoebe-server](https://github.com/aprsa/phoebe-server))

### Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/aprsa/phoebe-lab.git
   cd phoebe-lab
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv ~/.venvs/phoebe-lab
   source ~/.venvs/phoebe-lab/bin/activate  # On Windows: ~/.venvs/phoebe-lab/Scripts/activate
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

3. **Student Login**: Enter your first name, last name, and email to begin

4. **Session Management**: Your session persists for ~30 minutes. If you refresh the page, you can continue your existing session or start a new one.

## Project Structure

```
phoebe-lab/
├── lab/
│   ├── __init__.py
│   ├── phoebe_ui.py      # Main UI application (PhoebeUI, Dataset, parameter widgets)
│   ├── login.py          # Login and session dialogs
│   ├── user.py           # User model
│   └── utils.py          # Astronomy utilities (phase conversion, aliasing, flux/mag)
├── examples/             # Example data files for upload dialog (empty by default)
├── pyproject.toml        # Package metadata and dependencies
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
- **Widget Architecture**: Two widget classes:
  - `PhoebeParameterWidget`: Base class for simple parameters (number, select, checkbox)
  - `PhoebeAdjustableParameterWidget`: Extends base with "Adjust" checkbox and step size for fitting
- Fully-qualified PHOEBE parameter addressing via twigs (e.g., `requiv@primary@star@component`)
- Automatic constraint detection and UI state management (disabled when constrained)
- Value validation with limit checking before submission to server
- Bulk parameter sync from backend bundle using tag-based matching

### Dataset Management
- **Encapsulated Dataset Class**: Manages data model, UI table, and backend synchronization
- Add/edit/remove light curve and RV datasets via dialog
- Upload observational data from text files or create synthetic datasets
- Configure model computation phases (min, max, number of points) per dataset
- Toggle visibility of data and model curves in plots via AG Grid checkboxes
- Automatic phase calculation and aliasing for plotting

### Model Computation
- Configurable computation backend (PHOEBE, PHOEBAI)
- Per-component settings:
  - Model atmosphere (blackbody, ck2004, etc.)
  - Surface discretization (ntriangles)
  - Distortion method
- System-wide settings:
  - Irradiation method
  - Dynamics method
  - Boosting method
  - Light travel time effects (LTTE)

### Model Fitting
- Differential corrections solver with configurable derivative method
- Select adjustable parameters with custom step sizes via checkboxes
- Asynchronous solver execution (non-blocking UI)
- View fit results with:
  - Initial vs. fitted values
  - Percent change analysis
- Adopt fitted values back into parameters (clears model arrays)

### Visualization
- Interactive Plotly light curve plots with:
  - Switchable X-axis: time (BJD) or phase
  - Switchable Y-axis: flux or magnitude
  - Optional legend display
  - Phase aliasing for better visualization (extends range by 0.1)
- Automatic plot updates on ephemeris changes (T₀, period)
- Responsive plot resizing on splitter drag

### Session Persistence
- Sessions stored in NiceGUI browser storage (requires `storage_secret`)
- Automatic reconnection to existing sessions on page refresh
- UI state synced from backend bundle on reconnect
- Session cleanup when backend session expires

## Configuration

The backend URL is currently hardcoded to `http://localhost:8001` in `main_page()`. The storage secret for session persistence is set in the `ui.run()` call.

## Dependencies

### Core
- `nicegui>=1.4.0` - Web UI framework
- `phoebe-client>=0.1.0` - REST API client for phoebe-server
- `numpy>=1.26.0` - Numerical arrays
- `plotly>=5.18.0` - Interactive plotting

### Development
- `pytest` - Testing framework
- `black` - Code formatting
- `ruff` - Fast Python linter
- `mypy` - Static type checking

## House Patterns and Conventions

- **Twig Addressing**: Use fully-qualified twigs everywhere (as widget keys, in API calls, in solver lists)
- **UI-Only Parameters**: Attached at startup as `backend@ui`, `morphology@ui`, and dataset defaults like `phase_min@_default@ui`
- **AG Grid Events**: 
  - `rowSelected` for table row selection
  - `cellDoubleClicked` for editing (skips checkbox columns)
  - `cellValueChanged` for mirroring checkbox state changes
- **Long-Running Operations**: Execute with `get_event_loop().run_in_executor()` and show button loading indicators
- **Plot Responsiveness**: Call `Plotly.Plots.resize()` via `ui.run_javascript()` after splitter changes

## Known Limitations

- Backend URL is hardcoded (no configuration file support yet)
- RV curve plotting not yet implemented (only light curves)
- Morphology changes require manual dataset re-adding
- No undo/redo functionality
- Example data files must be added manually to `examples/` directory

## License

GNU Affero General Public License v3.0 (AGPL-3.0)

## Author

**Andrej Prša** (aprsa@villanova.edu)

## Links

- **Repository**: https://github.com/aprsa/phoebe-lab
- **Issues**: https://github.com/aprsa/phoebe-lab/issues
- **phoebe-server**: https://github.com/aprsa/phoebe-server
- **phoebe-client**: https://github.com/aprsa/phoebe-client
