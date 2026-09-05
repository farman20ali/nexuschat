import sys
from tkinter import ttk

# Catppuccin Mocha / Tokyo Night inspired palette
BG = "#1e1e2e"
BG_SIDEBAR = "#181825"
BG_RAISED = "#313244"
BG_CARD = "#252739"
BG_INPUT = "#11111b"
FG = "#cdd6f4"
FG_MUTED = "#a6adc8"
FG_SUBTLE = "#6c7086"
ACCENT = "#89b4fa"
ACCENT_DARK = "#74c7ec"
ACCENT_BG = "#1e283d"
DANGER = "#f38ba8"
DANGER_DARK = "#eb6f92"
OK = "#a6e3a1"
WARN = "#f9e2af"
BORDER = "#45475a"
BORDER_SUBTLE = "#313244"
GOLD = "#fab387"
PURPLE = "#cba6f7"
ONLINE = "#a6e3a1"
OFFLINE = "#585b70"

if sys.platform == "win32":
    UI_FONT = "Segoe UI"
elif sys.platform == "darwin":
    UI_FONT = "SF Pro Text"
else:
    UI_FONT = "DejaVu Sans"


def ui_font(size, weight="normal"):
    if weight == "bold":
        return (UI_FONT, size, "bold")
    return (UI_FONT, size)


def apply_theme(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", background=BG, foreground=FG, fieldbackground=BG_INPUT, bordercolor=BORDER)
    style.configure("TFrame", background=BG)
    style.configure("Sidebar.TFrame", background=BG_SIDEBAR)
    style.configure("Header.TFrame", background=BG_SIDEBAR)
    style.configure("Card.TFrame", background=BG_CARD)
    style.configure("Raised.TFrame", background=BG_RAISED)

    style.configure("TLabel", background=BG, foreground=FG, font=ui_font(10))
    style.configure("Sidebar.TLabel", background=BG_SIDEBAR, foreground=FG, font=ui_font(10))
    style.configure("SidebarMuted.TLabel", background=BG_SIDEBAR, foreground=FG_MUTED, font=ui_font(9))
    style.configure("SidebarTitle.TLabel", background=BG_SIDEBAR, foreground=ACCENT, font=ui_font(12, "bold"))
    style.configure("Muted.TLabel", background=BG, foreground=FG_MUTED, font=ui_font(9))
    style.configure("Subtle.TLabel", background=BG, foreground=FG_SUBTLE, font=ui_font(8))
    style.configure("Title.TLabel", background=BG, foreground=ACCENT, font=ui_font(16, "bold"))
    style.configure("Brand.TLabel", background=BG, foreground=ACCENT, font=ui_font(20, "bold"))
    style.configure("Status.TLabel", background=BG, foreground=OK, font=ui_font(9))
    style.configure("AdminBadge.TLabel", background=GOLD, foreground="#11111b", font=ui_font(8, "bold"), padding=(4, 1))

    # Standard Button
    style.configure("TButton", background=BG_RAISED, foreground=FG, padding=(10, 5), font=ui_font(9), borderwidth=0)
    style.map("TButton", background=[("active", ACCENT_DARK), ("pressed", ACCENT)], foreground=[("active", "#11111b")])

    # Accent Button
    style.configure("Accent.TButton", background=ACCENT, foreground="#11111b", padding=(12, 6), font=ui_font(10, "bold"), borderwidth=0)
    style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("pressed", "#b4befe")])

    # Admin Shield Button
    style.configure("Admin.TButton", background="#3e3829", foreground=GOLD, padding=(10, 5), font=ui_font(9, "bold"), borderwidth=1, bordercolor=GOLD)
    style.map("Admin.TButton", background=[("active", GOLD), ("pressed", "#e0a174")], foreground=[("active", "#11111b")])

    # Danger Button
    style.configure("Danger.TButton", background="#3c222c", foreground=DANGER, padding=(10, 5), font=ui_font(9), borderwidth=1, bordercolor=DANGER)
    style.map("Danger.TButton", background=[("active", DANGER)], foreground=[("active", "#11111b")])

    # Small Action Button
    style.configure("Small.TButton", background=BG_RAISED, foreground=FG, padding=(6, 3), font=ui_font(8), borderwidth=0)
    style.map("Small.TButton", background=[("active", ACCENT_DARK)], foreground=[("active", "#11111b")])

    # Entry & Combobox
    style.configure("TEntry", fieldbackground=BG_INPUT, foreground=FG, insertcolor=FG, padding=6)
    style.configure("TCombobox", fieldbackground=BG_INPUT, background=BG_RAISED, foreground=FG, padding=5)
    style.map("TCombobox", fieldbackground=[("readonly", BG_INPUT)])

    # Scrollbar
    style.configure("TScrollbar", background=BG_RAISED, troughcolor=BG, borderwidth=0)

    # Notebook (Tabs)
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=BG_RAISED, foreground=FG_MUTED, padding=(12, 6), font=ui_font(9))
    style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "#11111b")])

    # Treeview (for Admin user management)
    style.configure("Treeview", background=BG_INPUT, foreground=FG, fieldbackground=BG_INPUT, font=ui_font(9), rowheight=26, borderwidth=0)
    style.configure("Treeview.Heading", background=BG_RAISED, foreground=ACCENT, font=ui_font(9, "bold"), padding=5, borderwidth=0)
    style.map("Treeview", background=[("selected", ACCENT_BG)], foreground=[("selected", ACCENT)])

    return style
