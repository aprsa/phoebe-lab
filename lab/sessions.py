from dataclasses import dataclass, asdict, fields
from nicegui import ui


@dataclass
class SessionInfo:
    """
    Passive server session state. Server is the single source of truth.
    """

    first_name: str = ""
    last_name: str = ""
    email: str = ""
    session_id: str | None = None
    project_name: str = "Unnamed Project"
    created_at: float | None = None
    last_activity: float | None = None
    mem_used: float | None = None
    port: int | None = None

    @property
    def full_name(self) -> str:
        return f'{self.first_name} {self.last_name}'.strip()

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


class LoginDialog(PhoebeDialog):
    """Login/registration dialog for new sessions."""

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
            ui.label('Please register below to begin').classes('text-gray-600')
        return block

    def create_content_block(self):
        """Create the registration form."""
        with ui.column().classes('w-full gap-4') as block:
            self.project_name_input = ui.input(
                'System/Project Name',
                placeholder='Enter a name for your binary system',
                value='Unnamed Project'
            ).classes('w-full').props('outlined')

            self.first_name_input = ui.input(
                'First Name',
                placeholder='Enter your first name'
            ).classes('w-full').props('outlined')

            self.last_name_input = ui.input(
                'Last Name',
                placeholder='Enter your last name'
            ).classes('w-full').props('outlined')

            self.email_input = ui.input(
                'Email (optional)',
                placeholder='your.email@example.com'
            ).classes('w-full').props('outlined')

            self.error_label = ui.label('').classes('text-red-500 text-sm')
            self.error_label.visible = False
        return block

    def create_buttons_block(self):
        """Create action buttons."""
        with ui.row().classes('w-full gap-3 mt-4') as block:
            ui.button(
                'Start Session',
                on_click=self.validate_and_create
            ).classes('flex-1 bg-blue-600 text-white').props('size=lg')
            # Back button only if sessions exist
            if self.sessions:
                ui.button(
                    'Back',
                    on_click=self.on_back
                ).classes('flex-1 bg-gray-600 text-white').props('size=lg')
            


        return block

    def on_back(self):
        """Navigate back to SessionDialog."""
        self.hide()
        self.context_data['session_dialog'].show()

    def validate_and_create(self):
        """Validate inputs and create new session."""
        first_name = self.first_name_input.value.strip()
        last_name = self.last_name_input.value.strip()
        email = self.email_input.value.strip()
        project_name = self.project_name_input.value.strip() or 'Unnamed Project'

        errors = []
        if not first_name:
            errors.append("First name is required")
        if not last_name:
            errors.append("Last name is required")

        if errors:
            self.error_label.text = "; ".join(errors)
            self.error_label.visible = True
            return

        # Create session
        session_info = SessionInfo(
            first_name=first_name,
            last_name=last_name,
            email=email,
            project_name=project_name
        )
        self.hide()
        self.on_session_activated(session_info=session_info, context_data=self.context_data)


class SessionDialog(PhoebeDialog):
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
        self.sessions = sessions if sessions is not None else {}
        self.create()
        
        # Populate sessions if provided, otherwise refresh from server
        if sessions:
            self._populate_from_sessions()
        else:
            self.refresh()

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
            ui.button(
                'New',
                on_click=self.on_new_session
            ).classes('flex-1 bg-blue-600 text-white').props('size=lg')

            ui.button(
                'Reconnect',
                on_click=self.on_reconnect_session
            ).classes('flex-1 bg-blue-600 text-white').props('size=lg')

            ui.button(
                'Delete',
                on_click=self.on_delete_session
            ).classes('flex-1 bg-red-600 text-white').props('size=lg')

            ui.button(
                'Close',
                on_click=self.hide
            ).classes('flex-1 bg-gray-600 text-white').props('size=lg')
        return block

    def refresh(self):
        """Refresh the dialog with current data from server."""
        self.sessions = self.client.get_sessions()
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

            first_name = session.get('user_first_name', '')
            last_name = session.get('user_last_name', '')
            if first_name or last_name:
                owner_name = f'{first_name} {last_name}'.strip()
                ui.label(f"Owner: {owner_name}").classes('text-sm text-gray-700')

            email = session.get('user_email', '')
            if email:
                ui.label(f"Email: {email}").classes('text-sm text-gray-700')

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

    def on_reconnect_session(self):
        """Handle reconnecting to selected session."""
        selected_id = self.session_select.value

        if selected_id == self.current_session_id:
            ui.notify('Already connected to this session', color='info')
            self.hide()
            return

        self.hide()

        # Create SessionInfo and invoke callback to rebuild UI with new session
        session_info = SessionInfo.from_dict(self.sessions.get(selected_id, {}))
        ui.notify(f'Switching to session "{session_info.project_name}"', color='positive')
        if self.on_session_activated:
            self.on_session_activated(session_info=session_info, context_data=self.context_data)

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
                    on_click=lambda: self.confirm_delete(selected_id, confirm_dialog)
                ).props('flat color=negative')

        confirm_dialog.open()

    def confirm_delete(self, session_id: str, confirm_dialog):
        """Execute session deletion after confirmation."""
        confirm_dialog.close()

        try:
            self.client.end_session(session_id)
            ui.notify('Session deleted successfully', color='positive')

            self.refresh()

            if session_id == self.current_session_id:
                self.hide()
                ui.notify('Current session deleted, reloading...', color='info')
                ui.navigate.to('/')

        except Exception as e:
            ui.notify(f'Failed to delete session: {str(e)}', color='negative')
