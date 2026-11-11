"""Start the SmartPad text editor."""

import sqlite3
import tkinter as tk
from tkinter import messagebox

from editor import SmartPad


def main() -> None:
    """Create the application window and start Tkinter's event loop."""
    root = tk.Tk()
    try:
        SmartPad(root)
    except (OSError, sqlite3.Error, tk.TclError) as error:
        messagebox.showerror(
            "SmartPad could not start",
            f"The application could not initialize:\n{error}",
            parent=root,
        )
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
