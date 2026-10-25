"""Reusable controls and a restrained visual theme built on standard ttk."""

import tkinter as tk
from tkinter import ttk


COLORS = {
    "window": "#f3f6fb",
    "card": "#ffffff",
    "text": "#1e293b",
    "muted": "#64748b",
    "primary": "#2878d0",
    "primary_hover": "#1d65b5",
    "success": "#16856b",
    "selection": "#e4efff",
}


def configure_theme(root):
    """Configure a portable ttk theme using only Tk's built-in theme engine."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(background=COLORS["window"])
    style.configure("TFrame", background=COLORS["window"])
    style.configure("Card.TFrame", background=COLORS["card"], relief="flat")
    style.configure("TLabel", background=COLORS["window"], foreground=COLORS["text"], font=("Segoe UI", 10))
    style.configure("Card.TLabel", background=COLORS["card"], foreground=COLORS["text"])
    style.configure("Muted.TLabel", background=COLORS["window"], foreground=COLORS["muted"])
    style.configure("CardMuted.TLabel", background=COLORS["card"], foreground=COLORS["muted"])
    style.configure("Hero.TLabel", background=COLORS["window"], foreground="#19324f", font=("Segoe UI", 23, "bold"))
    style.configure("Badge.TLabel", background="#e8f2ff", foreground="#1267d5", padding=(10, 7), font=("Segoe UI", 9, "bold"))
    style.configure("TButton", padding=(12, 8), font=("Segoe UI", 9))
    style.configure("Primary.TButton", background=COLORS["primary"], foreground="#ffffff", padding=(13, 9), font=("Segoe UI", 9, "bold"), borderwidth=0)
    style.map("Primary.TButton", background=[("disabled", "#a8bfd8"), ("active", COLORS["primary_hover"])], foreground=[("disabled", "#f4f7fb")])
    style.configure("Success.TButton", background=COLORS["success"], foreground="#ffffff", padding=(13, 9), font=("Segoe UI", 9, "bold"), borderwidth=0)
    style.map("Success.TButton", background=[("disabled", "#a8c9bf"), ("active", "#116f5a")])
    style.configure("Secondary.TButton", background="#edf3fa", foreground="#315477", padding=(11, 8))
    style.map("Secondary.TButton", background=[("active", "#dce9f7"), ("disabled", "#f1f4f8")])
    style.configure("TEntry", padding=(9, 7), fieldbackground=COLORS["card"], foreground=COLORS["text"])
    style.configure("TCombobox", padding=(7, 6), fieldbackground=COLORS["card"], foreground=COLORS["text"])
    style.map("TCombobox", fieldbackground=[("readonly", COLORS["card"])])
    style.configure("TCheckbutton", background=COLORS["card"], foreground=COLORS["text"], padding=4)
    style.map("TCheckbutton", background=[("active", COLORS["card"])])
    style.configure("Treeview", rowheight=29, font=("Segoe UI", 9), background=COLORS["card"], fieldbackground=COLORS["card"], foreground=COLORS["text"], borderwidth=0)
    style.configure("Treeview.Heading", background="#edf2f8", foreground="#50627a", font=("Segoe UI", 9, "bold"), padding=(8, 8), relief="flat")
    style.map("Treeview", background=[("selected", COLORS["selection"])], foreground=[("selected", "#174e9d")])
    style.configure("Horizontal.TProgressbar", troughcolor="#e4ebf4", background=COLORS["primary"], bordercolor="#e4ebf4", lightcolor=COLORS["primary"], darkcolor=COLORS["primary"])


def center_window(window, parent=None):
    """Center a toplevel and clamp its position to the current display bounds."""
    window.update_idletasks()
    width = max(window.winfo_width(), window.winfo_reqwidth())
    height = max(window.winfo_height(), window.winfo_reqheight())
    screen_width, screen_height = window.winfo_screenwidth(), window.winfo_screenheight()
    if parent is None:
        x, y = (screen_width - width) // 2, (screen_height - height) // 2
    else:
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
    x = max(0, min(x, screen_width - width))
    y = max(0, min(y, screen_height - height))
    window.geometry(f"+{x}+{y}")


class PanelCard(ttk.Frame):
    """Padded reusable surface for grouping related controls."""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("style", "Card.TFrame")
        super().__init__(master, padding=14, **kwargs)


class PrimaryButton(ttk.Button):
    def __init__(self, master, text, command=None, success=False, **kwargs):
        style = "Success.TButton" if success else "Primary.TButton"
        super().__init__(master, text=text, command=command, style=style, cursor="hand2", **kwargs)


class SecondaryButton(ttk.Button):
    def __init__(self, master, text, command=None, **kwargs):
        super().__init__(master, text=text, command=command, style="Secondary.TButton", cursor="hand2", **kwargs)


class LabeledDropdown(ttk.Combobox):
    """Readonly, consistently styled dropdown for filter presets."""

    def __init__(self, master, values, **kwargs):
        super().__init__(master, values=values, state="readonly", cursor="hand2", **kwargs)


class TextInput(ttk.Entry):
    """Reusable single-line text input."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)


class ScrollableFrame(ttk.Frame):
    """A content frame whose height can grow without exceeding its parent."""

    def __init__(self, master, height=300, **kwargs):
        super().__init__(master, **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, background=COLORS["card"])
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.content = ttk.Frame(self.canvas, style="Card.TFrame")
        self._window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._fit_content_width)

    def _update_scroll_region(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_content_width(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)


class CheckOption(ttk.Checkbutton):
    """Reusable pointer-friendly check box with a caller-owned Tk variable."""

    def __init__(self, master, text, variable, **kwargs):
        super().__init__(master, text=text, variable=variable, style="TCheckbutton", cursor="hand2", **kwargs)


class ChoiceDialog(tk.Toplevel):
    """Scrollable modal checkbox dialog that applies changes only on confirmation."""

    def __init__(self, master, title, options, selected, on_apply):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.resizable(True, True)
        self.configure(background=COLORS["window"])
        self.grab_set()
        self.on_apply = on_apply
        self.variables = {}
        screen_width = max(320, self.winfo_screenwidth() - 40)
        screen_height = max(300, self.winfo_screenheight() - 80)
        width, height = min(390, screen_width), min(480, screen_height)
        self.minsize(min(340, width), min(280, height))
        self.geometry(f"{width}x{height}")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ttk.Label(self, text=title, style="Hero.TLabel").grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))
        card = PanelCard(self)
        card.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(0, weight=1)
        options_frame = ScrollableFrame(card, height=320, style="Card.TFrame")
        options_frame.grid(row=0, column=0, sticky="nsew")
        for row, option in enumerate(options):
            variable = tk.BooleanVar(master=self, value=option in selected)
            self.variables[option] = variable
            CheckOption(options_frame.content, option or "(no extension)", variable).grid(row=row, column=0, sticky="w", pady=2)
        if not options:
            ttk.Label(options_frame.content, text="No supported types were found.", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")

        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="e", padx=16, pady=(0, 16))
        SecondaryButton(actions, "Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        PrimaryButton(actions, "Apply", command=self._apply).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, master)

    def _apply(self):
        self.on_apply({option for option, variable in self.variables.items() if variable.get()})
        self.destroy()
