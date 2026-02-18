# Copilot Instructions for phoebe.lab

A NiceGUI web UI for PHOEBE Lab — inspect and fit eclipsing-binary models against light/RV curves.

## Architecture
- **Frontend**: Single-page NiceGUI app at `lab/phoebe_ui.py` (port 8082), Plotly charts, AG Grid tables
- **Backend**: REST API via `phoebe-client` SDK to phoebe-server at http://localhost:8001
- **State**: Parameter widgets mirror PHOEBE "twigs" (e.g., `mass@primary@component`); `Dataset` class manages observations + model arrays

## File Layout
```
lab/phoebe_ui.py   # Main UI: PhoebeUI, Dataset, PhoebeParameterWidget, PhoebeAdjustableParameterWidget, main()
lab/sessions.py    # SessionInfo dataclass, StartSessionDialog, SessionManagerDialog, AuthLoginDialog, AuthRegisterDialog, PasswordProtected, PhoebeDialog base class
lab/utils.py       # Astronomy helpers: time_to_phase(), alias_data(), flux_to_magnitude()
examples/          # Sample data files for upload dialog
data/              # Bundle files and observation CSVs
static/styles.css  # Custom CSS for dialogs
```

## Developer Workflow
```bash
pip install -e ".[dev]"           # Install with dev tools (pytest, black, ruff, mypy)
phoebe-lab                        # Start UI at http://localhost:8082
# Ensure phoebe-server runs at http://localhost:8001
pytest && black lab/ && ruff check lab/ && mypy lab/
```

## Key Patterns

### Parameter Widgets
- `PhoebeParameterWidget`: Base class — fetches metadata via `client.get_parameter()`, renders number/select/checkbox, writes back via `set_value(uniqueid=...)`
- `PhoebeAdjustableParameterWidget`: Adds "Adjust" checkbox + step input for solver; wires into solver table via `add_parameter_to_solver_table()`
- Widget keys in `self.parameters[...]` use the full twig returned by `parameter.twig` (e.g., `period@binary@orbit@component`)

### Dataset Management  
- `Dataset` class encapsulates: internal model (`self.datasets` dict), AG Grid table, add/edit/remove dialogs
- Each dataset has: `kind` ('lc' or 'rv'), `component` ('' for LC, 'primary'/'secondary' for RV), and data arrays
- RV datasets: one entry per component — user adds separate datasets for primary and secondary RVs
- Checkbox columns (`plot_data`, `plot_model`) use `:editable` JS expressions — note the leading colon

### Plotting Architecture
- **Dual canvas**: `plot_lc_canvas` and `plot_rv_canvas` in separate containers
- **Plot type selector**: `widgets['plot_type']` switches visibility via `on_plot_type_changed()`
- **Unified method**: `create_figure(plot_type='lc'|'rv')` filters datasets by `kind` and builds traces
- Y-axis dropdown hidden for RV (fixed to "RV (km/s)")

### Async Operations
Long-running backend calls use NiceGUI's `run.io_bound()` with button loading indicators:
```python
from nicegui import ui, run

self.compute_button.props('loading')
response = await run.io_bound(self.client.run_compute)
self.compute_button.props(remove='loading')
```
Or with arguments:
```python
response = await run.io_bound(self.client.set_value, twig='period@binary', value=1.5)
```
`run.io_bound()` runs blocking I/O operations in a thread pool without blocking the NiceGUI event loop, keeping the UI responsive during long network calls. Async event handlers pass directly to UI element callbacks (NiceGUI handles execution):
```python
async def handle_delete():
    await self.confirm_delete(session_id, dialog)

ui.button('Delete', on_click=handle_delete)
```

### UI-Only Parameters
Attached at startup via `attach_ui_parameters()`: `project_name@ui`, `backend@ui`, `morphology@ui`, `phase_min@_default@ui`

## API Surface
Backend calls expected by UI (all return `{success, result, error}`):
- Parameters: `get_parameter`, `is_parameter_constrained`, `get_value`, `set_value`, `attach_parameters`
- Datasets: `add_dataset`, `remove_dataset`, `get_datasets`  
- Compute: `run_compute`, `run_solver`
- Bundle: `save_bundle`, `load_bundle`, `new_bundle`, `get_bundle`
- Sessions: `start_session`, `get_sessions`

## Common Tasks

**Add adjustable parameter:**
```python
# In create_parameter_panel():
self.add_parameter(qualifier='q', component='binary', context='component', label='Mass ratio', step=0.01, adjust=False)
```

**Add dataset table column:** Update `_dataset_template`, `columnDefs`, `_collect_from_dialog()`, and `_refresh_table()`

**Add RV dataset with data:**
```python
Dataset.add(kind='rv', dataset='rv01', component='primary', passband='Johnson:V', rvs=[...], times=[...])
```

## Gotchas
- Parameter keys: `self.parameters['period@binary@orbit@component']` — must match exact twig from `create_parameter_panel()`
- AG Grid `:editable`: Leading colon = JS expression string, e.g., `':editable': 'params => params.data.filename !== "Synthetic"'`
- RV datasets: Each component (primary/secondary) is a separate UI dataset entry with its own `plot_data`/`plot_model` checkboxes
- Color schemes: `DATASET_COLORS` list cycles through 6 data/model color pairs with `MARKER_SYMBOLS` and `LINE_DASHES`
- Sessions: ~30min server timeout; UI reconnects via `SessionDialog` if session still valid
- Auth: `main_page()` calls `GET /auth/config` to discover mode (none/password/jwt/external), routes to login dialogs or straight to sessions accordingly
  - `none`: Go straight to session dialogs
  - `password`: `PasswordProtected` gate using `CONFIG.ui.access_password`, then session dialogs
  - `jwt`: `AuthLoginDialog`/`AuthRegisterDialog` first, token stored in `app.storage.user['phoebe_token']`, then session dialogs
  - `external`: Token expected in `app.storage.user['phoebe_token']` (set by upstream), then session dialogs
