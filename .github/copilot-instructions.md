# Copilot Instructions for phoebe.lab

These notes make AI coding agents productive quickly in this repo by capturing the project’s architecture, workflows, and house patterns. Keep answers specific to this codebase.

## Big picture
- Purpose: a NiceGUI-based web UI for PHOEBE Lab to inspect and fit eclipsing-binary models against light/RV curves.
- Backend: talks to a running phoebe worker via REST APIs exposed by `phoebe_client` (`SessionAPI`, `PhoebeAPI`) at http://localhost:8001.
- Frontend: single-page NiceGUI app served from `lab/phoebe_ui.py` on port 8082 (Plotly for charts, AG Grid for tables).
- State model: parameter widgets mirror PHOEBE parameters ("twigs" like `mass@primary@component`); datasets track observational/model arrays and table state.

## Repo layout
- `lab/phoebe_ui.py` — entrypoint and main UI; defines components `PhoebeUI`, `Dataset`, and parameter widgets. Contains `main()` CLI entry point.
- `lab/login.py` — `LoginDialog` (collects first/last name, email) and `SessionDialog` (continue vs. new session choice).
- `lab/user.py` — `User` dataclass with `to_dict()` for passing to session API and `from_dict()` for storage deserialization.
- `lab/utils.py` — small astronomy helpers used by plotting (phase conversion, flux/mag transforms, phase aliasing).
- `examples/` — optional data files shown in the upload dialog (empty by default).
- `pyproject.toml` — package metadata, dependencies, dev tools (black, ruff, mypy, pytest).

## How it works (key flows)
- Login: on first load, `main_page()` shows `LoginDialog` to collect student identification (first name, last name, email). If an existing session is stored, `SessionDialog` offers to continue or start fresh. User metadata is passed to `SessionAPI.start_session(user_metadata=...)` and stored in `app.storage.user`.
- Session management: `PhoebeUI` creates a worker session via `SessionAPI.start_session()`, stores `session_id` and `user` data in `app.storage.user`, and reuses on refresh. It can reconnect to an existing `session_id` if still valid (~30min server timeout).
- Parameter widgets: `PhoebeParameterWidget` fetches parameter meta (`get_parameter`), renders appropriate input (number/select/checkbox), and writes back via `set_value` on change. Constrained parameters are auto-disabled via `is_parameter_constrained`.
- Adjustable parameters: `PhoebeAdjustableParameterWidget` pairs a value, an "Adjust" checkbox, and a step size, and wires into the solver table when toggled.
- Datasets: `Dataset` adds/removes/syncs datasets with the backend (`add_dataset`, `remove_dataset`, `get_datasets`) and manages a table with `plot_data`/`plot_model` toggles. On morphology change, datasets are re-added with current compute phases.
- Compute/fit: `Compute Model` calls `run_compute`; `Run solver` sets `fit_parameters` and `steps` then calls `run_solver`. Both run in a thread pool to keep UI responsive. `Adopt Solution` commits fitted values back to parameters and clears model arrays.
- Plotting: Plotly light-curve view with axis mode switches; phase data are optionally aliased using `lab/utils.py` helpers.

## Developer workflows
- Install: `pip install .` or `pip install -e ".[dev]"` (with pytest, black, ruff, mypy)
- Run UI locally: `phoebe-lab` or `python -m lab.phoebe_ui`, then open http://localhost:8082
- Backend: ensure phoebe-server is running at http://localhost:8001; otherwise compute/fit/load/save calls will return errors, but the UI still loads.
- Dependencies: `nicegui>=1.4.0`, `numpy>=1.26.0`, `plotly>=5.18.0`, `phoebe-client>=0.1.0` (Python 3.12+)
- Storage: NiceGUI `app.storage.user` persists `session_id` and `user` dict between reloads; the `storage_secret` in `ui.run()` must be set.
- Testing: `pytest`, formatting: `black lab/`, linting: `ruff check lab/`, types: `mypy lab/`

## House patterns and conventions
- Parameter addressing uses fully-qualified PHOEBE twigs (e.g., `requiv@primary@component`). Use the same twig string everywhere: as the widget key in `self.parameters[...]`, in API calls (`set_value`, `get_value`), and in solver lists.
- UI-only parameters are attached at startup via `attach_ui_parameters()` as `backend@ui`, `morphology@ui`, and dataset defaults like `phase_min@_default@ui`.
- AG Grid events: use `rowSelected`, `cellDoubleClicked` (opens edit dialog, except on checkbox columns), and `cellValueChanged` to mirror `plot_*` booleans back into `Dataset.datasets`.
- Long-running backend calls run with `get_event_loop().run_in_executor(...)`; always show/remove NiceGUI button `loading` props to signal progress.
- Plot responsiveness: after splitter resize, call `Plotly.Plots.resize(...)` via `ui.run_javascript` on the canvas element id.

## Gotchas and sharp edges
- Twig key mismatch: reading parameters in plotting must use the exact keys created in `create_parameter_panel()`. Example: the code adds `period@binary` and `t0_supconj@binary`; avoid using variants like `period@binary@orbit@component` when indexing `self.parameters`.
- Dataset example files: the dialog looks in `examples/` relative to repo root; keep sample text files there to demo uploads.
- `:editable` in AG Grid column defs is a JS expression (leading colon); pass functions as strings exactly like in `phoebe_ui.py`.
- The backend API surface assumed by the UI includes commands: `get_parameter`, `get_uniqueid`, `is_parameter_constrained`, `get_value`, `set_value`, `attach_params`, `add_dataset`, `remove_dataset`, `get_datasets`, `change_morphology`, `run_compute`, `run_solver`, `save_bundle`, `load_bundle`. Stubs/mocks must mirror these names and response envelopes with `{ success, result, error }`.

## Common extension examples
- Add a new adjustable PHOEBE parameter:
  1) In `create_parameter_panel()`, call `self.add_parameter(twig='<your_twig>', label='...', step=..., adjust=False)`;
  2) Ensure the twig exists in the backend or attach it via `attach_ui_parameters` if UI-only.
- Add a new dataset field to the table: extend `_dataset_template` and the `columnDefs`, and mirror changes in `_collect_from_dialog()` and `_refresh_table()`.

If anything above is unclear or misses a workflow you use, tell me which sections to expand or examples to add, and I’ll refine this doc.