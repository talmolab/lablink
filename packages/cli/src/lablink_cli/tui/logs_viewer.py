"""Textual TUI for viewing LabLink VM logs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
)

from lablink_allocator_service.conf.structured_config import Config


class VMListItem(ListItem):
    """A list item representing a VM."""

    def __init__(self, vm: dict) -> None:
        self.vm = vm
        vm_type = vm["vm_type"]
        name = vm["name"]
        state = vm["state"]
        label = f"[{'cyan' if vm_type == 'allocator' else 'green'}]{vm_type}[/] {name}"
        if state != "running":
            label += f" [dim]({state})[/dim]"
        super().__init__(Label(label, markup=True))


class LogsApp(App):
    """Interactive log viewer for LabLink VMs."""

    TITLE = "LabLink Log Viewer"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "show_cloud_init", "Cloud-Init"),
        Binding("2", "show_docker", "Docker"),
    ]

    CSS = """
    #main-container {
        height: 1fr;
    }

    #vm-list-panel {
        width: 35;
        min-width: 25;
        border-right: solid $primary-lighten-2;
    }

    #vm-list-panel Label {
        padding: 0 1;
        color: $text-muted;
    }

    #vm-list {
        height: 1fr;
    }

    #log-panel {
        width: 1fr;
    }

    #log-header {
        height: 3;
        padding: 0 1;
    }

    #vm-info {
        padding: 0 1;
    }

    #tab-bar {
        height: 1;
        padding: 0 1;
    }

    .tab {
        width: auto;
        margin-right: 2;
    }

    .tab-active {
        color: $accent;
        text-style: bold underline;
    }

    .tab-inactive {
        color: $text;
    }

    #log-output {
        height: 1fr;
        border-top: solid $primary-lighten-3;
    }

    #status-bar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        border-top: solid $primary-lighten-3;
    }
    """

    def __init__(
        self,
        cfg: Config,
        vms: list[dict],
        allocator_url: str,
        admin_user: str,
        admin_pw: str,
        deploy_dir: Path,
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._vms = vms
        self._allocator_url = allocator_url
        self._admin_user = admin_user
        self._admin_pw = admin_pw
        self._deploy_dir = deploy_dir
        self._selected_vm: dict | None = None
        self._current_tab = "cloud_init"
        self._cached_logs: dict | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            with Vertical(id="vm-list-panel"):
                yield Label(
                    f"[bold]{self._cfg.deployment_name}[/bold] "
                    f"({self._cfg.environment})"
                )
                yield ListView(
                    *[VMListItem(vm) for vm in self._vms],
                    id="vm-list",
                )
            with Vertical(id="log-panel"):
                yield Label("Select a VM to view logs", id="vm-info")
                with Horizontal(id="tab-bar"):
                    yield Static(
                        "[bold]Cloud-Init[/bold]",
                        id="tab-cloud-init",
                        classes="tab tab-active",
                        markup=True,
                    )
                    yield Static(
                        "Docker",
                        id="tab-docker",
                        classes="tab tab-inactive",
                        markup=True,
                    )
                yield RichLog(
                    id="log-output",
                    auto_scroll=True,
                    wrap=True,
                    markup=True,
                )
                yield Label("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Show initial hint in the log panel."""
        log_output = self.query_one("#log-output", RichLog)
        log_output.write(
            "[dim]Select a VM from the list to view its logs.[/dim]"
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle VM selection."""
        item = event.item
        if isinstance(item, VMListItem):
            self._selected_vm = item.vm
            self._cached_logs = None
            self._update_vm_info()
            # Clear log panel immediately and show loading state
            log_output = self.query_one("#log-output", RichLog)
            log_output.clear()
            log_output.write("[dim]Fetching logs...[/dim]")
            self._set_status("Fetching logs...")
            self._fetch_logs()

    def _update_vm_info(self) -> None:
        """Update the VM info label."""
        vm = self._selected_vm
        if not vm:
            return
        info = self.query_one("#vm-info", Label)
        ip_display = vm.get("public_ip", "—")
        info.update(
            f"[bold]{vm['name']}[/bold]  "
            f"({vm['type']})  "
            f"IP: {ip_display}"
        )

    def _update_tab_styles(self) -> None:
        """Update tab visual state."""
        cloud_init_tab = self.query_one("#tab-cloud-init", Static)
        docker_tab = self.query_one("#tab-docker", Static)
        if self._current_tab == "cloud_init":
            cloud_init_tab.update("[bold]Cloud-Init[/bold]")
            cloud_init_tab.set_classes("tab tab-active")
            docker_tab.update("Docker")
            docker_tab.set_classes("tab tab-inactive")
        else:
            cloud_init_tab.update("Cloud-Init")
            cloud_init_tab.set_classes("tab tab-inactive")
            docker_tab.update("[bold]Docker[/bold]")
            docker_tab.set_classes("tab tab-active")

    _MAX_LOG_LINES = 5000

    def _display_logs(self) -> None:
        """Display logs from cache for the current tab."""
        log_output = self.query_one("#log-output", RichLog)
        log_output.clear()

        if self._cached_logs is None:
            log_output.write("[dim]No logs loaded. Select a VM.[/dim]")
            return

        error = self._cached_logs.get("error")
        if error:
            log_output.write(f"[red]{error}[/red]")
            return

        if self._current_tab == "cloud_init":
            content = self._cached_logs.get("cloud_init_logs")
        else:
            content = self._cached_logs.get("docker_logs")

        if content:
            lines = content.splitlines()
            if len(lines) > self._MAX_LOG_LINES:
                skipped = len(lines) - self._MAX_LOG_LINES
                log_output.write(
                    f"[dim]... {skipped} earlier lines truncated ...[/dim]"
                )
                lines = lines[-self._MAX_LOG_LINES :]
            for line in lines:
                log_output.write(line)
        else:
            tab_name = (
                "Cloud-Init" if self._current_tab == "cloud_init" else "Docker"
            )
            log_output.write(
                f"[dim]No {tab_name} logs available for this VM.[/dim]"
            )

    @work(thread=True, exclusive=True)
    def _fetch_logs(self) -> None:
        """Fetch logs in a background thread."""
        vm = self._selected_vm
        if not vm:
            return

        if vm["vm_type"] == "client":
            if not self._allocator_url:
                logs = {
                    "cloud_init_logs": None,
                    "docker_logs": None,
                    "error": (
                        "Allocator URL not available. "
                        "Cannot fetch client logs."
                    ),
                }
            else:
                from lablink_cli.commands.logs import fetch_client_logs

                logs = fetch_client_logs(
                    allocator_url=self._allocator_url,
                    hostname=vm["name"],
                    admin_user=self._admin_user,
                    admin_pw=self._admin_pw,
                    ssl_provider=self._cfg.ssl.provider,
                )
        else:
            from lablink_cli.commands.logs import fetch_allocator_logs

            logs = fetch_allocator_logs(
                instance_id=vm["instance_id"],
                public_ip=vm.get("public_ip", "—"),
                region=self._cfg.app.region,
                deploy_dir=self._deploy_dir,
            )

        # Guard: discard results if user selected a different VM while fetching
        if self._selected_vm is not vm:
            return

        self._cached_logs = logs
        now = datetime.now().strftime("%H:%M:%S")
        self.call_from_thread(self._display_logs)
        self.call_from_thread(self._set_status, f"Last fetched: {now}")

    def _set_status(self, text: str) -> None:
        """Update the status bar."""
        status = self.query_one("#status-bar", Label)
        status.update(f"[dim]{text}[/dim]")

    def action_refresh(self) -> None:
        """Refresh logs for the selected VM."""
        if self._selected_vm:
            self._fetch_logs()

    def action_show_cloud_init(self) -> None:
        """Switch to cloud-init log tab."""
        self._current_tab = "cloud_init"
        self._update_tab_styles()
        self._display_logs()

    def action_show_docker(self) -> None:
        """Switch to docker log tab."""
        self._current_tab = "docker"
        self._update_tab_styles()
        self._display_logs()

