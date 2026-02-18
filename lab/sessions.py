from dataclasses import dataclass, asdict, fields
from functools import partial
from nicegui import ui, app, run


@dataclass
class SessionInfo:
    """
    Passive server session state. Server is the single source of truth.
    """

    session_id: str | None = None
    user_id: str | None = None
    full_name: str = ""
    project_name: str = "Unnamed Project"
    created_at: float | None = None
    last_activity: float | None = None
    mem_used: float | None = None
    port: int | None = None

    @property
    def is_new_session(self) -> bool:
        return self.session_id is None

    def update(self, data: dict) -> None:
        """
        Update session info from dict (typically from server).

        Args:
            data: Dictionary with fields to update (from server)
        """
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)

    @classmethod
    def from_dict(cls, data: dict) -> 'SessionInfo':
        """
        Create SessionInfo from dictionary (from server, storage, or manual construction).

        Args:
            data: Dictionary with session fields

        Returns:
            New SessionInfo instance

        Examples:
            # From server response
            session_info = SessionInfo.from_dict(client.get_session(session_id))

            # From manual dict
            session_info = SessionInfo.from_dict({
                'first_name': 'Alice',
                'last_name': 'Smith',
                'email': 'alice@example.com',
                'project_name': 'My System'
            })
        """
        # Only use keys that are actual SessionInfo fields
        valid_fields = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)

    @classmethod
    def from_server(cls, client, session_id: str) -> 'SessionInfo':
        """
        Fetch session from server and create SessionInfo.

        Args:
            client: PhoebeClient instance
            session_id: Session ID to fetch

        Returns:
            New SessionInfo instance with data from server

        Example:
            session_info = SessionInfo.from_server(client, 'abc123')
        """
        server_data = client.get_session(session_id)
        return cls.from_dict(server_data)

    def to_dict(self, exclude_none: bool = True) -> dict:
        """
        Convert to dict for server calls.

        Args:
            exclude_none: If True, exclude fields with None values

        Returns:
            Dictionary representation
        """
        result = asdict(self)
        if exclude_none:
            result = {k: v for k, v in result.items() if v is not None}
        return result


class PhoebeDialog:
    """Base class for all PHOEBE dialogs with reusable blocks."""

    def __init__(self, persistent=False, context_data: dict = {}):
        """Initialize the base dialog structure."""
        self.dialog = ui.dialog()
        if persistent:
            self.dialog.props('persistent')
        self.card = None
        self.title_block = None
        self.content_block = None
        self.buttons_block = None

        ui.add_css('/static/styles.css')

    def attach_context_data(self, context_data: dict):
        """Attach context data dictionary to the dialog instance."""
        self.context_data = context_data

    def create(self):
        """Build the complete dialog structure."""
        with self.dialog:
            with ui.card().classes('w-[600px] p-6') as self.card:
                self.title_block = self.create_title_block()
                self.content_block = self.create_content_block()
                self.buttons_block = self.create_buttons_block()
        return self

    def create_title_block(self):
        """Override in subclass to customize title. Returns the block container."""
        with ui.column().classes('w-full mb-4') as block:
            ui.label('Dialog Title').classes('text-2xl font-bold mb-2')
        return block

    def create_content_block(self):
        """Override in subclass for main content. Returns the block container."""
        with ui.column().classes('w-full gap-4') as block:
            ui.label('Content goes here')
        return block

    def create_buttons_block(self):
        """Override in subclass for action buttons. Returns the block container."""
        with ui.row().classes('w-full gap-3 mt-4') as block:
            ui.button('Close', on_click=self.hide).classes('w-full bg-gray-600 text-white')
        return block

    def show(self):
        """Open the dialog."""
        self.dialog.open()

    def hide(self):
        """Close the dialog."""
        self.dialog.close()

    def clear(self):
        """Clear the dialog content."""
        self.dialog.clear()


