import io
import json
from datetime import datetime
from nicegui import ui, run
from nicegui import app  # noqa: F401 - Required for storage_secret in ui.run()
import numpy as np
import plotly.graph_objects as go
from phoebe_client import PhoebeClient
from lab.config import CONFIG, EXAMPLES_PATH
from lab.utils import time_to_phase, alias_data, flux_to_magnitude
from lab.sessions import StartSessionDialog, SessionManagerDialog, SessionInfo, AuthLoginDialog, AuthRegisterDialog, PasswordProtected


# Color scheme for data/model plots: 10 high-contrast color combinations.
# Each entry contains colors for data markers and model lines, plus symbol/dash
# style for cycling through multiple sets of 10 datasets.

DATASET_COLORS = [
    {'data': '#1f77b4', 'model': '#ff7f0e'},  # Blue / Orange
    {'data': '#2ca02c', 'model': '#d62728'},  # Green / Red
    {'data': '#e377c2', 'model': '#7f7f7f'},  # Pink / Gray
    {'data': '#17becf', 'model': '#bcbd22'},  # Cyan / Olive
    {'data': '#393b79', 'model': '#e7969c'},  # Navy / Salmon
    {'data': '#8c6d31', 'model': '#e7ba52'},  # Sienna / Gold
    # {'data': '#9467bd', 'model': '#8c564b'},  # Purple / Brown
    # {'data': '#637939', 'model': '#b5cf6b'},  # Forest / Lime
    # {'data': '#843c39', 'model': '#ad494a'},  # Maroon / Coral
    # {'data': '#7b4173', 'model': '#ce6dbd'},  # Plum / Orchid
]

# Marker symbols for cycling through datasets beyond the first 10.
MARKER_SYMBOLS = ['circle', 'x', 'diamond', 'square', 'cross']

# Line dash patterns for cycling through datasets beyond the first 10.
LINE_DASHES = ['solid', 'dash', 'dot', 'dashdot', 'longdash']


class PhoebeParameterWidget:
    """
    Parent class for all parameter widgets.
    """

    def __init__(
        self,
        client: PhoebeClient,
        qualifier: str,
        label: str,
        format: str = '%.3f',
        ui_hook=None,
        classes='flex-1 min-w-0',
        visible=True,
        sensitive=True,
        **kwargs
    ):
        self.client = client  # API client
        self.ui_hook = ui_hook  # Optional hook for UI updates

        # grab parameter information:
        request = client.get_parameter(qualifier=qualifier, **kwargs)

        if request['success']:
            par = request['result']

            self.qualifier = qualifier

            self.context = par.get('context', None)
            self.uniqueid = par.get('uniqueid', None)
            self.component = par.get('component', None)
            self.dataset = par.get('dataset', None)
            self.kind = par.get('kind', None)
            self.twig = par.get('twig', None)

            # Store parameter metadata for validation
            self.param_class = par.get('Class', None)
            # Server returns limits as: None, or list of [None, dict{'value':...}, or plain number]
            raw_limits = par.get('limits')
            if raw_limits is None:
                self.limits = [None, None]
            else:
                self.limits = [
                    raw_limits[0]['value'] if isinstance(raw_limits[0], dict) else raw_limits[0],
                    raw_limits[1]['value'] if isinstance(raw_limits[1], dict) else raw_limits[1]
                ]

            value = par.get('value', None)
        else:
            raise ValueError(f"Failed to retrieve parameter {qualifier}: {request.get('error', 'Unknown error')}")

        # Create widget through overridable method
        self.widget = self._widget_layout(par, value, label, format, classes)

        # set default visibility and sensitivity:
        self.visible = visible
        self.sensitive = sensitive

        # TODO: can this be inferred from the get_parameter() call?
        # if parameter is constrained, disable the widget
        response = client.is_parameter_constrained(uniqueid=self.uniqueid)
        if response['success']:
            self.set_sensitive(not response['result'])

        # self.widget.on('change', self.on_value_changed)
        self.widget.on_value_change(self.on_value_changed)

    def _widget_layout(self, par, value, label, format, classes):
        """Create and return the widget based on parameter type. Override in derived classes."""
        if par['Class'] in ['FloatParameter', 'IntParameter']:
            order_of_mag = np.floor(np.log10(np.abs(value))) if value != 0 else 0
            return ui.number(
                label=label,
                value=value,
                format=format,
                min=self.limits[0],
                max=self.limits[1],
                step=float(10**(order_of_mag-2))
            ).classes('flex-1 min-w-0')

        elif par['Class'] == 'StringParameter':
            return ui.input(
                label=label,
                value=value
            ).classes(classes)

        elif par['Class'] == 'ChoiceParameter':
            return ui.select(
                label=label,
                options=par['choices'],
                value=value
            ).classes(classes)

        elif par['Class'] == 'BoolParameter':
            return ui.checkbox(
                text=label,
                value=value
            ).classes('flex-1 min-w-0')

        else:
            raise NotImplementedError(f"Parameter class {par['Class']} not supported yet.")

    def set_sensitive(self, sensitive: bool):
        if sensitive:
            self.widget.enable()
            self.sensitive = True
        else:
            self.widget.disable()
            self.sensitive = False

    def set_visible(self, visible: bool):
        self.widget.classes(remove='hidden') if visible else self.widget.classes(add='hidden')
        self.visible = visible

    def get_value(self):
        if self.widget:
            return self.widget.value

    def set_value(self, value):
        if self.widget:
            self.widget.value = value

    def on_value_changed(self, event):
        if event is None:
            return

        value = self.widget.value

        # Validate value before sending to server
        if not self._validate_value(value):
            return  # Stop propagation if invalid

        try:
            response = self.client.set_value(uniqueid=self.uniqueid, value=value)
            if not response.get('success', False):
                ui.notify(f'Failed to set {self.qualifier}: {response.get("error", "Unknown error")}', type='negative')
                return  # Don't call ui_hook if server rejected the value

            # Only call ui_hook after successful validation and server update
            if self.ui_hook:
                # ui_hooks are always async
                import asyncio
                asyncio.create_task(self.ui_hook(value))
        except Exception as e:
            ui.notify(f'Error setting {self.qualifier}: {str(e)}', type='negative')

    def _validate_value(self, value):
        """Validate value against parameter limits. Returns True if valid."""
        if value is None:
            return False

        # Check limits for numeric parameters
        if self.param_class in ['FloatParameter', 'IntParameter']:
            try:
                value_float = float(value)
            except (TypeError, ValueError):
                # Should not happen as widgets enforce type, but handle gracefully
                return False

            min_limit, max_limit = self.limits
            if min_limit is not None and value_float < min_limit:
                ui.notify(f'{self.qualifier}: Value {value_float} is below minimum {min_limit}', type='warning')
                return False
            if max_limit is not None and value_float > max_limit:
                ui.notify(f'{self.qualifier}: Value {value_float} is above maximum {max_limit}', type='warning')
                return False

        return True


class PhoebeAdjustableParameterWidget(PhoebeParameterWidget):
    """
    Widget for a single Phoebe parameter with value, adjustment checkbox, and step size.
    """

    def __init__(self, qualifier: str, label: str, step: float = 0.001, vformat: str = '%.3f',
                 sformat: str = '%.3f', adjust: bool = False, client=None, ui_ref=None, ui_hook=None, **kwargs):
        self.step = step
        self.adjust = adjust
        self.ui = ui_ref
        self.label = label
        self.vformat = vformat
        self.sformat = sformat

        # Call parent constructor with empty label (we'll show our own in _widget_layout)
        super().__init__(client=client, qualifier=qualifier, label='', format=vformat, ui_hook=ui_hook, **kwargs)

    def _widget_layout(self, par, value, label, format, classes):
        """Create row layout with label, value widget, adjust checkbox, and step input."""
        with ui.row().classes('items-center gap-2 w-full') as self.container:
            # Parameter label
            ui.label(f'{self.label}:').classes('w-24 flex-shrink-0 text-sm')

            # Value widget from parent class
            if par['Class'] in ['FloatParameter', 'IntParameter']:
                order_of_mag = np.floor(np.log10(np.abs(value))) if value != 0 else 0
                value_widget = ui.number(
                    label='Value',
                    value=value,
                    format=self.vformat,
                    min=self.limits[0],
                    max=self.limits[1],
                    step=float(10**(order_of_mag-2))
                ).classes('flex-1 min-w-0')

            elif par['Class'] == 'ChoiceParameter':
                value_widget = ui.select(
                    label='Value',
                    options=par['choices'],
                    value=value
                ).classes(classes)

            elif par['Class'] == 'BoolParameter':
                value_widget = ui.checkbox(
                    text='Value',
                    value=value
                ).classes('flex-1 min-w-0')

            else:
                raise NotImplementedError(f"Parameter class {par['Class']} not supported yet.")

            # Checkbox for adjustment
            self.adjust_checkbox = ui.checkbox(text='Adjust', value=self.adjust).classes('flex-shrink-0')
            self.adjust_checkbox.on('update:model-value', self.on_adjust_toggled)

            # Step size input (after checkbox)
            self.step_input = ui.number(
                label='Step',
                value=self.step,
                format=self.sformat,
                step=self.step/10
            ).classes('flex-1 min-w-0')

            # Set initial state of step input
            self.on_adjust_toggled()

        return value_widget

    def set_visible(self, visible: bool):
        """Override to control entire row container visibility."""
        self.container.classes(remove='hidden') if visible else self.container.classes(add='hidden')
        self.visible = visible

    def set_sensitive(self, sensitive: bool):
        """Override to control value widget sensitivity."""
        if sensitive:
            self.widget.enable()
            self.sensitive = True
        else:
            self.widget.disable()
            self.sensitive = False

    def get_twig(self):
        return self.twig

    def on_adjust_toggled(self):
        """Handle adjust checkbox state change."""
        if self.ui is None:
            return

        self.adjust = self.adjust_checkbox.value

        if self.adjust:
            self.step_input.enable()
            self.step_input.classes(remove='text-gray-400')
            if self.ui.fully_initialized:
                self.ui.add_parameter_to_solver_table(self)
        else:
            self.step_input.disable()
            self.step_input.classes(add='text-gray-400')
            if self.ui.fully_initialized:
                self.ui.remove_parameter_from_solver_table(self)


