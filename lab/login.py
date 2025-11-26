from nicegui import ui
from lab.user import User


class Login:
    """
    Manages login dialogs for student identification and session management.

    Provides methods to create login dialogs and session reconnection dialogs
    with callback-based event handling.
    """

    def __init__(self, client, on_login_completed, existing_sessions: dict = {}):
        """
        Initialize Login manager.

        Args:
            on_login_completed: Function to call with User object when login is complete
            existing_sessions: Dict with session_id keys and metadata values
        """

        self.client = client

        self.existing_sessions = existing_sessions
        self.on_login_completed = on_login_completed

        ui.add_css('/static/styles.css')
        self.dialog = ui.dialog()

        if self.existing_sessions:
            self.create_existing_session_dialog()
        else:
            self.create_new_session_dialog()

    def create_existing_session_dialog(self) -> None:
        """
        Create dialog for handling existing session reconnection.
        """

        if not self.existing_sessions:
            self.create_new_session_dialog()
            return

        # Sort sessions by last_activity (most recent first)
        sorted_sessions = sorted(
            self.existing_sessions.items(),
            key=lambda x: x[1].get('last_activity', 0),
            reverse=True
        )

        # Get most recent session for welcome message
        session_id, session = sorted_sessions[0]
        first_name = session.get('user_first_name', None)
        last_name = session.get('user_last_name', None)
        display_name = f'{first_name} {last_name}' if first_name and last_name else None

        with self.dialog.props('persistent'), ui.card().classes('w-[600px] p-6'):
            if display_name:
                ui.label(f'Welcome back, {display_name}!').classes('text-2xl font-bold mb-4')
            else:
                ui.label('Welcome back!').classes('text-2xl font-bold mb-4')

            # Session selection dropdown
            with ui.column().classes('w-full gap-2 mb-6'):
                ui.label('Available sessions:').classes('text-sm font-semibold mb-2')

                # Build options dict for dropdown
                options = {
                    session_id: session_data.get('project_name', 'Unnamed Project')
                    for session_id, session_data in self.existing_sessions.items()
                }

                # Default to most recent session
                default_session_id = session_id

                self.session_select = ui.select(
                    options=options,
                    value=default_session_id,
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
                        # Get the session data for the selected ID
                        session = self.existing_sessions.get(selected_id)
                        if session:
                            from datetime import datetime

                            with self.metadata_display:
                                ui.label(f"Project: {session.get('project_name', 'Unnamed Project')}").classes('text-sm text-gray-700 font-semibold')

                                # Owner information
                                first_name = session.get('user_first_name', None)
                                last_name = session.get('user_last_name', None)

                                owner_name = f'{first_name} {last_name}' if first_name and last_name else None
                                if owner_name:
                                    ui.label(f"Owner: {owner_name}").classes('text-sm text-gray-700')

                                email = session.get('user_email', '')
                                if email:
                                    ui.label(f"Email: {email}").classes('text-sm text-gray-700')

                                # Session timing information
                                created_at = session.get('created_at', 0)
                                if created_at:
                                    created_dt = datetime.fromtimestamp(created_at)
                                    ui.label(f"Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S')}").classes('text-sm text-gray-700')

                                last_activity = session.get('last_activity', 0)
                                if last_activity:
                                    activity_dt = datetime.fromtimestamp(last_activity)
                                    ui.label(f"Last Activity: {activity_dt.strftime('%Y-%m-%d %H:%M:%S')}").classes('text-sm text-gray-700')

                                # Memory usage
                                mem_used = session.get('mem_used', 0)
                                if mem_used:
                                    ui.label(f"Memory: {mem_used:.1f} MB").classes('text-sm text-gray-700')

                                # Session ID
                                session_id_short = session['session_id'][:16]
                                ui.label(f"Session ID: {session_id_short}...").classes('text-sm text-gray-600 font-mono')

                    # Initialize metadata display
                    update_metadata_display()

                    # Update display when selection changes
                    self.session_select.on('update:model-value', update_metadata_display)

            # Action buttons
            with ui.row().classes('w-full gap-3 mt-4'):
                ui.button(
                    'New',
                    on_click=self.on_start_new_session
                ).classes('flex-1 bg-blue-600 text-white').props('size=lg')

                ui.button(
                    'Reconnect',
                    on_click=self.on_continue_session
                ).classes('flex-1 bg-blue-600 text-white').props('size=lg')

                ui.button(
                    'Delete',
                    on_click=self.on_delete_session
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
        selected_session = self.existing_sessions.get(selected_id)

        if not selected_session:
            ui.notify('Invalid session selection', type='negative')
            return

        # Construct User from session fields
        user = User(
            first_name=selected_session.get('user_first_name', ''),
            last_name=selected_session.get('user_last_name', ''),
            email=selected_session.get('user_email', '')
        )
        project_name = selected_session.get('project_name', 'Unnamed Project')

        self.dialog.close()
        self.on_login_completed(user=user, session_id=selected_id, project_name=project_name)

    def on_start_new_session(self):
        """Handle start new session button click."""
        self.dialog.clear()
        self.create_new_session_dialog()

    def on_delete_session(self):
        """Handle delete session button click with confirmation."""
        selected_id = self.session_select.value
        if not selected_id:
            ui.notify('No session selected', color='warning')
            return

        # Get the selected session data
        session = self.existing_sessions.get(selected_id)
        if not session:
            ui.notify('Session not found', color='negative')
            return

        project_name = session.get('project_name', 'Unnamed Project')

        # Create confirmation dialog
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
        confirm_dialog.close()

        try:
            # End the session on the server
            self.client.end_session(session_id)

            # Refresh sessions dict from server
            self.existing_sessions = self.client.get_sessions()

            ui.notify('Session deleted successfully', color='positive')

            # If no sessions left, switch to new session dialog
            if not self.existing_sessions:
                self.dialog.clear()
                # self.dialog.close()
                self.create_new_session_dialog()
            else:
                # Refresh the dialog with remaining sessions
                self.dialog.clear()
                self.create_existing_session_dialog()

        except Exception as e:
            ui.notify(f'Failed to delete session: {str(e)}', color='negative')

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