class StartSessionDialog(PhoebeDialog):
    """Registration dialog for new sessions."""

    def __init__(self, client, sessions, on_session_activated):
        """
        Initialize login dialog.

        Args:
            client: The PhoebeClient instance
            on_session_activated: Callback for when login completes (user, session_id, project_name)
        """
        super().__init__(persistent=True)
        self.client = client
        self.sessions = sessions
        self.on_session_activated = on_session_activated
        self.create()

    def create_title_block(self):
        """Create the welcome title."""
        with ui.column().classes('w-full mb-4') as block:
            ui.label('Welcome to PHOEBE Lab').classes('text-2xl font-bold mb-2')
            ui.label('Please enter your project name below to begin').classes('text-gray-600')
        return block

    def create_content_block(self):
        """Create the registration form."""
        with ui.column().classes('w-full gap-4') as block:
            self.project_name_input = ui.input(
                'System/Project Name',
                placeholder='Enter a name for your project',
                value='Unnamed Project'
            ).classes('w-full').props('outlined')

            self.error_label = ui.label('').classes('text-red-500 text-sm')
            self.error_label.visible = False
        return block

    def create_buttons_block(self):
        """Create action buttons."""
        with ui.row().classes('w-full gap-3 mt-4') as block:
            self.start_button = ui.button(
                'Start Session',
                on_click=self.validate_and_create
            ).classes('flex-1 bg-blue-600 text-white').props('size=lg')
            # Back button only if sessions exist
            if self.sessions:
                self.back_button = ui.button(
                    'Back',
                    on_click=self.on_back
                ).classes('flex-1 bg-gray-600 text-white').props('size=lg')
            else:
                # Logout button if JWT auth (no back option, show logout instead)
                self.logout_button = ui.button(
                    'Logout',
                    on_click=self.on_logout,
                    icon='logout'
                ).classes('flex-1 bg-red-600 text-white').props('size=lg')

        return block

    def on_back(self):
        """Navigate back to SessionDialog."""
        self.hide()
        self.context_data['session_dialog'].show()

    def on_logout(self):
        """Handle logout - clear token and return to login."""
        # Clear the JWT token from browser storage
        if 'phoebe_token' in app.storage.user:
            app.storage.user.pop('phoebe_token')
        
        # Hide this dialog
        self.hide()
        
        # Show auth login dialog if available (JWT mode), otherwise fall back to login_dialog
        if 'auth_login' in self.context_data:
            self.context_data['auth_login'].show()
        elif 'login_dialog' in self.context_data:
            self.context_data['login_dialog'].show()
        else:
            # Fallback: navigate to root which will restart auth flow
            ui.navigate.to('/')
        
        ui.notify('You have been logged out.', type='info')

    async def validate_and_create(self):
        """Validate inputs and create new session."""
        project_name = self.project_name_input.value.strip() or 'Unnamed Project'

        # self.start_button.disable()
        self.start_button.props('loading')
        if self.sessions:
            self.back_button.disable()

        try:
            # Create session
            session_info = SessionInfo(
                project_name=project_name,
            )

            await self.on_session_activated(session_info=session_info, context_data=self.context_data)
        finally:
            # Now that the dialog is hidden, re-enable the buttons:
            # self.start_button.enable()
            self.start_button.props(remove='loading')
            if self.sessions:
                self.back_button.enable()
            self.hide()