class Dataset:
    """
    Fully encapsulated dataset component managing data model, UI, and interactions.
    Handles dataset creation, editing, display, and synchronization with bundle.
    """

    def __init__(self, client: PhoebeClient):
        self.client = client

        # Internal data model
        self.datasets = {}
        self._dataset_template = {
            'kind': 'lc',
            'dataset': 'ds01',
            'passband': 'Johnson:V',
            'component': '',       # 'primary' or 'secondary' for RV datasets, empty for LC
            'times': [],
            'fluxes': [],          # LC data
            'model_fluxes': [],    # LC model
            'rvs': [],             # RV data (single component per dataset)
            'model_rvs': [],       # RV model (single component per dataset)
            'sigmas': [],
            'filename': '',
            'n_points': 201,
            'phase_min': -0.5,
            'phase_max': 0.5,
            'data_points': 0,
            'plot_data': False,
            'plot_model': False
        }

        # UI references (will be set during mount)
        self.dataset_table = None
        # self.dataset_dialog = None
        self.widgets = {}
        self.selected_row = None

        # File upload state
        self.data_file = None
        self.data_content = None

        # Dialog state
        self._editing_mode = False
        self._editing_dataset = None

    def add(self, **kwargs):
        """Add a dataset to both internal model and bundle."""
        kind = kwargs.get('kind', None)
        dataset = kwargs.get('dataset', None)

        if kind is None:
            raise ValueError('Dataset kind not specified.')
        if dataset is None:
            raise ValueError('Dataset label not specified.')
        if dataset in self.datasets:
            raise ValueError(f'Dataset {dataset} already exists -- please choose a unique label.')

        dataset_meta = self._dataset_template.copy()
        dataset_meta.update(kwargs)
        self.datasets[dataset] = dataset_meta

        compute_phases = np.linspace(
            dataset_meta['phase_min'],
            dataset_meta['phase_max'],
            dataset_meta['n_points']
        )

        data_kwargs = {}
        if kind == 'lc':
            data_kwargs['times'] = dataset_meta.get('times', [])
            data_kwargs['fluxes'] = dataset_meta.get('fluxes', [])
            data_kwargs['sigmas'] = dataset_meta.get('sigmas', [])
            data_kwargs['pblum_mode'] = 'dataset-scaled' if len(dataset_meta.get('fluxes', [])) > 0 else 'component-coupled'
        elif kind == 'rv':
            component = dataset_meta.get('component', None)
            if component is None or component not in ['primary', 'secondary']:
                raise ValueError('RV dataset must specify component (primary/secondary).')

            times_arr = np.array(dataset_meta.get('times', []))
            rvs_arr = np.array(dataset_meta.get('rvs', []))
            sigmas_arr = np.array(dataset_meta.get('sigmas', []))

            # Synthetic RVs: send only compute_phases so PHOEBE computes both components
            if len(times_arr) == 0 and len(rvs_arr) == 0:
                data_kwargs['component'] = None
            else:
                data_kwargs['times'] = {component: times_arr}
                data_kwargs['rvs'] = {component: rvs_arr}
                if len(sigmas_arr) == len(times_arr) and len(sigmas_arr) > 0:
                    data_kwargs['sigmas'] = {component: sigmas_arr}

        self.client.add_dataset(
            kind=dataset_meta.get('kind'),
            dataset=dataset_meta.get('dataset'),
            passband=dataset_meta.get('passband', 'Johnson:V'),
            compute_phases=compute_phases,
            overwrite=True,
            **data_kwargs
        )

    def remove(self, dataset):
        """Remove a dataset from both internal model and bundle."""
        if dataset not in self.datasets:
            raise ValueError(f'Dataset {dataset} does not exist.')

        response = self.client.remove_dataset(dataset=dataset)
        if not response.get('success', False):
            raise ValueError(f"Failed to remove dataset from backend: {response.get('error', 'Unknown error')}")

        del self.datasets[dataset]

    def readd_all(self):
        """Re-add all datasets to bundle (used after morphology change)."""
        for dataset in self.datasets.values():
            compute_phases = np.linspace(
                dataset['phase_min'],
                dataset['phase_max'],
                dataset['n_points']
            )

            params = {
                'dataset': dataset.get('dataset'),
                'passband': dataset.get('passband'),
                'compute_phases': compute_phases,
            }

            if dataset['kind'] == 'lc':
                params['times'] = dataset.get('times', [])
                params['fluxes'] = dataset.get('fluxes', [])
                params['sigmas'] = dataset.get('sigmas', [])
            elif dataset['kind'] == 'rv':
                component = dataset.get('rv_component', None)
                if component is None or component not in ['primary', 'secondary']:
                    raise ValueError('RV dataset must specify component (primary/secondary).')

                times_arr = np.array(dataset.get('times', []))
                rvs_arr = np.array(dataset.get('rvs', []))
                sigmas_arr = np.array(dataset.get('sigmas', []))

                # Synthetic RVs: omit times/rvs so PHOEBE computes both components
                if len(times_arr) == 0 and len(rvs_arr) == 0:
                    params.pop('times', None)
                    params.pop('sigmas', None)
                else:
                    params['times'] = {component: times_arr}
                    params['rvs'] = {component: rvs_arr}
                    if len(sigmas_arr) == len(times_arr) and len(sigmas_arr) > 0:
                        params['sigmas'] = {component: sigmas_arr}

            self.client.add_dataset(
                kind=dataset['kind'],
                overwrite=True,
                **params
            )
            if len(dataset.get('fluxes', [])) > 0:
                self.client.set_value(twig=f'pblum_mode@{dataset["dataset"]}', value='dataset-scaled')

    def sync_from_pset(self, pset):
        """Synchronize internal model from the parameter set."""

        # clear existing datasets
        self.datasets = {}

        # get all datasets in the parameter set:
        datasets = list(set([par['dataset'] for par in pset if 'dataset' in par and par['dataset'] != '_default']))

        # gather all dataset parameters:
        ds_params = {ds: [par for par in pset if 'dataset' in par and par['dataset'] == ds] for ds in datasets}

        # define a helper function to extract parameter values:
        def get_value(qualifier, context, dataset, component=None):
            for par in ds_params[dataset]:
                if component is None:
                    if par['qualifier'] == qualifier and par['context'] == context:
                        return par['value']
                else:
                    if par['qualifier'] == qualifier and par['context'] == context and par.get('component') == component:
                        return par['value']
            return None

        for dataset in datasets:
            kind = ds_params[dataset][0]['kind']
            passband = get_value(qualifier='passband', context='dataset', dataset=dataset)
            sigmas = get_value(qualifier='sigmas', context='dataset', dataset=dataset)
            sigmas = np.array(sigmas) if sigmas is not None else np.array([])

            if kind == 'lc':
                # LC: single dataset entry
                times = get_value(qualifier='times', context='dataset', dataset=dataset)
                times = np.array(times) if times is not None else np.array([])
                fluxes = get_value(qualifier='fluxes', context='dataset', dataset=dataset)
                fluxes = np.array(fluxes) if fluxes is not None else np.array([])
                model_fluxes = get_value(qualifier='fluxes', context='model', dataset=dataset)
                model_fluxes = np.array(model_fluxes) if model_fluxes is not None else np.array([])

                # Get phase parameters from UI context (with fallback defaults)
                phase_min = get_value(qualifier='phase_min', context='ui', dataset=dataset)
                phase_max = get_value(qualifier='phase_max', context='ui', dataset=dataset)
                phase_length = get_value(qualifier='phase_length', context='ui', dataset=dataset)

                ds_meta = self._dataset_template.copy()
                ds_meta.update({
                    'kind': 'lc',
                    'dataset': dataset,
                    'passband': passband,
                    'component': '',
                    'times': times,
                    'sigmas': sigmas,
                    'fluxes': fluxes,
                    'model_fluxes': model_fluxes,
                    'data_points': len(times),
                    'filename': 'From bundle' if len(times) > 0 else 'Synthetic',
                    'n_points': phase_length or 201,
                    'phase_min': phase_min or -0.5,
                    'phase_max': phase_max or 0.5,
                    'plot_data': False,
                    'plot_model': False
                })
                self.datasets[dataset] = ds_meta
            elif kind == 'rv':
                # For RV: retrieve per-component data (if present) and keep single-component datasets
                times_primary = get_value(qualifier='times', context='dataset', component='primary', dataset=dataset)
                times_primary = np.array(times_primary) if times_primary is not None else np.array([])
                times_secondary = get_value(qualifier='times', context='dataset', component='secondary', dataset=dataset)
                times_secondary = np.array(times_secondary) if times_secondary is not None else np.array([])

                rvs_primary = get_value(qualifier='rvs', context='dataset', dataset=dataset, component='primary')
                rvs_primary = np.array(rvs_primary) if rvs_primary is not None else np.array([])
                rvs_secondary = get_value(qualifier='rvs', context='dataset', dataset=dataset, component='secondary')
                rvs_secondary = np.array(rvs_secondary) if rvs_secondary is not None else np.array([])

                model_rvs_primary = get_value(qualifier='rvs', context='model', dataset=dataset, component='primary')
                model_rvs_primary = np.array(model_rvs_primary) if model_rvs_primary is not None else np.array([])
                model_rvs_secondary = get_value(qualifier='rvs', context='model', dataset=dataset, component='secondary')
                model_rvs_secondary = np.array(model_rvs_secondary) if model_rvs_secondary is not None else np.array([])

                has_primary_data = len(rvs_primary) > 0 or len(times_primary) > 0
                has_secondary_data = len(rvs_secondary) > 0 or len(times_secondary) > 0

                rv_component = get_value(qualifier='rv_component', context='ui', dataset=dataset)

                # Phase parameters (ui context)
                phase_min = get_value(qualifier='phase_min', context='ui', dataset=dataset)
                phase_max = get_value(qualifier='phase_max', context='ui', dataset=dataset)
                phase_length = get_value(qualifier='phase_length', context='ui', dataset=dataset)

                def build_ds(label_suffix, component, times_arr, rvs_arr, model_arr):
                    ds_meta = self._dataset_template.copy()
                    ds_meta.update({
                        'kind': 'rv',
                        'dataset': f"{dataset}{label_suffix}",
                        'passband': passband,
                        'component': component,
                        'times': times_arr,
                        'sigmas': sigmas,
                        'rvs': rvs_arr,
                        'model_rvs': model_arr,
                        'data_points': len(times_arr),
                        'filename': 'From bundle' if len(times_arr) > 0 else 'Synthetic',
                        'n_points': phase_length if phase_length is not None else 201,
                        'phase_min': phase_min if phase_min is not None else -0.5,
                        'phase_max': phase_max if phase_max is not None else 0.5,
                        'plot_data': False,
                        'plot_model': False
                    })
                    self.datasets[ds_meta['dataset']] = ds_meta

                if has_primary_data and has_secondary_data:
                    if rv_component in ['primary', 'secondary']:
                        if rv_component == 'primary':
                            build_ds('', 'primary', times_primary, rvs_primary, model_rvs_primary)
                        else:
                            build_ds('', 'secondary', times_secondary, rvs_secondary, model_rvs_secondary)
                    else:
                        # Split into two datasets to avoid ambiguity
                        build_ds('_primary', 'primary', times_primary, rvs_primary, model_rvs_primary)
                        build_ds('_secondary', 'secondary', times_secondary, rvs_secondary, model_rvs_secondary)
                elif has_primary_data:
                    build_ds('', 'primary', times_primary, rvs_primary, model_rvs_primary)
                elif has_secondary_data:
                    build_ds('', 'secondary', times_secondary, rvs_secondary, model_rvs_secondary)
                else:
                    # Synthetic-only RV: keep empty arrays; component from UI if available
                    component = rv_component if rv_component in ['primary', 'secondary'] else 'primary'
                    build_ds('', component, np.array([]), np.array([]), model_rvs_primary if component == 'primary' else model_rvs_secondary)
            else:
                ui.notify(f'Unsupported dataset {dataset} kind {kind} in bundle, ignoring.')

    def sync_from_server(self):
        """Synchronize internal model from the server."""
        response = self.client.get_datasets()

        if not response.get('success', False):
            ui.notify(f"Failed to get datasets from bundle: {response.get('error', 'Unknown error')}", type='negative')
            return

        bundle_datasets = response['result']['datasets']
        self.datasets = {}

        # Populate model from bundle data
        for ds_label, ds_data in bundle_datasets.items():
            kind = ds_data.get('kind', 'invalid')
            times = np.array(ds_data.get('times', [])) if ds_data.get('times') is not None else np.array([])

            if kind == 'lc':
                dataset_meta = self._dataset_template.copy()
                dataset_meta.update({
                    'kind': 'lc',
                    'dataset': ds_label,
                    'passband': ds_data.get('passband', 'Johnson:V'),
                    'component': '',
                    'times': times,
                    'fluxes': np.array(ds_data.get('fluxes', [])) if ds_data.get('fluxes') is not None else np.array([]),
                    'sigmas': np.array(ds_data.get('sigmas', [])) if ds_data.get('sigmas') is not None else np.array([]),
                    'data_points': len(times),
                    'filename': 'From server' if len(times) > 0 else 'Synthetic',
                    'n_points': 201,
                    'phase_min': -0.5,
                    'phase_max': 0.5,
                    'model_fluxes': [],
                    'plot_data': False,
                    'plot_model': False
                })
                self.datasets[ds_label] = dataset_meta
            elif kind == 'rv':
                # RV data from server may come as dicts keyed by component or as arrays
                times_data = ds_data.get('times', {})
                rvs_data = ds_data.get('rvs', {})

                # Handle both dict format (keyed by component) and array format
                if isinstance(times_data, dict):
                    times_primary = np.array(times_data.get('primary', []))
                    times_secondary = np.array(times_data.get('secondary', []))
                else:
                    times_primary = np.array(times_data) if times_data is not None else np.array([])
                    times_secondary = np.array([])

                if isinstance(rvs_data, dict):
                    rvs_primary = np.array(rvs_data.get('primary', []))
                    rvs_secondary = np.array(rvs_data.get('secondary', []))
                else:
                    rvs_primary = np.array(rvs_data) if rvs_data is not None else np.array([])
                    rvs_secondary = np.array([])

                # Determine which component has data
                has_primary_data = len(rvs_primary) > 0 or len(times_primary) > 0
                has_secondary_data = len(rvs_secondary) > 0 or len(times_secondary) > 0

                if has_primary_data:
                    component = 'primary'
                    times = times_primary
                    rvs = rvs_primary
                elif has_secondary_data:
                    component = 'secondary'
                    times = times_secondary
                    rvs = rvs_secondary
                else:
                    # Synthetic - default to primary
                    component = 'primary'
                    times = np.array([])
                    rvs = np.array([])

                dataset_meta = self._dataset_template.copy()
                dataset_meta.update({
                    'kind': 'rv',
                    'dataset': ds_label,
                    'passband': ds_data.get('passband', 'Johnson:V'),
                    'component': component,
                    'times': times,
                    'rvs': rvs,
                    'sigmas': np.array(ds_data.get('sigmas', [])) if ds_data.get('sigmas') is not None else np.array([]),
                    'data_points': len(times),
                    'filename': 'imported' if len(times) > 0 else 'Synthetic',
                    'n_points': 201,
                    'phase_min': -0.5,
                    'phase_max': 0.5,
                    'model_rvs': [],
                    'plot_data': False,
                    'plot_model': False
                })
                self.datasets[ds_label] = dataset_meta
            else:
                ui.notify(f'Unsupported dataset {ds_label} received from the server, ignoring.')

    def _collect_from_dialog(self):
        """Collect dataset parameters from dialog widgets."""
        kind = self.widgets['dataset_kind'].value

        params = {
            'kind': kind,
            'dataset': self.widgets['dataset_label'].value,
            'component': self.widgets['dataset_component'].value if kind == 'rv' else 'binary',
            'passband': self.widgets['dataset_passband'].value,
            'n_points': int(self.widgets['dataset_n_points'].value),
            'phase_min': self.widgets['dataset_phase_min'].value,
            'phase_max': self.widgets['dataset_phase_max'].value,
        }

        # Add data if available (from file upload)
        if self.data_file:
            params['filename'] = self.data_file

            if self.data_content:
                data_content = np.genfromtxt(io.StringIO(self.data_content))
            else:
                data_content = np.genfromtxt(self.data_file)

            params['data_points'] = len(data_content)
            params['times'] = data_content[:, 0]

            if kind == 'lc':
                params['fluxes'] = data_content[:, 1]
            elif kind == 'rv':
                params['rvs'] = data_content[:, 1]

            # Sigmas are optional (3rd column); default to empty if not present
            if data_content.ndim == 2 and data_content.shape[1] >= 3:
                params['sigmas'] = data_content[:, 2]
            else:
                params['sigmas'] = np.ones_like(params['times']) * 0.01  # Default small errors
        else:
            params['filename'] = 'Synthetic'
            params['data_points'] = 0
            # Initialize empty arrays for synthetic datasets
            params['times'] = []
            params['sigmas'] = np.ones_like(params['times']) * 0.01  # Default small errors
            if kind == 'lc':
                params['fluxes'] = []
            elif kind == 'rv':
                params['rvs'] = []

        return params

    def _populate_dialog_from_dataset(self, dataset_label):
        """Populate dialog widgets from an existing dataset."""
        if dataset_label not in self.datasets:
            ui.notify(f"Dataset {dataset_label} not found", type='warning')
            return

        dataset_meta = self.datasets[dataset_label]

        # Mark as editing mode
        self._editing_mode = True
        self._editing_dataset = dataset_label

        # Update dialog UI for edit mode
        self.dialog_title.text = f'Edit Dataset: {dataset_label}'
        self.dialog_action_button.text = 'Save'

        # Populate all fields
        self.widgets['dataset_kind'].value = dataset_meta.get('kind')
        self.widgets['dataset_label'].value = dataset_meta.get('dataset')
        self.widgets['dataset_passband'].value = dataset_meta.get('passband')
        self.widgets['dataset_n_points'].value = dataset_meta.get('n_points')
        self.widgets['dataset_phase_min'].value = dataset_meta.get('phase_min')
        self.widgets['dataset_phase_max'].value = dataset_meta.get('phase_max')

        # Populate component for RV datasets
        if dataset_meta.get('kind') == 'rv':
            self.widgets['dataset_component'].value = dataset_meta.get('component')
            self._update_component_visibility()

        # Disable label widget (can't change dataset designation)
        self.widgets['dataset_label'].disable()

    def _refresh_table(self):
        """Refresh the dataset table UI from internal model."""
        if not self.dataset_table:
            return

        row_data = []
        for ds_label, ds_meta in self.datasets.items():
            phase_min = ds_meta.get('phase_min', -0.5)
            phase_max = ds_meta.get('phase_max', 0.5)
            n_points = ds_meta.get('n_points', 201)
            phases_str = f'({phase_min:.2f}, {phase_max:.2f}, {n_points})'

            row_data.append({
                'label': ds_label,
                'type': ds_meta['kind'],
                'component': ds_meta['component'],
                'passband': ds_meta['passband'],
                'filename': ds_meta['filename'],
                'phases': phases_str,
                'data_points': ds_meta['data_points'],
                'plot_data': ds_meta.get('plot_data', False),
                'plot_model': ds_meta.get('plot_model', False)
            })

        self.dataset_table.options['rowData'] = row_data
        self.dataset_table.update()

    def mount_panel(self):
        """Mount the dataset management panel UI (table + buttons)."""
        with ui.expansion('Dataset Management', icon='table_chart', value=True).classes('w-full mb-2').style('padding: 2px;'):
            # Enhanced dataset control grid
            self.dataset_table = ui.aggrid({
                'columnDefs': [
                    {'field': 'label', 'headerName': 'Dataset', 'width': 100, 'sortable': True},
                    {'field': 'type', 'headerName': 'Type', 'width': 50, 'sortable': True},
                    {'field': 'component', 'headerName': 'Component', 'width': 60, 'sortable': True},
                    {'field': 'phases', 'headerName': 'Phases', 'width': 100, 'sortable': True},
                    {'field': 'data_points', 'headerName': 'Pts', 'width': 60, 'sortable': True, 'type': 'numericColumn'},
                    {'field': 'passband', 'headerName': 'Passband', 'width': 90, 'sortable': True},
                    {'field': 'filename', 'headerName': 'Source', 'width': 100, 'sortable': True},
                    {
                        'field': 'plot_data',
                        'headerName': 'Data',
                        'width': 70,
                        'cellRenderer': 'agCheckboxCellRenderer',
                        ':editable': 'params => { return params.data.filename !== "Synthetic"; }'
                    },
                    {
                        'field': 'plot_model',
                        'headerName': 'Model',
                        'width': 70,
                        'cellRenderer': 'agCheckboxCellRenderer',
                        'editable': True
                    }
                ],
                'rowData': [],
                'domLayout': 'autoHeight',
                'suppressHorizontalScroll': False,
                'enableCellChangeFlash': True,
                'rowSelection': 'single',
                'overlayNoRowsTemplate': 'No datasets added. Click "Add" to define a synthetic dataset or load observations.',
            }).classes('w-full').style('height: auto; min-height: 80px; max-height: 300px;')

            # Listen to events
            self.dataset_table.on('rowSelected', self._on_row_selected)
            self.dataset_table.on('cellDoubleClicked', self._on_cell_double_clicked)
            self.dataset_table.on('cellValueChanged', self._on_checkbox_toggled)

            # Dataset action buttons
            with ui.row().classes('gap-2 justify-end w-full'):
                ui.button('Add', on_click=self._on_add_clicked, icon='add').props('flat color=primary')
                ui.button('Edit', on_click=self._on_edit_clicked, icon='edit').props('flat color=secondary')
                ui.button('Remove', on_click=self._on_remove_clicked, icon='delete').props('flat color=negative')

    def mount_dialog(self):
        """Mount the dataset creation/edit dialog."""
        def format_file_size(size_bytes: int) -> str:
            units = ['B', 'KB', 'MB', 'GB']
            size = float(size_bytes)
            for unit in units:
                if size < 1024.0 or unit == units[-1]:
                    if unit == 'B':
                        return f'{int(size)} {unit}'
                    return f'{size:.1f} {unit}'
                size /= 1024.0
            return f'{size_bytes} B'

        with ui.dialog() as self.dataset_dialog, ui.card().classes('w-[800px] h-[600px]'):
            self.dialog_title = ui.label('Add Dataset').classes('text-xl font-bold mb-4')

            with ui.column().classes('w-full gap-4'):
                self.widgets['dataset_kind'] = ui.select(
                    options={'lc': 'Light Curve', 'rv': 'RV Curve'},
                    label='Dataset type',
                    value='lc'
                ).classes('w-full')
                self.widgets['dataset_kind'].on('update:model-value', self._update_component_visibility)

                self.widgets['dataset_label'] = ui.input(
                    label='Dataset Label',
                    placeholder='e.g., lc01, rv01, etc.',
                ).classes('w-full')

                # Component dropdown (only visible for RV datasets)
                self.widgets['dataset_component'] = ui.select(
                    options={'primary': 'Primary', 'secondary': 'Secondary'},
                    label='Component',
                    value='primary'
                ).classes('w-full hidden')

                self.widgets['dataset_passband'] = ui.select(
                    options=['GoChile:R', 'GoChile:G', 'GoChile:B', 'GoChile:L', 'TESS:T', 'Kepler:mean', 'Gaia:BP', 'Gaia:RP', 'Gaia:G', 'Gaia:RVS', 'Johnson:V'],
                    label='Passband',
                    value='Johnson:V'
                ).classes('w-full')

                # Phase parameters section
                with ui.expansion('Model', icon='straighten', value=False).classes('w-full mt-4'):
                    with ui.row().classes('gap-2 w-full'):
                        self.widgets['dataset_phase_min'] = ui.number(
                            label='Phase min', value=-0.5, step=0.1, format='%.2f'
                        ).classes('flex-1')

                        self.widgets['dataset_phase_max'] = ui.number(
                            label='Phase max', value=0.5, step=0.1, format='%.2f'
                        ).classes('flex-1')

                        self.widgets['dataset_n_points'] = ui.number(
                            label='Length', value=201, min=20, max=10000, step=1, format='%d'
                        ).classes('flex-1')

            ui.separator().classes('my-4')

            with ui.expansion('Observations', icon='insert_chart', value=False).classes('w-full'):
                with ui.tabs().classes('w-full') as tabs:
                    example_tab = ui.tab('Example Files')
                    upload_tab = ui.tab('Upload File')

                with ui.tab_panels(tabs, value=example_tab).classes('w-full'):
                    # Example tab
                    with ui.tab_panel(example_tab):
                        ui.label('Select an example data file:').classes('mb-2')

                        example_files = []

                        if EXAMPLES_PATH.is_dir():
                            ignore = ['__init__.py', '__pycache__']
                            for file_path in sorted(EXAMPLES_PATH.iterdir(), key=lambda path: path.name.lower()):
                                if file_path.is_file() and file_path.name not in ignore:
                                    file_stat = file_path.stat()
                                    example_files.append({
                                        'name': file_path.name,
                                        'path': str(file_path),
                                        'size': format_file_size(file_stat.st_size),
                                        'modified': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                                    })

                        if example_files:
                            self.example_list = ui.aggrid({
                                'columnDefs': [
                                    {'headerName': 'Filename:', 'field': 'filename', 'sortable': True},
                                    {'headerName': 'Size:', 'field': 'size', 'sortable': True, 'type': 'numericColumn', 'cellClass': 'text-right'},
                                    {'headerName': 'Modified:', 'field': 'modified', 'sortable': True},
                                ],
                                'rowData': [
                                ],
                                'rowSelection': 'single',
                            })

                            for example_file in example_files:
                                self.example_list.options['rowData'].append({
                                    'filename': example_file['name'],
                                    'size': example_file['size'],
                                    'modified': example_file['modified'],
                                })
                            self.example_list.update()

                            def on_example_row_selected(event):
                                if event.args and 'data' in event.args and 'filename' in event.args['data']:
                                    self.data_file = str(EXAMPLES_PATH / event.args['data']['filename'])
                                    self.data_content = None

                            self.example_list.on('rowSelected', on_example_row_selected)

                        else:
                            ui.label('No example files found').classes('text-gray-500')

                    # Upload tab
                    with ui.tab_panel(upload_tab):
                        ui.label('Upload a data file from your computer:').classes('mb-2')
                        ui.label('Supported formats: Space or tab-separated text files with columns:').classes('text-sm text-gray-600')
                        ui.label('Time, Flux/Magnitude/Velocity, Error').classes('text-sm text-gray-600 mb-4')

                        ui.upload(
                            max_file_size=10_000_000,
                            max_files=1,
                            on_upload=self._on_file_uploaded,
                            auto_upload=True
                        ).classes('w-full border-2 border-dashed border-gray-300 rounded-lg p-8 text-center')

            ui.separator().classes('my-4')

            with ui.row().classes('gap-2 justify-end w-full'):
                ui.button('Cancel', on_click=self.dataset_dialog.close).classes('bg-gray-500')
                self.dialog_action_button = ui.button('Add', icon='save', on_click=self._on_dialog_add_clicked).classes('bg-blue-500')

    def refresh(self):
        """Public method to refresh the table from model."""
        self._refresh_table()

    def _update_component_visibility(self):
        """Show/hide component dropdown based on dataset kind selection."""
        kind = self.widgets['dataset_kind'].value
        if kind == 'rv':
            self.widgets['dataset_component'].classes(remove='hidden')
        else:
            self.widgets['dataset_component'].classes(add='hidden')

    def _on_add_clicked(self):
        """Handle Add button click."""
        # Reset to add mode
        self._editing_mode = False
        self._editing_dataset = None

        # Update dialog UI for add mode
        self.dialog_title.text = 'Add Dataset'
        self.dialog_action_button.text = 'Add'

        # Clear and enable all fields
        self.widgets['dataset_kind'].value = 'lc'
        self.widgets['dataset_label'].value = f'ds{len(self.datasets)+1:02d}'
        self.widgets['dataset_label'].enable()
        self.widgets['dataset_passband'].value = 'Johnson:V'
        self.widgets['dataset_component'].value = 'primary'
        self.widgets['dataset_n_points'].value = 201
        self.widgets['dataset_phase_min'].value = -0.5
        self.widgets['dataset_phase_max'].value = 0.5

        # Reset component visibility
        self._update_component_visibility()

        # Clear file upload state
        self.data_file = None
        self.data_content = None

        # Clear example file selection in grid so each dialog open starts unselected
        if hasattr(self, 'example_list') and self.example_list is not None:
            self.example_list.run_grid_method('deselectAll')

        self.dataset_dialog.open()

    def _on_edit_clicked(self):
        """Handle Edit button click."""
        if not self.selected_row:
            ui.notify('Please select a dataset to edit.', type='warning')
            return
        dataset_label = self.selected_row['label']
        self._populate_dialog_from_dataset(dataset_label)
        self.dataset_dialog.open()

    def _on_cell_double_clicked(self, event):
        """Handle double-click on table cell to edit.

        Skip if user double-clicked on checkbox cells (plot_data, plot_model),
        otherwise open the edit dialog.
        """
        if not event.args:
            return

        # Get the column that was double-clicked
        column = event.args.get('colId', '')

        # Skip if double-clicking on checkbox columns
        if column in ['plot_data', 'plot_model']:
            return

        # Get the dataset label and open edit dialog
        if 'data' in event.args and 'label' in event.args['data']:
            dataset_label = event.args['data']['label']
            self._populate_dialog_from_dataset(dataset_label)
            self.dataset_dialog.open()

    def _on_remove_clicked(self):
        """Handle Remove button click."""
        if not self.selected_row:
            ui.notify('Please select a dataset to remove.', type='warning')
            return

        dataset = self.selected_row['label']

        with ui.dialog() as dialog, ui.card():
            ui.label(f'Are you sure you want to remove dataset "{dataset}"?').classes('text-lg font-bold')
            with ui.row().classes('gap-2 justify-end mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                ui.button('Remove', on_click=lambda: self._on_remove_confirmed(dataset, dialog), color='negative').props('flat')
        dialog.open()

    def _on_remove_confirmed(self, dataset, dialog):
        """Handle Remove confirmation."""
        self.remove(dataset)
        self._refresh_table()
        dialog.close()

    def _on_dialog_add_clicked(self):
        """Handle Add/Save button in dialog."""
        model = self._collect_from_dialog()

        try:
            if self._editing_mode:
                # Update existing dataset
                # Remove old version and add updated version
                if self._editing_dataset and self._editing_dataset in self.datasets:
                    self.remove(self._editing_dataset)
                self.add(**model)
                ui.notify(f'Dataset {model["dataset"]} updated successfully', type='positive')
            else:
                # Add new dataset
                self.add(**model)
                ui.notify(f'Dataset {model["dataset"]} added successfully', type='positive')

            # Sync phase parameters to backend UI parameters for persistence
            dataset = model['dataset']
            self.client.set_value(twig=f'phase_min@{dataset}@ui', value=model['phase_min'])
            self.client.set_value(twig=f'phase_max@{dataset}@ui', value=model['phase_max'])
            self.client.set_value(twig=f'phase_length@{dataset}@ui', value=model['n_points'])

            # Sync component parameter for RV datasets
            if model['kind'] == 'rv':
                self.client.set_value(twig=f'rv_component@{dataset}@ui', value=model['component'])
        except Exception as e:
            ui.notify(f'Error saving dataset: {e}', type='negative')
            return

        self._refresh_table()
        self.dataset_dialog.close()

    def _on_row_selected(self, event):
        """Handle row selection in table."""
        if event.args and 'data' in event.args and 'label' in event.args['data']:
            self.selected_row = event.args['data']
        else:
            self.selected_row = None

    def _on_checkbox_toggled(self, event):
        """Handle checkbox toggle in table."""
        dataset = event.args['data']['label']
        field = event.args['colId']
        state = event.args['value']
        self.datasets[dataset][field] = state

    async def _on_file_uploaded(self, event):
        """Handle file upload."""

        if event and event.file:
            self.data_file = event.file.name
            self.data_content = await event.file.text()
            ui.notify(f'File uploaded: {self.data_file}', type='positive')
        else:
            ui.notify('File upload failed.', type='negative')


class PhoebeUI:
    """Main Phoebe UI."""

    def __init__(self, phoebe_client: PhoebeClient, session_info: SessionInfo, context_data: dict = {}):
        # prevent callbacks from firing during init:
        self.fully_initialized = False

        self.client = phoebe_client
        self.session_info = session_info
        self.context_data = context_data

        # sync session id with upstream:
        self.client.set_session_id(session_info.session_id)

        # Parameters:
        self.parameters = {}

        # Reference to widgets:
        self.widgets = {}

        # Initialize dataset component:
        self.dataset = Dataset(client=self.client)
        self.dataset.mount_dialog()  # Create dialog upfront

        # Create main UI (will be shown after dialog)
        with ui.splitter(value=30).classes('w-full h-screen') as self.main_splitter:
            # Left panel - Parameters, data, and controls
            with self.main_splitter.before:
                with ui.scroll_area().classes('w-full h-full p-4'):
                    self.create_parameter_panel()

            # Right panel - Data, plots and results
            with self.main_splitter.after:
                self.create_analysis_panel()

        # Handle plot resize on splitter change (plots are created lazily)
        def resize_plot():
            if self.plot_lc_canvas is not None:
                plot_id = self.plot_lc_canvas.id
                ui.run_javascript(f'Plotly.Plots.resize(getHtmlElement({plot_id}))')
            if self.plot_rv_canvas is not None:
                plot_id = self.plot_rv_canvas.id
                ui.run_javascript(f'Plotly.Plots.resize(getHtmlElement({plot_id}))')

        self.main_splitter.on_value_change(resize_plot)

        # Set project name parameter from session info
        if self.session_info.project_name:
            self.parameters['project_name@ui'].set_value(self.session_info.project_name)
            self.parameters['project_name@ui'].on_value_changed(event=False)

        # If reconnecting to existing session, sync UI state from backend bundle
        if not self.session_info.is_new_session:
            # sync with upstream:
            response = self.client.get_bundle()
            if response.get('success'):
                pset = json.loads(response['result'].get('bundle'))
                import asyncio
                asyncio.create_task(self.sync_ui_state(pset=pset))

        self.fully_initialized = True

    def add_parameter(self, qualifier: str, label: str, step: float, adjust: bool, vformat: str = '%.3f', sformat: str = '%.3f', on_value_changed=None, **kwargs):
        parameter = PhoebeAdjustableParameterWidget(
            qualifier=qualifier,
            label=label,
            step=step,
            adjust=adjust,
            vformat=vformat,
            sformat=sformat,
            client=self.client,
            ui_ref=self,
            ui_hook=on_value_changed,
            **kwargs
        )

        # name the parameter by its fully qualified twig:
        self.parameters[parameter.twig] = parameter

    def create_parameter_panel(self):
        # Load/Save buttons
        with ui.row().classes('w-full gap-2 mb-4'):
            self.new_button = ui.button(
                'New',
                icon='note_add',
                on_click=self.on_new_model
            ).classes('flex-1 bg-gray-600 text-white')

            self.load_button = ui.button(
                'Load',
                icon='file_upload',
                on_click=self.on_load_model
            ).classes('flex-1 bg-blue-600 text-white')

            self.save_button = ui.button(
                'Save',
                icon='file_download',
                on_click=self.on_save_model
            ).classes('flex-1 bg-green-600 text-white')

            # Menu button for additional options
            with ui.button(icon='menu').classes('bg-gray-700 text-white'):
                with ui.menu():
                    ui.menu_item('Manage Sessions', on_click=self.on_manage_sessions)
                    ui.menu_item('Account', on_click=self.on_account_management)
                    ui.separator()
                    ui.menu_item('Logout', on_click=self.on_logout)

        # Target/project name:
        self.parameters['project_name@ui'] = PhoebeParameterWidget(
            qualifier='project_name',
            context='ui',
            label='System/Project Name',
            client=self.client,
            classes='w-full mb-4'
        )

        # Model selection
        self.parameters['backend@ui'] = PhoebeParameterWidget(
            qualifier='backend',
            context='ui',
            label='Computation Backend',
            client=self.client,
            classes='w-full mb-4'
        )

        # Morphology selection
        self.parameters['morphology@ui'] = PhoebeParameterWidget(
            qualifier='morphology',
            context='ui',
            label='Binary star morphology type',
            client=self.client,
            ui_hook=self.on_morphology_changed,
            classes='w-full mb-4'
        )

        # Ephemerides parameters
        with ui.expansion('Ephemerides', icon='schedule', value=False).classes('w-full mb-4'):
            # Create parameter widgets for t0 and period
            self.add_parameter(
                qualifier='t0_supconj',
                component='binary',
                kind='orbit',
                context='component',
                label='T₀ (BJD)',
                step=0.01,
                adjust=False,
                vformat='%.8f',
                sformat='%.3f',
                on_value_changed=self.on_ephemeris_changed
            )

            self.add_parameter(
                qualifier='period',
                component='binary',
                kind='orbit',
                context='component',
                label='Period (d)',
                step=0.0001,
                adjust=False,
                vformat='%.8f',
                sformat='%.3f',
                on_value_changed=self.on_ephemeris_changed
            )

        # Primary star parameters
        with ui.expansion('Primary Star', icon='wb_sunny', value=False).classes('w-full mb-4'):
            self.add_parameter(
                qualifier='mass',
                component='primary',
                kind='star',
                context='component',
                label='Mass (M₀)',
                step=0.01,
                adjust=False,
            )

            self.add_parameter(
                qualifier='requiv',
                component='primary',
                kind='star',
                context='component',
                label='Radius (R₀)',
                step=0.01,
                adjust=False,
            )

            self.add_parameter(
                qualifier='teff',
                component='primary',
                kind='star',
                context='component',
                label='Temperature (K)',
                vformat='%d',
                step=10.0,
                adjust=False,
            )

        # Secondary star parameters
        with ui.expansion('Secondary Star', icon='wb_sunny', value=False).classes('w-full mb-4'):
            self.add_parameter(
                qualifier='mass',
                component='secondary',
                kind='star',
                context='component',
                label='Mass (M₀)',
                step=0.01,
                adjust=False,
            )

            self.add_parameter(
                qualifier='requiv',
                component='secondary',
                kind='star',
                context='component',
                label='Radius (R₀)',
                step=0.01,
                adjust=False,
            )

            self.add_parameter(
                qualifier='teff',
                component='secondary',
                kind='star',
                context='component',
                label='Temperature (K)',
                vformat='%d',
                step=10.0,
                adjust=False,
            )

        # Orbit parameters
        with ui.expansion('Orbit', icon='trip_origin', value=False).classes('w-full mb-4'):
            self.add_parameter(
                qualifier='incl',
                component='binary',
                kind='orbit',
                context='component',
                label='Inclination (°)',
                step=0.1,
                adjust=False,
            )

            self.add_parameter(
                qualifier='ecc',
                component='binary',
                kind='orbit',
                context='component',
                label='Eccentricity',
                step=0.01,
                adjust=False,
            )

            self.add_parameter(
                qualifier='per0',
                component='binary',
                kind='orbit',
                context='component',
                label='Argument of periastron (°)',
                step=1.0,
                adjust=False,
            )

            self.add_parameter(
                qualifier='vgamma',
                context='system',
                label='Systemic velocity (km/s)',
                step=1.0,
                adjust=False
            )

    def create_compute_panel(self):
        with ui.expansion('Model computation', icon='calculate', value=False).classes('w-full'):

            with ui.column().classes('w-full h-full p-4 min-w-0'):
                # Primary star parameters row
                with ui.row().classes('gap-4 items-center w-full mb-3') as self.compute_row_primary:
                    ui.label('Primary star:').classes('w-32 flex-shrink-0 text-sm font-medium')
                    self.parameters['atm@primary'] = PhoebeParameterWidget(
                        qualifier='atm',
                        component='primary',
                        kind='phoebe',
                        context='compute',
                        compute='phoebe01',
                        label='Model atmosphere',
                        client=self.client
                    )

                    self.parameters['ntriangles@primary'] = PhoebeParameterWidget(
                        qualifier='ntriangles',
                        component='primary',
                        kind='phoebe',
                        context='compute',
                        compute='phoebe01',
                        label='Surface elements',
                        format='%d',
                        client=self.client
                    )

                    self.parameters['distortion_method@primary'] = PhoebeParameterWidget(
                        qualifier='distortion_method',
                        component='primary',
                        kind='phoebe',
                        context='compute',
                        compute='phoebe01',
                        label='Distortion',
                        client=self.client
                    )

                # Secondary star parameters row
                with ui.row().classes('gap-4 items-center w-full mb-3') as self.compute_row_secondary:
                    ui.label('Secondary star:').classes('w-32 flex-shrink-0 text-sm font-medium')
                    self.parameters['atm@secondary'] = PhoebeParameterWidget(
                        qualifier='atm',
                        component='secondary',
                        kind='phoebe',
                        context='compute',
                        compute='phoebe01',
                        label='Model atmosphere',
                        client=self.client
                    )

                    self.parameters['ntriangles@secondary'] = PhoebeParameterWidget(
                        qualifier='ntriangles',
                        component='secondary',
                        kind='phoebe',
                        context='compute',
                        compute='phoebe01',
                        label='Surface elements',
                        format='%d',
                        client=self.client
                    )

                    self.parameters['distortion_method@secondary'] = PhoebeParameterWidget(
                        qualifier='distortion_method',
                        component='secondary',
                        kind='phoebe',
                        context='compute',
                        compute='phoebe01',
                        label='Distortion',
                        client=self.client
                    )

                # with ui.row().classes('gap-4 items-center w-full mb-3') as self.compute_row_envelope:
                #     ui.label('Envelope:').classes('w-32 flex-shrink-0 text-sm font-medium')

                #     self.parameters['ntriangles@envelope'] = PhoebeParameterWidget(
                #         twig='ntriangles@envelope',
                #         label='Surface elements',
                #         format='%d',
                #         client=self.phoebe_client
                #     )

                # System parameters and compute button row
                with ui.row().classes('gap-4 items-center w-full'):
                    self.parameters['irrad_method'] = PhoebeParameterWidget(
                        qualifier='irrad_method',
                        kind='phoebe',
                        context='compute',
                        compute='phoebe01',
                        label='Irradiation method',
                        client=self.client
                    )

                    self.parameters['dynamics_method'] = PhoebeParameterWidget(
                        qualifier='dynamics_method',
                        kind='phoebe',
                        context='compute',
                        compute='phoebe01',
                        label='Dynamics method',
                        client=self.client
                    )

                    self.parameters['boosting_method'] = PhoebeParameterWidget(
                        qualifier='boosting_method',
                        kind='phoebe',
                        context='compute',
                        compute='phoebe01',
                        label='Boosting method',
                        client=self.client
                    )

                    self.parameters['ltte'] = PhoebeParameterWidget(
                        qualifier='ltte',
                        kind='phoebe',
                        context='compute',
                        compute='phoebe01',
                        label='Include LTTE',
                        client=self.client
                    )

                    self.compute_button = ui.button(
                        'Compute Model',
                        on_click=self.compute_model,
                        icon='calculate'
                    ).classes('h-12 flex-shrink-0')

    def create_plot_panel(self):
        with ui.expansion('Plotting', icon='insert_chart', value=False).classes('w-full') as plot_expansion:

            with ui.column().classes('w-full h-full p-4 min-w-0'):

                # Plot controls row
                with ui.row().classes('gap-4 items-center mb-4'):
                    # Plot type selector (LC or RV)
                    self.widgets['plot_type'] = ui.select(
                        options={'lc': 'Light Curve', 'rv': 'RV Curve'},
                        value='lc',
                        label='Plot type'
                    ).classes('w-32 h-10')
                    self.widgets['plot_type'].on('update:model-value', self.on_plot_type_changed)

                    # X-axis dropdown
                    self.widgets['plot_x_axis'] = ui.select(
                        options={'time': 'Time', 'phase': 'Phase'},
                        value='time',
                        label='X-axis'
                    ).classes('w-24 h-10')
                    self.widgets['plot_x_axis'].on('update:model-value', lambda: self.on_plot_update())

                    # Y-axis dropdown (only visible for LC plots)
                    self.widgets['plot_y_axis'] = ui.select(
                        options={'magnitude': 'Magnitude', 'flux': 'Flux'},
                        value='flux',
                        label='Y-axis'
                    ).classes('w-24 h-10')
                    self.widgets['plot_y_axis'].on('update:model-value', lambda: self.on_plot_update())

                    # Legend checkbox
                    self.widgets['plot_legend'] = ui.checkbox('Legend', value=False).classes('translate-y-4')
                    self.widgets['plot_legend'].on('update:model-value', lambda: self.on_plot_update())

                    # Plot button, styled for alignment
                    self.plot_button = ui.button('Plot', on_click=self.on_plot_button_clicked).classes('bg-blue-500 h-10 translate-y-4')

                # Containers for plot canvases - created lazily on first expansion open
                self.plot_lc_container = ui.column().classes('w-full min-w-0')
                self.plot_lc_canvas = None
                self.plot_rv_container = ui.column().classes('w-full min-w-0 hidden')
                self.plot_rv_canvas = None

        # Lazily create plots when expansion is first opened
        def on_expansion_open():
            if plot_expansion.value:
                if self.plot_lc_canvas is None:
                    with self.plot_lc_container:
                        self.plot_lc_canvas = ui.plotly(self.create_empty_styled_plot('lc')).classes('w-full min-w-0')
                if self.plot_rv_canvas is None:
                    with self.plot_rv_container:
                        self.plot_rv_canvas = ui.plotly(self.create_empty_styled_plot('rv')).classes('w-full min-w-0')

        plot_expansion.on_value_change(on_expansion_open)

    def create_fitting_panel(self):
        with ui.expansion('Model fitting', icon='tune', value=False).classes('w-full'):

            with ui.column().classes('h-full p-4 min-w-0 w-full'):
                with ui.row().classes('gap-4 items-center w-full'):

                    # Solver selection
                    self.solver_select = ui.select(
                        options={'dc': 'Differential corrections'},
                        value='dc',
                        label='Solver'
                    ).classes('flex-1')

                    self.parameters['deriv_method@solver'] = PhoebeParameterWidget(
                        qualifier='deriv_method',
                        context='solver',
                        kind='differential_corrections',
                        solver='dc',
                        label='Derivatives',
                        options=['symmetric', 'asymmetric'],
                        client=self.client
                    )

                    self.parameters['expose_lnprobabilities@solver'] = PhoebeParameterWidget(
                        qualifier='expose_lnprobabilities',
                        kind='differential_corrections',
                        context='solver',
                        solver='dc',
                        label='Expose ln-probabilities',
                        client=self.client
                    )

                    self.fit_button = ui.button(
                        'Run solver',
                        on_click=self.run_solver,
                        icon='tune'
                    ).classes('h-12 flex-2')

                # Initialize empty table
                self.solution_table = ui.table(
                    columns=[
                        {'name': 'parameter', 'label': 'Adjusted Parameter', 'field': 'parameter', 'align': 'left'},
                        {'name': 'initial', 'label': 'Initial Value', 'field': 'initial', 'align': 'right'},
                        {'name': 'fitted', 'label': 'New Value', 'field': 'fitted', 'align': 'right'},
                        {'name': 'change_percent', 'label': 'Percent Change', 'field': 'change_percent', 'align': 'right'},
                    ],
                    rows=[],
                    row_key='parameter',
                ).classes('w-full').props('no-data-label="No parameters selected for adjustment."')

                # Solution buttons (right-justified)
                with ui.row().classes('w-full justify-end mt-3'):
                    self.preview_solution_button = ui.button(
                        'Preview Solution',
                        icon='visibility',
                        on_click=self.preview_solver_solution
                    ).classes('bg-green-600 text-white px-6 py-2')

                    self.adopt_solution_button = ui.button(
                        'Adopt Solution',
                        icon='check_circle',
                        on_click=self.adopt_solver_solution
                    ).classes('bg-green-600 text-white px-6 py-2')

                    # disable them by default (no solution yet)
                    self.preview_solution_button.props('disabled')
                    self.adopt_solution_button.props('disabled')

    def create_empty_styled_plot(self, plot_type='lc'):
        fig = go.Figure()

        x_title = 'Time (BJD)'
        y_title = 'Flux' if plot_type == 'lc' else 'RV (km/s)'

        fig.update_layout(
            xaxis_title=x_title,
            yaxis_title=y_title,
            hovermode='closest',
            template='plotly_white',
            autosize=True,
            height=400,
            margin=dict(l=50, r=50, t=50, b=50),
            xaxis=dict(
                mirror='allticks',
                ticks='outside',
                showline=True,
                linecolor='black',
                linewidth=2,
                zeroline=False,
                showgrid=True,
                gridcolor='lightgray',
                gridwidth=1,
                griddash='dot'
            ),
            yaxis=dict(
                mirror='allticks',
                ticks='outside',
                showline=True,
                linecolor='black',
                linewidth=2,
                zeroline=False,
                showgrid=True,
                gridcolor='lightgray',
                gridwidth=1,
                griddash='dot'
            ),
            plot_bgcolor='white',
            showlegend=False,
            uirevision=True
        )

        return fig

    def on_plot_type_changed(self):
        """Handle plot type dropdown change - toggle canvas visibility and y-axis options."""
        plot_type = self.widgets['plot_type'].value

        if plot_type == 'lc':
            # Show LC canvas, hide RV canvas
            self.plot_lc_container.classes(remove='hidden')
            self.plot_rv_container.classes(add='hidden')
            # Update y-axis options for LC
            self.widgets['plot_y_axis'].options = {'magnitude': 'Magnitude', 'flux': 'Flux'}
            self.widgets['plot_y_axis'].value = 'flux'
        else:
            # Show RV canvas, hide LC canvas
            self.plot_rv_container.classes(remove='hidden')
            self.plot_lc_container.classes(add='hidden')
            # Update y-axis options for RV
            self.widgets['plot_y_axis'].options = {'rv': 'RV (km/s)'}
            self.widgets['plot_y_axis'].value = 'rv'

    def on_plot_update(self):
        # Handle updates to the plot settings (called on dropdown/checkbox changes)
        pass

    def create_figure(self, plot_type='lc', preview_model_data: dict | None = None):
        """
        Create a figure with current data and model for the specified plot type.

        Args:
            plot_type: 'lc' for light curve, 'rv' for radial velocity
            preview_model_data: Optional dict of model data for preview mode.
                               If provided, uses this data instead of stored model data.
                               Format: {ds_label: {'fluxes': [...], ...}, ...}

        Returns:
            Plotly Figure object
        """
        fig = self.create_empty_styled_plot(plot_type)

        # Update axis labels based on dropdown selections
        x_axis = self.widgets['plot_x_axis'].value

        if plot_type == 'lc':
            y_axis = self.widgets['plot_y_axis'].value
            x_title = 'Phase' if x_axis == 'phase' else 'Time (BJD)'
            y_title = 'Magnitude' if y_axis == 'magnitude' else 'Flux'
        else:  # rv
            y_axis = 'rv'
            x_title = 'Phase' if x_axis == 'phase' else 'Time (BJD)'
            y_title = 'RV (km/s)'

        # Update layout with correct axis titles and y-axis direction for magnitude
        layout_updates = {
            'xaxis_title': x_title,
            'yaxis_title': y_title,
            'showlegend': self.widgets['plot_legend'].value
        }
        if plot_type == 'lc' and y_axis == 'magnitude':
            layout_updates['yaxis_autorange'] = 'reversed'

        fig.update_layout(**layout_updates)

        period = self.parameters['period@binary@orbit@component'].get_value()
        t0 = self.parameters['t0_supconj@binary@orbit@component'].get_value()

        # Filter datasets by plot type and plot them
        dataset_index = 0
        for ds_label, ds_meta in self.dataset.datasets.items():
            # Only plot datasets matching the current plot type
            if ds_meta['kind'] != plot_type:
                continue

            # Get color scheme for this dataset
            color_idx = dataset_index % len(DATASET_COLORS)
            cycle_idx = dataset_index // len(DATASET_COLORS)
            colors = DATASET_COLORS[color_idx]
            marker_symbol = MARKER_SYMBOLS[cycle_idx % len(MARKER_SYMBOLS)]
            line_dash = LINE_DASHES[cycle_idx % len(LINE_DASHES)]

            if ds_meta['plot_data']:
                if x_axis == 'time':
                    xs = ds_meta['times']
                else:
                    xs = time_to_phase(ds_meta['times'], period, t0)

                # Get y-values based on dataset type
                if plot_type == 'lc':
                    if y_axis == 'flux':
                        ys = ds_meta['fluxes']
                    else:
                        ys = flux_to_magnitude(ds_meta['fluxes'])
                else:  # rv
                    component = ds_meta.get('component')
                    if component == 'primary':
                        ys = ds_meta['rvs']
                    else:
                        ys = ds_meta['rvs']

                if len(xs) == 0 or len(ys) == 0:
                    continue

                data = np.column_stack((xs, ys))

                # Alias phases:
                if x_axis == 'phase':
                    data = alias_data(data, extend_range=0.1)

                fig.add_trace(go.Scatter(
                    x=data[:, 0],
                    y=data[:, 1],
                    mode='markers',
                    marker={'color': colors['data'], 'symbol': marker_symbol},
                    name=ds_label
                ))

            if ds_meta['plot_model']:
                # Get model data based on dataset type
                if plot_type == 'lc':
                    if preview_model_data is not None and ds_label in preview_model_data:
                        model_ys = np.array(preview_model_data[ds_label].get('fluxes', []))
                    else:
                        model_ys = np.array(ds_meta['model_fluxes'])
                else:  # rv
                    component = ds_meta.get('component')
                    if preview_model_data is not None and ds_label in preview_model_data:
                        if component == 'primary':
                            model_ys = np.array(preview_model_data[ds_label].get('rvs', []))
                        else:
                            model_ys = np.array(preview_model_data[ds_label].get('rvs', []))
                    else:
                        if component == 'primary':
                            model_ys = np.array(ds_meta['model_rvs'])
                        else:
                            model_ys = np.array(ds_meta['model_rvs'])

                if len(model_ys) == 0:
                    kind_label = 'fluxes' if plot_type == 'lc' else 'RVs'
                    ui.notify(f'No model {kind_label} available for dataset {ds_label}. Please compute the model first.', type='warning')
                    continue

                # Generate phase grid matching model data length
                n_model_points = len(model_ys)
                compute_phases = np.linspace(ds_meta['phase_min'], ds_meta['phase_max'], n_model_points)

                # Apply magnitude conversion for LC if needed
                if plot_type == 'lc' and y_axis == 'magnitude':
                    ys = flux_to_magnitude(model_ys)
                else:
                    ys = model_ys

                if x_axis == 'time':
                    # Tile model across full time span of data
                    if ds_meta['plot_data'] and len(ds_meta['times']) > 0:
                        t_min = np.min(ds_meta['times'])
                        t_max = np.max(ds_meta['times'])
                        # Calculate which cycles we need to cover
                        cycle_min = int(np.floor((t_min - t0) / period))
                        cycle_max = int(np.ceil((t_max - t0) / period))
                        # Build tiled model
                        all_xs = []
                        all_ys = []
                        for cycle in range(cycle_min, cycle_max + 1):
                            cycle_times = t0 + period * (compute_phases + cycle)
                            all_xs.extend(cycle_times)
                            all_ys.extend(ys)
                        xs = np.array(all_xs)
                        ys = np.array(all_ys)
                        # Trim to exact data time range
                        mask = (xs >= t_min) & (xs <= t_max)
                        xs = xs[mask]
                        ys = ys[mask]
                    else:
                        xs = t0 + period * compute_phases
                else:
                    xs = compute_phases

                model = np.column_stack((xs, ys))

                if x_axis == 'phase':
                    model = alias_data(model, extend_range=0.1)

                fig.add_trace(go.Scatter(
                    x=model[:, 0],
                    y=model[:, 1],
                    mode='lines',
                    line={'color': colors['model'], 'dash': line_dash},
                    name=ds_label
                ))

            dataset_index += 1

        return fig

    async def on_plot_button_clicked(self):
        """Redraw the current plot with data and model."""
        plot_type = self.widgets.get('plot_type', None)
        if plot_type is not None:
            plot_type = plot_type.value
        else:
            plot_type = 'lc'  # Default to LC if not yet initialized

        canvas = self.plot_lc_canvas if plot_type == 'lc' else self.plot_rv_canvas
        if canvas is None:
            return

        try:
            # Show button loading indicator
            self.plot_button.props('loading')

            # Run the plotting operation asynchronously to avoid blocking the UI with large datasets
            fig = await run.io_bound(self.create_figure, plot_type)

            canvas.figure = fig
            canvas.update()
        except Exception as e:
            ui.notify(f"Error plotting data: {str(e)}", type='negative')
        finally:
            # Remove button loading indicator
            self.plot_button.props(remove='loading')

    def create_analysis_panel(self):
        with ui.column().classes('w-full h-full p-4 min-w-0'):
            # Dataset management panel:
            self.dataset.mount_panel()

            # Compute management panel:
            self.create_compute_panel()

            # Plotting panel (LC and RV)
            self.create_plot_panel()

            # Fitting panel:
            self.create_fitting_panel()

    async def on_ephemeris_changed(self, param_name=None, param_value=None):
        """Handle changes to ephemeris parameters (t0, period) and update phase plot."""
        # Only replot if we're currently showing phase on x-axis or if there's any data to plot
        if self.widgets['plot_x_axis'].value == 'phase' or any(
            ds_meta.get('plot_data', False) or ds_meta.get('plot_model', False)
            for ds_meta in self.dataset.datasets.values()
        ):
            await self.on_plot_button_clicked()

    async def sync_ui_state(self, **kwargs):
        """Syncs UI state with PHOEBE server."""
        if not self.client:
            return

        pset = kwargs.get('pset', None)

        if pset is not None:
            # For each UI parameter, find matching param in pset by tag comparison
            for param_widget in self.parameters.values():
                param = next((p for p in pset
                              if p.get('qualifier') == param_widget.qualifier
                              and p.get('context') == param_widget.context
                              and p.get('component') == param_widget.component
                              and p.get('dataset') == param_widget.dataset
                              and p.get('kind') == param_widget.kind), None)

                if param:
                    # update uniqueid and value from pset:
                    param_widget.uniqueid = param.get('uniqueid')

                    # update value:
                    value = param.get('value')
                    if value is not None:
                        param_widget.set_value(value)
                else:
                    raise ValueError(f'Parameter {param_widget.twig} not found in provided pset')

            # sync datasets from pset:
            self.dataset.sync_from_pset(pset=pset)
        else:
            self.dataset.sync_from_server()

        self.dataset.refresh()

    def filter(self, pset, qualifier=None, context=None, component=None, dataset=None, kind=None, uniqueid=None):
        # this mimics PHOEBE's filter() ParameterSet method.
        filtered_pset = []

        for par in pset:
            if qualifier and par.get('qualifier', None) and qualifier != par.get('qualifier'):
                continue
            if context and par.get('context', None) and context != par.get('context', None):
                continue
            if component and par.get('component', None) and component != par.get('component', None):
                continue
            if dataset and par.get('dataset', None) and dataset != par.get('dataset', None):
                continue
            if kind and par.get('kind', None) and kind != par.get('kind', None):
                continue
            if uniqueid and par.get('uniqueid', None) and uniqueid != par.get('uniqueid', None):
                continue

            filtered_pset.append(par)

        if len(filtered_pset) == 1:
            return filtered_pset[0]

        raise ValueError(f'{len(filtered_pset)} parameters found with matching tags: {filtered_pset}.')

    async def on_morphology_changed(self, new_morphology):
        print('entered on_morphology_changed')
        self.client.set_morphology(morphology=new_morphology)

        # preserve project name and backend:
        project_name = self.parameters['project_name@ui'].get_value()
        backend = self.parameters['backend@ui'].get_value()
        # TODO: do we want to preserve other UI parameters?
        attach_ui_parameters(self.client, project_name=project_name, backend=backend, morphology=new_morphology)

        # get the new bundle from the server:
        response = self.client.get_bundle()
        if response.get('success', False):
            pset = json.loads(response['result'].get('bundle'))
            # FIXME: UI parameters are doubled!
        else:
            raise RuntimeError('failed to fetch the new bundle from the server.')

        # iterate over UI parameters and update their uniqueids:
        for widget in self.parameters.values():
            match = self.filter(
                pset,
                qualifier=widget.qualifier,
                context=widget.context,
                component=widget.component,
                dataset=widget.dataset,
                kind=widget.kind
            )

            # no need to check if match succeeded, filter() does that already.
            widget.uniqueid = match.get('uniqueid')

            # display or hide widgets based on parameter constraint:
            response = self.client.is_parameter_constrained(uniqueid=widget.uniqueid)
            if response['success']:
                constrained = response['result']
                widget.set_visible(not constrained)
                # if constrained:
                #     print(f'parameter {par.twig} hidden.')
            else:
                raise RuntimeError(f"Failed to check if parameter {widget.twig} is constrained")

            # reset values to bundle defaults:
            if not constrained:
                widget.set_value(match.get('value'))

        print(f'Morphology changed to {new_morphology.lower()}')

        # Readd all datasets:
        self.dataset.readd_all()

    async def compute_model(self):
        """Compute Phoebe model with current parameters."""
        try:
            # Show button loading indicator
            self.compute_button.props('loading')

            # Run the compute operation asynchronously to avoid blocking the UI
            response = await run.io_bound(self.client.run_compute)

            if response.get('success', False):
                model_data = response['result'].get('model', {})

                for ds_label, ds_meta in self.dataset.datasets.items():
                    # For RV datasets, the backend returns data keyed by the original dataset name
                    backend_ds_label = ds_meta.get('dataset', ds_label)

                    if backend_ds_label in model_data:
                        ds_data = model_data[backend_ds_label]
                        if ds_meta['kind'] == 'lc':
                            ds_meta['model_fluxes'] = ds_data.get('fluxes', [])
                        elif ds_meta['kind'] == 'rv':
                            component = ds_meta.get('component')
                            if component == 'primary':
                                ds_meta['model_rvs'] = ds_data.get('rvs_primary', [])
                            else:
                                ds_meta['model_rvs'] = ds_data.get('rvs_secondary', [])
                        else:
                            ui.notify(f"Unknown dataset kind '{ds_meta['kind']}' for dataset '{ds_label}'", type='warning')
                    else:
                        if ds_meta['kind'] == 'lc':
                            ds_meta['model_fluxes'] = []
                        elif ds_meta['kind'] == 'rv':
                            ds_meta['model_rvs'] = []
                        else:
                            ui.notify(f"Unknown dataset kind '{ds_meta['kind']}' for dataset '{ds_label}'", type='warning')

                ui.notify('Model computed successfully!', type='positive')
            else:
                ui.notify(f"Model computation failed: {response.get('error', 'Unknown error')}", type='negative')

        except Exception as e:
            ui.notify(f"Error computing model: {str(e)}", type='negative')
        finally:
            # Remove button loading indicator
            self.compute_button.props(remove='loading')

    async def run_solver(self):
        fit_parameters = [twig for twig, parameter in self.parameters.items() if hasattr(parameter, 'adjust') and parameter.adjust]
        if not fit_parameters:
            ui.notify('No parameters selected for fitting', type='warning')
            return

        steps = [self.parameters[twig].step for twig in fit_parameters]

        self.client.set_value(twig='fit_parameters@solver', value=fit_parameters)
        self.client.set_value(twig='steps@solver', value=steps)

        try:
            # Show button loading indicator
            self.fit_button.props('loading')

            # Run the compute operation asynchronously to avoid blocking the UI
            response = await run.io_bound(self.client.run_solver)

            if response.get('success', False):
                solution_data = response.get('result', {}).get('solution', {})

                # Update the solver results table
                self.update_solution_table(solution_data)

                # Enable solution buttons:
                self.preview_solution_button.props(remove='disabled')
                self.adopt_solution_button.props(remove='disabled')

                ui.notify("Model fitting succeeded", type='positive')
            else:
                ui.notify(f"Model fitting failed: {response.get('error', 'Unknown error')}", type='negative')

        except Exception as e:
            ui.notify(f"Error fitting parameters: {str(e)}", type='negative')
        finally:
            # Remove button loading indicator
            self.fit_button.props(remove='loading')

    def update_solution_table(self, solution_data):
        """Update the solver results table with the fitting results."""

        # Extract solution data
        fit_parameters = solution_data.get('fit_parameters')
        initial_values = solution_data.get('initial_values')
        fitted_values = solution_data.get('fitted_values')

        # Prepare table data
        table_data = []
        for i, param in enumerate(fit_parameters):
            initial_val = initial_values[i]
            fitted_val = fitted_values[i]

            # Calculate percentage change
            if initial_val != 0:
                percent_change = ((fitted_val - initial_val) / initial_val) * 100
                percent_change_str = f'{percent_change:+.2f}%'
            else:
                percent_change_str = 'N/A'

            table_data.append({
                'parameter': param,
                'initial': f'{initial_val:.6f}',
                'fitted': f'{fitted_val:.6f}',
                'change_percent': percent_change_str
            })

        # Update the table
        self.solution_table.rows = table_data
        self.solution_table.update()

    def add_parameter_to_solver_table(self, par):
        rows = list(self.solution_table.rows)
        twig = par.get_twig()

        # only add a parameter if it's not already in the table:
        if not any(row['parameter'] == twig for row in rows):
            row_data = {
                'parameter': twig,
                'initial': par.get_value(),
                'fitted': 'n/a',
                'change_percent': 'n/a'
            }

            rows.append(row_data)
            self.solution_table.rows = rows
            self.solution_table.update()

    def remove_parameter_from_solver_table(self, par):
        twig = par.get_twig()
        rows = [row for row in self.solution_table.rows if row['parameter'] != twig]
        self.solution_table.rows = rows
        self.solution_table.update()

    def update_parameters_in_solver_table(self):
        rows = list(self.solution_table.rows)

        for i, row in enumerate(rows):
            par = self.parameters[row['parameter']]
            rows[i]['initial'] = par.get_value()
            rows[i]['fitted'] = 'n/a'
            rows[i]['change_percent'] = 'n/a'

        self.solution_table.rows = rows
        self.solution_table.update()

    async def preview_solver_solution(self):
        """
        Preview the solver solution by showing a side-by-side comparison dialog.

        Shows "Before" (current model) and "After" (model with fitted parameters)
        plots so user can compare and decide whether to adopt the solution.
        """
        try:
            # Show loading indicator on preview button
            self.preview_solution_button.props('loading')

            # Compute model with solution='latest' to get preview
            response = await run.io_bound(self.client.run_compute, solution='latest')

            if not response.get('success', False):
                ui.notify(f"Failed to compute preview: {response.get('error', 'Unknown error')}", type='negative')
                return

            preview_model_data = response['result'].get('model', {})

            # Create the preview dialog
            with ui.dialog() as preview_dialog, ui.card().classes('w-[1200px] max-w-[95vw]'):
                ui.label('Solution Preview').classes('text-xl font-bold mb-4')
                ui.label('Compare the current model (Before) with the fitted solution (After)').classes('text-gray-600 mb-4')

                # Side-by-side plots
                with ui.row().classes('w-full gap-4'):
                    # Before plot (current model)
                    with ui.column().classes('flex-1'):
                        ui.label('Before (Current Parameters)').classes('text-lg font-semibold mb-2 text-center')
                        before_fig = self.create_figure('lc')
                        before_fig.update_layout(height=350, title=None)
                        ui.plotly(before_fig).classes('w-full')

                    # After plot (preview with fitted parameters)
                    with ui.column().classes('flex-1'):
                        ui.label('After (Fitted Parameters)').classes('text-lg font-semibold mb-2 text-center')
                        after_fig = self.create_figure('lc', preview_model_data=preview_model_data)
                        after_fig.update_layout(height=350, title=None)
                        ui.plotly(after_fig).classes('w-full')

                # Parameter changes table
                ui.separator().classes('my-4')
                ui.label('Parameter Changes:').classes('font-semibold')
                with ui.row().classes('w-full'):
                    ui.table(
                        columns=[
                            {'name': 'parameter', 'label': 'Parameter', 'field': 'parameter', 'align': 'left'},
                            {'name': 'initial', 'label': 'Current', 'field': 'initial', 'align': 'right'},
                            {'name': 'fitted', 'label': 'Fitted', 'field': 'fitted', 'align': 'right'},
                            {'name': 'change_percent', 'label': 'Change', 'field': 'change_percent', 'align': 'right'},
                        ],
                        rows=list(self.solution_table.rows),
                        row_key='parameter',
                    ).classes('w-full')

                # Dialog buttons
                ui.separator().classes('my-4')
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('Close', on_click=preview_dialog.close).props('flat')
                    ui.button(
                        'Adopt Solution',
                        icon='check_circle',
                        on_click=lambda: self._adopt_and_close(preview_dialog)
                    ).classes('bg-green-600 text-white')

            preview_dialog.open()

        except Exception as e:
            ui.notify(f'Error previewing solution: {str(e)}', type='negative')
        finally:
            self.preview_solution_button.props(remove='loading')

    def _adopt_and_close(self, dialog):
        """Helper to adopt solution and close the preview dialog."""
        self.adopt_solver_solution()
        dialog.close()
        ui.notify('Solution adopted successfully', type='positive')

    def adopt_solver_solution(self):
        """Adopt the solver solution by setting fitted values to current parameters."""
        try:
            # Get all rows from the solution table
            for row in self.solution_table.rows:
                twig = row['parameter']
                fitted_value = row.get('fitted', 'n/a')

                # Skip if no fitted value available
                if fitted_value == 'n/a' or fitted_value is None:
                    continue

                # Set the parameter value
                param_widget = self.parameters[twig]
                param_widget.set_value(fitted_value)
                param_widget.on_value_changed(event=False)

            # Update the solution table to reflect the adopted values
            self.update_parameters_in_solver_table()

            # Clear model data since parameters have changed
            for ds_label, ds_meta in self.dataset.datasets.items():
                if ds_meta['kind'] == 'lc':
                    ds_meta['model_fluxes'] = []
                else:
                    ds_meta['model_rvs'] = []

            # Disable adopt solution button:
            self.preview_solution_button.props('disabled')
            self.adopt_solution_button.props('disabled')
        except Exception as e:
            ui.notify(f'Error adopting solver solution: {str(e)}', type='negative')

    async def on_new_model(self):
        """Create a new model after confirming with the user."""
        # Create a dialog to warn about unsaved changes
        with ui.dialog() as dialog, ui.card():
            ui.label('New Model').classes('text-h6')
            ui.label('Warning: Creating a new model will discard any unsaved changes to the current model.').classes('text-orange-600 mb-4')

            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                ui.button('Create New Model', on_click=lambda e: self.create_new_model(dialog)).classes('bg-red-600 text-white')

        dialog.open()

    async def create_new_model(self, dialog):
        """Create a new model in the backend and sync UI."""
        try:
            # Show loading indicator
            self.new_button.props('loading')

            response = await run.io_bound(self.client.new_bundle)

            if response.get('success', False):
                ui.notify('New model created successfully', type='positive')
                dialog.close()

                # Sync UI state with the new model
                await self.sync_ui_state()
            else:
                ui.notify(f"Failed to create new model: {response.get('error', 'Unknown error')}", type='negative')

        except Exception as e:
            ui.notify(f'Error creating new model: {str(e)}', type='negative')

        finally:
            self.new_button.props(remove='loading')

    async def on_load_model(self):
        """Load model from file with browser upload and confirmation dialog."""
        # Create a dialog to warn about unsaved changes and upload file

        with ui.dialog() as dialog, ui.card():
            ui.label('Load Model').classes('text-h6')
            ui.label('Warning: Loading a bundle will discard any unsaved changes to the current model.').classes('text-orange-600 mb-4')

            # File upload widget for selecting bundle file
            ui.upload(
                label='Select a phoebe model to upload',
                on_upload=lambda e: self.load_bundle_from_upload(e, dialog),
                auto_upload=True
            ).classes('w-full mb-4')

            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat')

        dialog.open()

    async def load_bundle_from_upload(self, event, dialog):
        """Load the bundle file from uploaded content."""
        try:
            # Show loading indicator
            self.load_button.props('loading')

            # Get the uploaded file content
            if event and event.file and event.file._data:
                filename = event.file.name
                file_content = await event.file.text()
            else:
                ui.notify('Bundle upload failed', type='negative')
                return

            response = await run.io_bound(self.client.load_bundle, bundle=file_content)

            if response.get('success', False):
                ui.notify(f'Bundle loaded from {filename}', type='positive')
                dialog.close()

                # Sync UI state with the loaded model
                await self.sync_ui_state(pset=json.loads(file_content))
            else:
                ui.notify(f"Failed to load bundle: {response.get('error', 'Unknown error')}", type='negative')

        except Exception as e:
            ui.notify(f'Error loading bundle: {str(e)}', type='negative')

        finally:
            self.load_button.props(remove='loading')

    async def on_save_model(self):
        """Save model and trigger browser download."""
        try:
            # Show loading indicator
            self.save_button.props('loading')

            # Get bundle content:
            response = await run.io_bound(self.client.save_bundle)

            if response.get('success', False):
                # Get the bundle content from the response (may be wrapped in 'result')
                result = response.get('result', response)
                bundle = result.get('bundle', '')

                if bundle:
                    # Trigger browser download
                    ui.download(bundle.encode('utf-8'), 'bundle.phoebe')
                    ui.notify('Bundle downloaded successfully', type='positive')
                else:
                    ui.notify('Bundle content is empty', type='warning')
            else:
                ui.notify(f"Failed to save bundle: {response.get('error', 'Unknown error')}", type='negative')

        except Exception as e:
            ui.notify(f'Error saving bundle: {str(e)}', type='negative')

        finally:
            self.save_button.props(remove='loading')

    def on_manage_sessions(self):
        """Open session manager dialog to switch or manage sessions."""
        self.context_data['session_dialog'].show()

    def on_account_management(self):
        """Open account management dialog for profile and password changes."""
        with ui.dialog() as account_dialog, ui.card().classes('w-[500px]'):
            ui.label('Account Management').classes('text-2xl font-bold mb-4')

            # Display user information
            with ui.card().classes('w-full bg-gray-50 p-4 mb-4'):
                ui.label('Current Account').classes('text-lg font-semibold mb-3')
                user_info = self.get_user_info()
                if self.session_info.full_name:
                    ui.label(f"Name: {self.session_info.full_name}").classes('text-sm')
                if hasattr(self.session_info, 'email'):
                    ui.label(f"Email: {self.session_info.email}").classes('text-sm')

            # Password change section (for future implementation)
            with ui.expansion('Change Password', icon='lock').classes('w-full'):
                ui.label('Password change coming soon...').classes('text-gray-600 text-sm')

            # Dialog action buttons
            ui.separator().classes('my-4')
            with ui.row().classes('w-full gap-2 justify-end'):
                ui.button('Close', on_click=account_dialog.close).props('flat')

        account_dialog.open()

    def on_logout(self):
        """Handle user logout - confirm and then clear session."""
        with ui.dialog() as confirm_dialog, ui.card():
            ui.label('Logout?').classes('text-lg font-bold mb-2')
            ui.label('You will be logged out and returned to the login screen.').classes('text-gray-600 mb-4')

            with ui.row().classes('w-full gap-2 justify-end mt-4'):
                ui.button('Cancel', on_click=confirm_dialog.close).props('flat')
                ui.button('Logout', on_click=lambda: self._perform_logout(confirm_dialog)).classes('bg-red-600 text-white')

        confirm_dialog.open()

    def _perform_logout(self, dialog):
        """Actually perform the logout - clear token and redirect to login."""
        dialog.close()
        
        # Clear the JWT token from browser storage
        if 'phoebe_token' in app.storage.user:
            app.storage.user.pop('phoebe_token')
        
        # End the current session on the server
        try:
            if self.session_info.session_id:
                self.client.end_session(self.session_info.session_id)
        except Exception as e:
            print(f'Warning: Could not end session on server: {e}')
        
        # Navigate back to login page
        ui.navigate.to('/')
        ui.notify('You have been logged out.', type='info')

    def get_user_info(self):
        """Get user information for logging or display purposes."""
        return self.session_info.full_name or "Unknown User"

    def get_session_info(self):
        """Get session information for logging or display purposes."""
        return {
            'session_id': self.session_info.session_id,
            'user_name': self.session_info.full_name,
            'session_active': not self.session_info.is_new_session
        }


def attach_ui_parameters(phoebe_client: PhoebeClient, project_name=None, backend=None, morphology=None, phase_min=None, phase_max=None, phase_length=None, rv_component=None):
    parameters = [
        {
            'ptype': 'string',
            'qualifier': 'project_name',
            'value': project_name or 'Unnamed Project',
            'description': 'Name of the binary system / project',
            'context': 'ui'
        },
        {
            'ptype': 'choice',
            'qualifier': 'backend',
            'value': backend or 'PHOEBE',
            'choices': ['PHOEBE', 'PHOEBAI'],
            'description': 'Computation backend',
            'context': 'ui'
        },
        {
            'ptype': 'choice',
            'qualifier': 'morphology',
            'value': morphology or 'Detached',
            'choices': ['Detached', 'Semi-detached', 'Contact'],
            'description': 'Morphology of the binary system',
            'context': 'ui',
            'component': 'binary'
        },
        {
            'ptype': 'float',
            'qualifier': 'phase_min',
            'value': phase_min or -0.5,
            'description': 'Starting phase for light curve plots',
            'context': 'ui',
            'copy_for': {'kind': ['lc', 'rv'], 'dataset': '*'},
            'dataset': '_default'
        },
        {
            'ptype': 'float',
            'qualifier': 'phase_max',
            'value': phase_max or 0.5,
            'description': 'Ending phase for light curve plots',
            'context': 'ui',
            'copy_for': {'kind': ['lc', 'rv'], 'dataset': '*'},
            'dataset': '_default'
        },
        {
            'ptype': 'int',
            'qualifier': 'phase_length',
            'value': phase_length or 201,
            'description': 'Number of phase points for light curve plots',
            'context': 'ui',
            'copy_for': {'kind': ['lc', 'rv'], 'dataset': '*'},
            'dataset': '_default'
        },
        {
            'ptype': 'choice',
            'qualifier': 'rv_component',
            'value': rv_component or 'primary',
            'choices': ['primary', 'secondary'],
            'description': 'Component for radial velocity datasets',
            'context': 'ui',
            'copy_for': {'kind': ['rv'], 'dataset': '*'},
            'dataset': '_default'
        }
    ]
    phoebe_client.attach_parameters(parameters=parameters)


@ui.page('/')
def main_page():
    """Main page for the Phoebe Lab UI with auth-mode-aware session management."""

    # Initialize phoebe API client
    client = PhoebeClient(host=CONFIG.server.host, port=CONFIG.server.port)

    main_window = ui.column().classes('w-full h-full items-center justify-start p-4 gap-4')

    # Discover server auth mode
    try:
        auth_config = client.get_auth_config()
    except Exception:
        auth_config = {"mode": "none"}

    auth_mode = auth_config.get("mode", "none")

    async def on_session_activated(session_info: SessionInfo, context_data: dict):
        """Handle session activation (new or reconnected) and create main UI."""

        if session_info.is_new_session:
            # no existing session -- start a new one:
            response = await run.io_bound(client.start_session, metadata=session_info.to_dict())

            # Update session_info with server response (session_id, etc.)
            session_info.update(response)

            await run.io_bound(attach_ui_parameters, client)

            # Set project name parameter value
            await run.io_bound(client.set_value, twig='project_name@ui', value=session_info.project_name)
        else:
            # Reconnecting to existing session - sync from server
            sessions = await run.io_bound(client.get_sessions)
            if session_info.session_id in sessions:
                server_data = sessions[session_info.session_id]
                session_info.update(server_data)

        # Update session dialog with current session
        session_dialog = context_data['session_dialog']
        session_dialog.current_session_id = session_info.session_id
        await session_dialog.refresh()

        # Create main UI
        main_window.clear()

        with main_window:
            PhoebeUI(
                phoebe_client=client,
                session_info=session_info,
                context_data=context_data
            )

    # Will be set to the JWT auth login dialog when auth_mode == "jwt",
    # so that session dialogs can offer a logout-to-login option.
    jwt_auth_login = None

    def build_session_dialogs():
        """Build session dialogs and show the appropriate one."""
        sessions = client.get_sessions()

        login_dialog = StartSessionDialog(
            client=client,
            sessions=sessions,
            on_session_activated=on_session_activated
        )

        session_dialog = SessionManagerDialog(
            client=client,
            sessions=sessions,
            current_session_id=None,
            on_session_activated=on_session_activated
        )

        context_data = {
            'session_dialog': session_dialog,
            'login_dialog': login_dialog,
        }

        # If JWT mode, include the auth login dialog so logout can return to it
        if jwt_auth_login is not None:
            context_data['auth_login'] = jwt_auth_login

        login_dialog.attach_context_data(context_data)
        session_dialog.attach_context_data(context_data)

        # Route to appropriate dialog based on existing sessions
        if sessions:
            session_dialog.show()
        else:
            login_dialog.show()

    if auth_mode == "jwt":
        # Server-managed users: show login/register before session flow
        auth_login = AuthLoginDialog(client=client, on_authenticated=None)
        auth_register = AuthRegisterDialog(client=client, on_authenticated=None)

        # Make auth_login available to build_session_dialogs for logout support
        jwt_auth_login = auth_login

        async def on_authenticated():
            """Called after successful JWT login/register. Build and show session dialogs."""
            try:
                build_session_dialogs()
            except Exception as e:
                ui.notify(f'Error after authentication: {str(e)}', type='negative')
                print(f'Error in on_authenticated: {e}')

        # Update dialog callbacks now that on_authenticated is defined
        auth_login.on_authenticated = on_authenticated
        auth_register.on_authenticated = on_authenticated

        auth_context = {
            'login_dialog': auth_login,
            'register_dialog': auth_register,
        }
        auth_login.attach_context_data(auth_context)
        auth_register.attach_context_data(auth_context)

        # Check for existing token in browser storage
        stored_token = app.storage.user.get('phoebe_token')
        if stored_token:
            client.set_token(stored_token)
            try:
                client.get_me()  # validate token still works
                build_session_dialogs()
            except Exception:
                ui.notify('Session token expired. Please log in again.', type='warning')
                app.storage.user.pop('phoebe_token', None)
                auth_login.show()
        else:
            auth_login.show()

    elif auth_mode == "password":
        # Simple password gate at the lab level
        # Build session dialogs first, then wrap the entry point with PasswordProtected
        sessions = client.get_sessions()

        login_dialog = StartSessionDialog(
            client=client,
            sessions=sessions,
            on_session_activated=on_session_activated
        )

        session_dialog = SessionManagerDialog(
            client=client,
            sessions=sessions,
            current_session_id=None,
            on_session_activated=on_session_activated
        )

        context_data = {
            'session_dialog': session_dialog,
            'login_dialog': login_dialog,
        }

        login_dialog.attach_context_data(context_data)
        session_dialog.attach_context_data(context_data)

        # Determine which dialog to show (entry point)
        entry_dialog = session_dialog if sessions else login_dialog

        # Wrap with password gate
        guarded = PasswordProtected(
            guarded_dialog=entry_dialog,
            password=CONFIG.ui.access_password,
            guard_enabled=bool(CONFIG.ui.access_password),
        )
        guarded.show()

    elif auth_mode == "external":
        # External JWT: expect token in browser storage (set by upstream)
        stored_token = app.storage.user.get('phoebe_token')
        if stored_token:
            client.set_token(stored_token)
        build_session_dialogs()

    else:
        # "none" mode: no auth needed
        build_session_dialogs()


def main():
    """Main entry point for phoebe-lab service."""
    ui.run(
        host=CONFIG.ui.host,
        port=CONFIG.ui.port,
        title=CONFIG.ui.title,
        reload=False,
        reconnect_timeout=CONFIG.ui.reconnect_timeout,
        storage_secret=CONFIG.ui.storage_secret
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
