"""
src/cli/console.py
------------------
Shared Rich console adapter with plain-stdout fallbacks so pipeline modules
never duplicate business logic across Rich/non-Rich branches.
"""

from contextlib import contextmanager
import sys
from typing import Iterable, Optional

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None
    box = None
    Panel = None
    Table = None
    Text = None


def print_banner(
    section: str,
    subtitle: str,
    meta_markup: Iterable[str] = (),
    border_style: str = "cyan",
    brand: str = "TIAMAT QUANT TERMINAL",
) -> None:
    if not HAS_RICH:
        print(f"\n--- {brand} | {section} ---")
        return

    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=3)
    grid.add_column(justify="right", ratio=2)

    title = Text()
    title.append(brand, style="bold cyan")
    title.append(" │ ", style="dim white")
    title.append(section, style="bold white")
    title.append(f"\n{subtitle}", style="dim italic")

    meta = Text.from_markup("\n".join(meta_markup)) if meta_markup else Text()
    grid.add_row(title, meta)
    console.print(Panel(grid, box=box.ROUNDED, border_style=border_style, padding=(0, 1)))
    console.print()


def print_msg(rich_markup: str, plain_text: Optional[str] = None, err: bool = False) -> None:
    if HAS_RICH:
        console.print(rich_markup)
    else:
        stream = sys.stderr if err else sys.stdout
        print(plain_text if plain_text is not None else rich_markup, file=stream)


@contextmanager
def status(rich_msg: str, plain_msg: Optional[str] = None, spinner: str = "dots"):
    if HAS_RICH:
        with console.status(rich_msg, spinner=spinner):
            yield
    else:
        print(plain_msg or rich_msg)
        yield


class _PlainTask:
    def update(self, description: Optional[str] = None, advance: float = 0) -> None:
        del advance
        if description:
            print(description)

    def advance(self, step: float = 1) -> None:
        del step


@contextmanager
def step_progress(description: str, total: Optional[float] = None, download: bool = False):
    if not HAS_RICH:
        print(description)
        yield _PlainTask()
        return

    columns = [SpinnerColumn(spinner_name="dots", style="bold cyan")]
    columns.append(TextColumn("[bold cyan]{task.description}"))
    columns.append(
        BarColumn(
            bar_width=35,
            style="dim white",
            complete_style="green" if download else "bold cyan",
            finished_style="bold green",
        )
    )
    if download:
        columns.extend([DownloadColumn(), TransferSpeedColumn(), TimeRemainingColumn()])
    else:
        columns.extend([TaskProgressColumn(), TimeElapsedColumn()])

    with Progress(*columns, console=console, transient=False) as prog:
        task_id = prog.add_task(description, total=total)

        class _RichTask:
            def update(self, desc: Optional[str] = None, advance: float = 0) -> None:
                kwargs = {}
                if desc is not None:
                    kwargs["description"] = desc
                if advance:
                    kwargs["advance"] = advance
                prog.update(task_id, **kwargs)

            def advance(self, step: float = 1) -> None:
                prog.advance(task_id, step)

        yield _RichTask()