class SessionManagerDialog(PhoebeDialog):
    """Session management dialog for reconnecting/managing sessions."""

    def __init__(self, client, sessions=None, current_session_id=None, on_session_activated=None):
        """
        Initialize session management dialog.

        Args:
            client: The PhoebeClient instance
            sessions: dict of existing sessions (if None, will call get_sessions())
            current_session_id: currently active session ID (if any)
            on_session_activated: callback to call on the resulting SessionInfo instance
        """
        super().__init__(persistent=True)
        self.client = client
        self.current_session_id = current_session_id
        self.on_session_activated = on_session_activated
        self.sessions = sessions or {}
        self.create()

        # Populate sessions if provided
        if sessions:
            self._populate_from_sessions()

    def create_title_block(self):
        """Create the title."""
        with ui.column().classes('w-full mb-4') as block:
            self.title_label = ui.label('Manage Sessions').classes('text-2xl font-bold')
        return block

    def create_content_block(self):
        """Create session selection and metadata display."""
        with ui.column().classes('w-full gap-4') as block:
            ui.label('Available sessions:').classes('text-sm font-semibold mb-2')

            self.session_select = ui.select(
                options={},
                value=None,
                with_input=False
            ).classes('w-full').props('outlined')

            with ui.card().classes('w-full bg-gray-50 p-4 mt-2'):
                ui.label('Session Details:').classes('text-sm font-semibold mb-2')
                self.metadata_display = ui.column().classes('gap-1')

            self.session_select.on_value_change(lambda: self.update_metadata())
        return block

    def create_buttons_block(self):
        """Create action buttons."""
        with ui.row().classes('w-full gap-3 mt-4') as block:
            self.new_button = ui.button(
                'New',
                on_click=self.on_new_session
            ).classes('flex-1 bg-blue-600 text-white').props('size=lg')

            self.reconnect_button = ui.button(
                'Reconnect',
                on_click=self.on_reconnect_session
            ).classes('flex-1 bg-blue-600 text-white').props('size=lg')

            self.delete_button = ui.button(
                'Delete',
                on_click=self.on_delete_session
            ).classes('flex-1 bg-red-600 text-white').props('size=lg')

            self.close_button = ui.button(
                'Close',
                on_click=self.hide
            ).classes('flex-1 bg-gray-600 text-white').props('size=lg')
        return block

    async def refresh(self):
        """Refresh the dialog with current data from server (async)."""
        self.sessions = await run.io_bound(self.client.get_sessions)
        self._populate_from_sessions()

    def _populate_from_sessions(self):
        """Populate dialog UI from self.sessions."""
        sorted_sessions = sorted(
            self.sessions.items(),
            key=lambda x: x[1].get('last_activity', 0),
            reverse=True
        )

        options = {
            session_id: session_data.get('project_name', 'Unnamed Project')
            for session_id, session_data in self.sessions.items()
        }

        self.session_select.options = options

        if self.current_session_id and self.current_session_id in self.sessions:
            self.session_select.value = self.current_session_id
        elif sorted_sessions:
            self.session_select.value = sorted_sessions[0][0]

        self.update_metadata()

    def update_metadata(self):
        """Update the metadata display for the selected session."""
        self.metadata_display.clear()

        selected_id = self.session_select.value
        if not selected_id or selected_id not in self.sessions:
            return

        session = self.sessions[selected_id]

        with self.metadata_display:
            from datetime import datetime

            ui.label(
                f"Project: {session.get('project_name', 'Unnamed Project')}"
            ).classes('text-sm text-gray-700 font-semibold')

            full_name = session.get('full_name', '')
            if full_name:
                ui.label(f"Owner: {full_name}").classes('text-sm text-gray-700')

            created_at = session.get('created_at', 0)
            if created_at:
                created_dt = datetime.fromtimestamp(created_at)
                ui.label(f"Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S')}").classes('text-sm text-gray-700')

            last_activity = session.get('last_activity', 0)
            if last_activity:
                activity_dt = datetime.fromtimestamp(last_activity)
                ui.label(f"Last Activity: {activity_dt.strftime('%Y-%m-%d %H:%M:%S')}").classes('text-sm text-gray-700')

            mem_used = session.get('mem_used', 0)
            if mem_used:
                ui.label(f"Memory: {mem_used:.1f} MB").classes('text-sm text-gray-700')

            session_id_short = selected_id[:16]
            ui.label(f"Session ID: {session_id_short}...").classes('text-sm text-gray-600 font-mono')

    def on_new_session(self):
        """Handle new session creation."""

        self.hide()
        self.context_data['login_dialog'].show()

    async def on_reconnect_session(self):
        """Handle reconnecting to selected session."""
        selected_id = self.session_select.value

        if selected_id == self.current_session_id:
            ui.notify('Already connected to this session', color='info')
            self.hide()
            return

        self.new_button.disable()
        self.delete_button.disable()
        self.close_button.disable()
        self.reconnect_button.props('loading')

        try:
            # Create SessionInfo and invoke callback to rebuild UI with new session
            session_info = SessionInfo.from_dict(self.sessions.get(selected_id, {}))
            ui.notify(f'Switching to session "{session_info.project_name}"', color='positive')
            if self.on_session_activated:
                await self.on_session_activated(session_info=session_info, context_data=self.context_data)
        finally:
            # self.reconnect_button.enable()
            self.reconnect_button.props(remove='loading')
            self.new_button.enable()
            self.delete_button.enable()
            self.close_button.enable()
            self.hide()

    def on_delete_session(self):
        """Handle session deletion with confirmation."""
        selected_id = self.session_select.value

        if not selected_id:
            ui.notify('No session selected', color='warning')
            return

        session = self.sessions.get(selected_id)
        if not session:
            ui.notify('Session not found', color='negative')
            return

        project_name = session.get('project_name', 'Unnamed Project')

        with ui.dialog() as confirm_dialog, ui.card().classes('p-6'):
            ui.label(f"Delete session '{project_name}'?").classes('text-lg font-semibold mb-2')
            ui.label('This action cannot be undone.').classes('text-sm text-gray-600 mb-4')

            with ui.row().classes('w-full gap-2 justify-end'):
                ui.button('Cancel', on_click=confirm_dialog.close).props('flat')
                ui.button(
                    'Delete',
                    on_click=partial(self.confirm_delete, selected_id, confirm_dialog)
                ).props('flat color=negative')

        confirm_dialog.open()

    async def confirm_delete(self, session_id: str, confirm_dialog):
        """Execute session deletion after confirmation."""
        confirm_dialog.close()

        try:
            self.client.end_session(session_id)
            ui.notify('Session deleted successfully', color='positive')

            await self.refresh()

            if session_id == self.current_session_id:
                self.hide()
                ui.notify('Current session deleted, reloading...', color='info')
                ui.navigate.to('/')

            if not self.sessions:
                # last session deleted
                self.hide()
                ui.navigate.to('/')

        except Exception as e:
            ui.notify(f'Failed to delete session: {str(e)}', color='negative')


