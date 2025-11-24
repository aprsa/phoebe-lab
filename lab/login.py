from nicegui import ui
from lab.user import User


class Login:
    """
    Manages login dialogs for student identification and session management.

    Provides methods to create login dialogs and session reconnection dialogs
    with callback-based event handling.
    """

    def __init__(self, on_login_completed, existing_session_id: str | None = None, existing_user: User | None = None, existing_project_name: str | None = None):
        """
        Initialize Login manager.

        Args:
            on_login_completed: Function to call with User object when login is complete
            existing_session_id: ID of an existing session, if any
            existing_user: User object for the logged-in user, if any
            existing_project_name: Project name for the existing session, if any
        """

        self.user = existing_user
        self.session_id = existing_session_id
        self.project_name = existing_project_name or "My Binary System"
        self.on_login_completed = on_login_completed

        ui.add_css('/static/styles.css')
        self.dialog = ui.dialog()

        if self.session_id and self.user:
            self.create_existing_session_dialog()
        else:
            self.create_new_session_dialog()

    def create_existing_session_dialog(self) -> None:
        """
        Create dialog for handling existing session reconnection.
        """

        if not self.user or not self.session_id:
            self.create_new_session_dialog()
            return

        with self.dialog.props('persistent'), ui.card().classes('w-[600px] p-6'):
            ui.label(f'Welcome back, {self.user.full_name}!').classes('text-2xl font-bold mb-4')

            # Session selection dropdown (future: will support multiple sessions)
            with ui.column().classes('w-full gap-2 mb-6'):
                ui.label('Available sessions:').classes('text-sm font-semibold mb-2')

                # Build session data with metadata
                # Store metadata separately to access after selection
                self.sessions_data = [{
                    'first_name': self.user.first_name,
                    'last_name': self.user.last_name,
                    'email': self.user.email,
                    'timestamp': self.user.timestamp,
                    'session_id': self.session_id,
                    'project_name': self.project_name,
                    'display': f'{self.project_name}'
                }]

                # Currently single session, but dropdown ready for multiple
                # ui.select needs simple dict format: {value: label}
                options = {
                    session['session_id']: session['display']
                    for session in self.sessions_data
                }

                self.session_select = ui.select(
                    options=options,
                    value=self.session_id,
                    with_input=False
                ).classes('w-full').props('outlined')

                # Display selected session metadata
                with ui.card().classes('w-full bg-gray-50 p-4 mt-2'):
                    ui.label('Session Details:').classes('text-sm font-semibold mb-2')
                    self.metadata_display = ui.column().classes('gap-1')

                    def update_metadata_display():
                        """Update metadata display based on selected session."""
                        self.metadata_display.clear()
                        selected_id = self.session_select.value
                        # Find the session data for the selected ID
                        meta = next((s for s in self.sessions_data if s['session_id'] == selected_id), None)
                        if meta:
                            with self.metadata_display:
                                ui.label(f"Project: {meta.get('project_name', 'My Binary System')}").classes('text-sm text-gray-700 font-semibold')
                                ui.label(f"Owner: {meta['first_name']} {meta['last_name']}").classes('text-sm text-gray-700')
                                if meta.get('email'):
                                    ui.label(f"Email: {meta['email']}").classes('text-sm text-gray-700')
                                ui.label(f"Started on: {meta['timestamp']}").classes('text-sm text-gray-700')
                                ui.label(f"Session ID: {meta['session_id']}").classes('text-sm text-gray-600 font-mono')

                    # Initialize metadata display
                    update_metadata_display()

                    # Update display when selection changes
                    self.session_select.on('update:model-value', update_metadata_display)

            # Action buttons
            with ui.row().classes('w-full gap-3 mt-4'):
                ui.button(
                    'Continue Session',
                    on_click=self.on_continue_session
                ).classes('flex-1 bg-blue-600 text-white').props('size=lg')

                ui.button(
                    'Start New Session',
                    on_click=self.on_start_new_session
                ).classes('flex-1 bg-blue-600 text-white').props('size=lg')

        self.dialog.open()

    def create_new_session_dialog(self) -> None:
        """
        Create login dialog to collect student identification.
        """

        with self.dialog.props('persistent'), ui.card().classes('w-[600px] p-6'):
            ui.label('Welcome to PHOEBE Lab').classes('text-2xl font-bold mb-2')
            ui.label('Please register below to begin').classes('text-gray-600 mb-6')

            with ui.column().classes('w-full gap-4'):
                self.project_name_input = ui.input(
                    'System/Project Name',
                    placeholder='Enter a name for your binary system',
                    value='My Binary System'
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

                ui.button(
                    'Start Session',
                    on_click=self.validate_login
                ).classes('w-full bg-blue-600 text-white mt-4').props('size=lg')

                # Allow Enter key to submit
                self.email_input.on('keydown.enter', self.validate_login)

        self.dialog.open()

    def on_continue_session(self):
        """Handle continue session button click."""
        # Get selected session metadata
        selected_id = self.session_select.value
        selected_session = next((s for s in self.sessions_data if s['session_id'] == selected_id), None)
        project_name = selected_session.get('project_name', 'My Binary System') if selected_session else 'My Binary System'

        self.dialog.close()
        self.on_login_completed(user=self.user, session_id=self.session_select.value, project_name=project_name)

    def on_start_new_session(self):
        """Handle start new session button click."""
        self.dialog.clear()
        self.create_new_session_dialog()

    def validate_login(self) -> bool:
        """Validate login input fields."""
        first_name = self.first_name_input.value.strip()
        last_name = self.last_name_input.value.strip()
        email = self.email_input.value.strip()

        errors = []
        if not first_name:
            errors.append("First name is required")
        if not last_name:
            errors.append("Last name is required")

        if errors:
            self.error_label.text = "; ".join(errors)
            self.error_label.set_visibility(True)
            return False

        # Create user
        self.user = User(
            first_name=first_name,
            last_name=last_name,
            email=email
        )

        # Get project name
        project_name = self.project_name_input.value.strip() or "My Binary System"

        self.on_login_completed(user=self.user, session_id=None, project_name=project_name)
        self.dialog.close()

        return True