class AuthLoginDialog(PhoebeDialog):
    """Login dialog for JWT/password server auth modes."""

    def __init__(self, client, on_authenticated):
        """
        Args:
            client: PhoebeClient instance
            on_authenticated: Callback after successful login
        """
        super().__init__(persistent=True)
        self.client = client
        self.on_authenticated = on_authenticated
        self.create()

    def create_title_block(self):
        with ui.column().classes('w-full mb-4') as block:
            ui.label('Welcome to PHOEBE Lab').classes('text-2xl font-bold mb-2')
            ui.label('Sign in to continue').classes('text-gray-600')
        return block

    def create_content_block(self):
        with ui.column().classes('w-full gap-4') as block:
            self.email_input = ui.input(
                'Email', placeholder='your.email@example.com'
            ).classes('w-full').props('outlined')

            self.password_input = ui.input(
                'Password', password=True, password_toggle_button=True
            ).classes('w-full').props('outlined')
            self.password_input.on('keydown.enter', self.do_login)

            self.error_label = ui.label('').classes('text-red-500 text-sm')
            self.error_label.visible = False
        return block

    def create_buttons_block(self):
        with ui.row().classes('w-full gap-3 mt-4') as block:
            self.login_button = ui.button(
                'Sign In', on_click=self.do_login
            ).classes('flex-1 bg-blue-600 text-white').props('size=lg')

            self.register_link = ui.button(
                'Create Account', on_click=self.go_to_register
            ).classes('flex-1').props('flat size=lg')
        return block

    async def do_login(self):
        email = self.email_input.value.strip()
        password = self.password_input.value

        if not email or not password:
            self.error_label.text = 'Email and password are required'
            self.error_label.visible = True
            return

        self.login_button.props('loading')
        try:
            result = await run.io_bound(self.client.login, email, password)
            # Persist token to browser storage for session survival
            token = result.get('access_token')
            if token:
                app.storage.user['phoebe_token'] = token
            self.hide()
            await self.on_authenticated()
        except Exception as e:
            self.error_label.text = str(e)
            self.error_label.visible = True
        finally:
            self.login_button.props(remove='loading')

    def go_to_register(self):
        self.hide()
        self.context_data.get('register_dialog', self).show()


class AuthRegisterDialog(PhoebeDialog):
    """Registration dialog for JWT/password server auth modes."""

    def __init__(self, client, on_authenticated):
        super().__init__(persistent=True)
        self.client = client
        self.on_authenticated = on_authenticated
        self.create()

    def create_title_block(self):
        with ui.column().classes('w-full mb-4') as block:
            ui.label('Create Account').classes('text-2xl font-bold mb-2')
            ui.label('Register to get started').classes('text-gray-600')
        return block

    def create_content_block(self):
        with ui.column().classes('w-full gap-4') as block:
            self.first_name_input = ui.input(
                'First Name', placeholder='First name'
            ).classes('w-full').props('outlined')

            self.last_name_input = ui.input(
                'Last Name', placeholder='Last name'
            ).classes('w-full').props('outlined')

            self.email_input = ui.input(
                'Email', placeholder='your.email@example.com'
            ).classes('w-full').props('outlined')

            self.password_input = ui.input(
                'Password', password=True, password_toggle_button=True
            ).classes('w-full').props('outlined')
            self.password_input.on('keydown.enter', self.do_register)

            self.error_label = ui.label('').classes('text-red-500 text-sm')
            self.error_label.visible = False
        return block

    def create_buttons_block(self):
        with ui.row().classes('w-full gap-3 mt-4') as block:
            self.register_button = ui.button(
                'Register', on_click=self.do_register
            ).classes('flex-1 bg-blue-600 text-white').props('size=lg')

            self.login_link = ui.button(
                'Sign In Instead', on_click=self.go_to_login
            ).classes('flex-1').props('flat size=lg')
        return block

    async def do_register(self):
        first = self.first_name_input.value.strip()
        last = self.last_name_input.value.strip()
        email = self.email_input.value.strip()
        password = self.password_input.value

        errors = []
        if not first:
            errors.append('First name is required')
        if not last:
            errors.append('Last name is required')
        if not email:
            errors.append('Email is required')
        if not password:
            errors.append('Password is required')

        if errors:
            self.error_label.text = '; '.join(errors)
            self.error_label.visible = True
            return

        self.register_button.props('loading')
        try:
            result = await run.io_bound(
                self.client.register, email, password, first, last
            )
            # Persist token to browser storage for session survival
            token = result.get('access_token')
            if token:
                app.storage.user['phoebe_token'] = token
            self.hide()
            await self.on_authenticated()
        except Exception as e:
            self.error_label.text = str(e)
            self.error_label.visible = True
        finally:
            self.register_button.props(remove='loading')

    def go_to_login(self):
        self.hide()
        self.context_data.get('login_dialog', self).show()


class PasswordProtected(PhoebeDialog):
    """Password gate that guards access to another dialog."""

    def __init__(self, guarded_dialog: PhoebeDialog, password: str,
                 guard_enabled: bool = True, storage_key: str = 'session_manager_access'):
        super().__init__(persistent=True)
        self.guarded_dialog = guarded_dialog
        self.password = password
        self.guard_enabled = guard_enabled
        self.storage_key = storage_key
        self.password_input = None
        self.error_label = None
        self.create()

    def __getattr__(self, name):
        """Proxy unknown attributes to the guarded dialog."""
        return getattr(self.guarded_dialog, name)

    def has_access(self) -> bool:
        if not self.guard_enabled or not self.password:
            return True
        return app.storage.user.get(self.storage_key, False)

    def show(self):
        """Show password prompt if needed, otherwise open guarded dialog directly."""
        if self.has_access():
            self.guarded_dialog.show()
            return

        if self.password_input:
            self.password_input.value = ''
        if self.error_label:
            self.error_label.visible = False
        super().show()

    def create_title_block(self):
        with ui.column().classes('w-full mb-4') as block:
            ui.label('Session Manager Access').classes('text-lg font-semibold mb-2')
            ui.label('Enter the access password to continue.').classes('text-sm text-gray-600')
        return block

    def create_content_block(self):
        with ui.column().classes('w-full gap-3') as block:
            self.password_input = ui.input(
                'Password', password=True,
                on_change=lambda: self._clear_error()
            ).classes('w-full').props('outlined')
            self.password_input.on('keydown.enter', self.confirm_access)
            self.error_label = ui.label('').classes('text-red-500 text-sm')
            self.error_label.visible = False
        return block

    def create_buttons_block(self):
        with ui.row().classes('w-full gap-3 mt-4') as block:
            ui.button('Cancel', on_click=self.hide).classes('flex-1 bg-gray-600 text-white')
            ui.button('Continue', on_click=self.confirm_access).classes('flex-1 bg-blue-600 text-white')
        return block

    def confirm_access(self):
        if self.password_input.value == self.password:
            app.storage.user[self.storage_key] = True
            self.hide()
            self.guarded_dialog.show()
        else:
            self.error_label.text = 'Incorrect password'
            self.error_label.visible = True

    def _clear_error(self):
        if self.error_label and self.error_label.visible:
            self.error_label.visible = False
