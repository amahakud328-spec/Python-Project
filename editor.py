"""The main SmartPad application window and its editing commands."""

from __future__ import annotations

import os
import json
import queue
import sqlite3
import threading
import tempfile
import tkinter as tk
from tkinter import colorchooser, filedialog, font, messagebox, simpledialog
from typing import Callable

from ai_assistant import AIConfigurationError, AIRequestError, WritingAssistant
from database import SmartPadStore
from features import DOCUMENT_TEMPLATES, convert_case, count_text, current_datetime
from security import (
    EncryptionUnavailableError,
    InvalidDocumentPasswordError,
    decrypt_document,
    encrypt_document,
)
from themes import THEMES
from voice import VoiceController, VoiceFeatureError


class SmartPad:
    """SmartPad student productivity, note management, and text editor."""

    APP_TITLE = "SmartPad – Intelligent Text Editor & Student Productivity Suite"
    AUTOSAVE_SECONDS = 30

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(self.APP_TITLE)
        self.root.geometry("1240x800")
        self.root.minsize(820, 560)

        self.current_path: str | None = None
        self.current_title = "Untitled"
        self.store = SmartPadStore()
        self.active_note_id: int | None = None
        self.active_category = "College Notes"
        self.current_protected = False
        self.current_password: str | None = None
        self.current_salt: bytes | None = None
        self._ai_window: tk.Toplevel | None = None
        self._focus_mode = False
        self._study_seconds = 0
        self._focus_seconds = 0
        self._study_running = False
        self._focus_running = False
        self._timer_job: str | None = None
        self._ui_poll_job: str | None = None
        self._ui_callbacks: queue.Queue[Callable[[], None]] = queue.Queue()
        self.is_dirty = False
        self.theme_name = self.store.get_setting("theme", "dark")
        if self.theme_name not in THEMES:
            self.theme_name = "dark"
        self.word_wrap = tk.BooleanVar(value=True)
        self._autosave_path = os.path.join(
            tempfile.gettempdir(), "smartpad_recovery.txt"
        )
        self.ai_assistant = WritingAssistant()
        self._build_menu()
        self._build_toolbar()
        self._build_editor()
        self._build_sidebar()
        self._build_student_bar()
        self._build_status_bar()
        self._bind_shortcuts()
        self.voice = VoiceController(
            on_text=lambda value: self._queue_ui_callback(
                lambda: self._insert_voice_text(value)
            ),
            on_error=lambda value: self._queue_ui_callback(
                lambda: self._voice_error(value)
            ),
            on_status=lambda value: self._queue_ui_callback(
                lambda: self._set_voice_status(value)
            ),
        )
        self.apply_theme()
        self.show_welcome()
        self.refresh_notes()
        self._restore_student_preferences()
        self._offer_recovery()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._ui_poll_job = self.root.after(100, self._drain_ui_callbacks)
        self.root.after(self.AUTOSAVE_SECONDS * 1000, self._auto_save)

    def _build_menu(self) -> None:
        self.menu_bar = tk.Menu(self.root)

        file_menu = tk.Menu(self.menu_bar, tearoff=False)
        file_menu.add_command(label="New", accelerator="Ctrl+N", command=self.new_file)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Save As…", command=self.save_as)
        self.recent_menu = tk.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="Recent Documents", menu=self.recent_menu)
        file_menu.add_command(label="New Note", command=self.create_note)
        file_menu.add_command(label="Templates…", command=self.insert_template)
        file_menu.add_command(label="Restore Previous Version…", command=self.restore_version)
        file_menu.add_command(label="Manage Backups…", command=self.manage_backups)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close)
        self.menu_bar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(self.menu_bar, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Cut", command=self.cut)
        edit_menu.add_command(label="Copy", command=self.copy)
        edit_menu.add_command(label="Paste", command=self.paste)
        edit_menu.add_command(label="Select All", command=self.select_all)
        edit_menu.add_separator()
        edit_menu.add_command(label="Find and Replace…", accelerator="Ctrl+F", command=self.find_replace)
        self.menu_bar.add_cascade(label="Edit", menu=edit_menu)

        format_menu = tk.Menu(self.menu_bar, tearoff=False)
        format_menu.add_command(label="Font Family…", command=self.choose_font)
        format_menu.add_command(label="Font Size…", command=self.choose_font_size)
        format_menu.add_command(label="Bold", command=self.toggle_bold)
        format_menu.add_command(label="Italic", command=self.toggle_italic)
        format_menu.add_command(label="Text Color…", command=self.choose_text_color)
        format_menu.add_separator()
        format_menu.add_command(label="UPPERCASE", command=lambda: self.change_case("upper"))
        format_menu.add_command(label="lowercase", command=lambda: self.change_case("lower"))
        format_menu.add_command(label="Title Case", command=lambda: self.change_case("title"))
        format_menu.add_command(label="Insert Date and Time", command=self.insert_datetime)
        format_menu.add_command(label="Highlight Selected Text", command=self.highlight_selection)
        self.menu_bar.add_cascade(label="Format", menu=format_menu)

        view_menu = tk.Menu(self.menu_bar, tearoff=False)
        view_menu.add_checkbutton(
            label="Word Wrap",
            variable=self.word_wrap,
            command=self.toggle_word_wrap,
        )
        view_menu.add_command(label="Word / Character / Line Count", command=self.show_counts)
        view_menu.add_command(label="Focus Mode", command=self.toggle_focus_mode)
        self.menu_bar.add_cascade(label="View", menu=view_menu)

        theme_menu = tk.Menu(self.menu_bar, tearoff=False)
        theme_menu.add_command(label="Light Mode", command=lambda: self.set_theme("light"))
        theme_menu.add_command(label="Dark Mode", command=lambda: self.set_theme("dark"))
        self.menu_bar.add_cascade(label="Theme", menu=theme_menu)

        notes_menu = tk.Menu(self.menu_bar, tearoff=False)
        notes_menu.add_command(label="Rename Note…", command=self.rename_note)
        notes_menu.add_command(label="Delete Note…", command=self.delete_note)
        notes_menu.add_command(label="Toggle Favorite", command=self.toggle_favorite)
        notes_menu.add_command(label="Protect / Remove Password…", command=self.protect_note)
        notes_menu.add_command(label="Add Category…", command=self.add_category)
        self.menu_bar.add_cascade(label="Notes", menu=notes_menu)

        student_menu = tk.Menu(self.menu_bar, tearoff=False)
        student_menu.add_command(label="Set Word Target…", command=self.set_word_target)
        student_menu.add_command(label="Start / Pause Study Timer", command=self.toggle_study_timer)
        student_menu.add_command(label="Reset Study Timer", command=self.reset_study_timer)
        student_menu.add_command(label="Start Focus Timer…", command=self.start_focus_timer)
        self.menu_bar.add_cascade(label="Student", menu=student_menu)

        voice_menu = tk.Menu(self.menu_bar, tearoff=False)
        voice_menu.add_command(label="Start Voice Typing", command=self.start_voice_typing)
        voice_menu.add_command(label="Stop Voice Typing", command=self.stop_voice_typing)
        voice_menu.add_command(label="Read Selected Text Aloud", command=self.speak_selection)
        voice_menu.add_command(label="Stop Speech", command=self.stop_speech)
        self.menu_bar.add_cascade(label="Voice", menu=voice_menu)

        self.assistant_menu = tk.Menu(self.menu_bar, tearoff=False)
        self.assistant_menu.add_command(label="Open Writing Assistant", command=self.open_ai_assistant)
        self.menu_bar.add_cascade(label="AI Assistant", menu=self.assistant_menu)
        self.menu_widgets = (
            file_menu,
            self.recent_menu,
            edit_menu,
            format_menu,
            view_menu,
            theme_menu,
            notes_menu,
            student_menu,
            voice_menu,
            self.assistant_menu,
        )
        self.root.config(menu=self.menu_bar)
        self._refresh_recent_menu()

    def _build_toolbar(self) -> None:
        self.toolbar = tk.Frame(self.root, padx=10, pady=8)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        controls = [
            ("＋ Note", self.create_note),
            ("📂 Open", self.open_file),
            ("💾 Save", self.save_file),
            ("⌕ Find", self.find_replace),
            ("✦ AI", self.open_ai_assistant),
            ("🎙 Voice", self.start_voice_typing),
            ("⏹ Stop voice", self.stop_voice_typing),
            ("🔊 Read", self.speak_selection),
            ("◐ Theme", self.toggle_theme),
            ("◎ Focus", self.toggle_focus_mode),
        ]
        self.toolbar_buttons: list[tk.Button] = []
        for label, command in controls:
            button = tk.Button(
                self.toolbar,
                text=label,
                command=command,
                relief=tk.FLAT,
                padx=10,
                pady=5,
                cursor="hand2",
            )
            button.pack(side=tk.LEFT, padx=(0, 6))
            self.toolbar_buttons.append(button)
        self.voice_status = tk.Label(self.toolbar, text="Voice ready", anchor=tk.E)
        self.voice_status.pack(side=tk.RIGHT, padx=8)

    def _build_editor(self) -> None:
        self.workspace = tk.Frame(self.root)
        self.workspace.pack(fill=tk.BOTH, expand=True)
        self.sidebar = tk.Frame(self.workspace, width=245, padx=12, pady=12)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        self.content = tk.Frame(self.workspace)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.welcome = tk.Frame(self.content, padx=30, pady=30)
        self.welcome_title = tk.Label(
            self.welcome,
            text="SmartPad",
            font=("Segoe UI", 30, "bold"),
        )
        self.welcome_title.pack(pady=(70, 8))
        self.welcome_subtitle = tk.Label(
            self.welcome,
            text="A calm, capable space for your notes and ideas.",
            font=("Segoe UI", 12),
        )
        self.welcome_subtitle.pack(pady=(0, 24))
        self.dashboard_metrics = tk.Frame(self.welcome)
        self.dashboard_metrics.pack(pady=(0, 18))
        self.dashboard_note_count = tk.Label(
            self.dashboard_metrics, text="0 notes", font=("Segoe UI", 11, "bold")
        )
        self.dashboard_note_count.pack(side=tk.LEFT, padx=14)
        self.dashboard_favorite_count = tk.Label(
            self.dashboard_metrics, text="0 favorites", font=("Segoe UI", 11, "bold")
        )
        self.dashboard_favorite_count.pack(side=tk.LEFT, padx=14)
        self.dashboard_recent_count = tk.Label(
            self.dashboard_metrics, text="Recently opened notes appear in the sidebar",
            font=("Segoe UI", 10),
        )
        self.dashboard_recent_count.pack(side=tk.LEFT, padx=14)
        welcome_actions = tk.Frame(self.welcome)
        welcome_actions.pack()
        self.welcome_new = tk.Button(
            welcome_actions, text="Create a new document", command=self.new_file
        )
        self.welcome_new.pack(side=tk.LEFT, padx=6)
        self.welcome_open = tk.Button(
            welcome_actions, text="Open a text file", command=self.open_file
        )
        self.welcome_open.pack(side=tk.LEFT, padx=6)

        self.editor_frame = tk.Frame(self.content)
        self.focus_bar = tk.Frame(self.editor_frame, padx=16, pady=8)
        self.focus_exit = tk.Button(
            self.focus_bar, text="← Exit focus", command=self.toggle_focus_mode
        )
        self.focus_exit.pack(side=tk.LEFT)
        self.focus_word_count = tk.Label(self.focus_bar, text="Words: 0")
        self.focus_word_count.pack(side=tk.LEFT, padx=14)
        self.focus_timer_label = tk.Label(self.focus_bar, text="Focus session")
        self.focus_timer_label.pack(side=tk.RIGHT, padx=10)
        self.focus_color_button = tk.Button(
            self.focus_bar, text="Writing background", command=self.choose_focus_background
        )
        self.focus_color_button.pack(side=tk.RIGHT)
        self.text = tk.Text(
            self.editor_frame,
            wrap=tk.WORD,
            undo=True,
            maxundo=-1,
            padx=24,
            pady=20,
            font=("Consolas", 12),
            borderwidth=0,
            insertwidth=2,
            tabs=("4c",),
        )
        self.scrollbar = tk.Scrollbar(
            self.editor_frame, orient=tk.VERTICAL, command=self.text.yview
        )
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.bind("<<Modified>>", self._on_text_modified)
        self.text.bind("<KeyRelease>", self._update_status)
        self.text.bind("<ButtonRelease-1>", self._update_status)
        self.text.tag_configure("important", background=THEMES["dark"]["highlight"])
        self.text.bind("<Control-Shift-a>", lambda _event: self.open_ai_assistant())

    def _build_sidebar(self) -> None:
        self.sidebar_heading = tk.Label(
            self.sidebar, text="✦  SMARTPAD", anchor=tk.W,
            font=("Segoe UI", 13, "bold"),
        )
        self.sidebar_heading.pack(fill=tk.X, pady=(4, 18))
        self.sidebar_new = tk.Button(
            self.sidebar, text="＋  New note", command=self.create_note, anchor=tk.W
        )
        self.sidebar_new.pack(fill=tk.X, pady=(0, 12))
        self.search_entry = tk.Entry(self.sidebar)
        self.search_entry.insert(0, "Search notes…")
        self.search_entry.pack(fill=tk.X, pady=(0, 10), ipady=5)
        self.search_entry.bind("<KeyRelease>", lambda _event: self.refresh_notes())
        self.category_var = tk.StringVar(value="All Notes")
        self.category_menu = tk.OptionMenu(
            self.sidebar, self.category_var, "All Notes",
            *self.store.list_categories(), command=lambda _value: self.refresh_notes()
        )
        self.category_menu.pack(fill=tk.X, pady=(0, 10))
        self.notes_heading = tk.Label(self.sidebar, text="YOUR NOTES", anchor=tk.W)
        self.notes_heading.pack(fill=tk.X, pady=(8, 5))
        list_frame = tk.Frame(self.sidebar)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.notes_list = tk.Listbox(
            list_frame, borderwidth=0, highlightthickness=0, activestyle="none"
        )
        notes_scrollbar = tk.Scrollbar(list_frame, command=self.notes_list.yview)
        self.notes_list.configure(yscrollcommand=notes_scrollbar.set)
        self.notes_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        notes_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.notes_list.bind("<Double-Button-1>", lambda _event: self.open_selected_note())
        self.notes_list.bind("<Return>", lambda _event: self.open_selected_note())
        self.notes_list.bind("<Button-3>", self._show_note_context_menu)
        action_row = tk.Frame(self.sidebar)
        self.sidebar_actions = action_row
        action_row.pack(fill=tk.X, pady=(8, 0))
        for label, action in (
            ("Rename", self.rename_note),
            ("★", self.toggle_favorite),
            ("Delete", self.delete_note),
        ):
            button = tk.Button(action_row, text=label, command=action, padx=5)
            button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.sidebar_category = tk.Button(
            self.sidebar, text="＋  Add category", command=self.add_category, anchor=tk.W
        )
        self.sidebar_category.pack(fill=tk.X, pady=(12, 0))

    def _build_student_bar(self) -> None:
        self.student_bar = tk.Frame(self.content, padx=12, pady=8)
        self.student_bar.pack(side=tk.TOP, fill=tk.X)
        self.student_mode = tk.BooleanVar(value=True)
        self.student_toggle = tk.Checkbutton(
            self.student_bar, text="Student Mode", variable=self.student_mode,
            command=self._toggle_student_mode, anchor=tk.W,
        )
        self.student_toggle.pack(side=tk.LEFT)
        self.target_button = tk.Button(
            self.student_bar, text="Set word target", command=self.set_word_target
        )
        self.target_button.pack(side=tk.LEFT, padx=(12, 6))
        self.assignment_status = tk.Label(self.student_bar, text="Target: 0 words")
        self.assignment_status.pack(side=tk.LEFT, padx=8)
        self.study_button = tk.Button(
            self.student_bar, text="Start study timer", command=self.toggle_study_timer
        )
        self.study_button.pack(side=tk.RIGHT, padx=4)
        self.study_clock = tk.Label(self.student_bar, text="Study 00:00:00")
        self.study_clock.pack(side=tk.RIGHT, padx=8)
        self.focus_clock = tk.Label(self.student_bar, text="Focus —")
        self.focus_clock.pack(side=tk.RIGHT, padx=8)

    def _build_status_bar(self) -> None:
        self.status_bar = tk.Frame(self.root, padx=12, pady=6)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.document_status = tk.Label(self.status_bar, anchor=tk.W)
        self.document_status.pack(side=tk.LEFT)
        self.position_status = tk.Label(self.status_bar, anchor=tk.E)
        self.position_status.pack(side=tk.RIGHT, padx=(12, 0))
        self.count_status = tk.Label(self.status_bar, anchor=tk.E)
        self.count_status.pack(side=tk.RIGHT)

    def _bind_shortcuts(self) -> None:
        shortcuts = {
            "<Control-n>": self.new_file,
            "<Control-o>": self.open_file,
            "<Control-s>": self.save_file,
            "<Control-f>": self.find_replace,
            "<Control-z>": self.undo,
            "<Control-y>": self.redo,
        }
        for sequence, command in shortcuts.items():
            self.root.bind_all(sequence, lambda _event, action=command: self._run_shortcut(action))

    def _run_shortcut(self, command: Callable[[], None]) -> str:
        command()
        return "break"

    def show_welcome(self) -> None:
        self.editor_frame.pack_forget()
        self.welcome.pack(fill=tk.BOTH, expand=True)
        notes = self.store.list_notes()
        self.dashboard_note_count.config(text=f"{len(notes)} saved notes")
        self.dashboard_favorite_count.config(
            text=f"{sum(bool(note['favorite']) for note in notes)} favorites"
        )
        recent = [note["title"] for note in notes[:3]]
        self.dashboard_recent_count.config(
            text=(
                "Recent: " + " · ".join(recent)
                if recent else "Your recently opened notes will appear in the sidebar."
            )
        )
        self._update_status()

    def show_editor(self) -> None:
        self.welcome.pack_forget()
        self.editor_frame.pack(fill=tk.BOTH, expand=True)
        self.text.focus_set()

    def _on_text_modified(self, _event: tk.Event) -> None:
        if self.text.edit_modified():
            self.is_dirty = True
            self.text.edit_modified(False)
            self._update_status()

    def _update_status(self, _event: tk.Event | None = None) -> None:
        modified = self.is_dirty
        if self.active_note_id is not None:
            name = self.current_title
            if self.current_protected:
                name = f"🔒 {name}"
        else:
            name = os.path.basename(self.current_path) if self.current_path else "Untitled"
        self.document_status.config(
            text=f"{name}  •  {'Unsaved changes' if modified else 'Saved'}"
        )
        if self.editor_frame.winfo_ismapped():
            position = self.text.index(tk.INSERT).split(".")
            self.position_status.config(
                text=f"Line {position[0]}, Column {int(position[1]) + 1}"
            )
        else:
            self.position_status.config(text="Welcome")
        counts = count_text(self._get_text())
        self.count_status.config(
            text=f"{counts['words']} words  |  {counts['characters']} characters  |  "
            f"{counts['lines']} lines"
        )
        self.focus_word_count.config(text=f"Words: {counts['words']}")
        self._update_student_progress(counts["words"])
        self.root.title(
            f"{'* ' if modified else ''}{name} — {self.APP_TITLE}"
        )

    def _get_text(self) -> str:
        return self.text.get("1.0", "end-1c")

    def _set_text(self, value: str, modified: bool = False) -> None:
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", value)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.is_dirty = modified
        self._update_status()

    def _confirm_discard_or_save(self) -> bool:
        if not self.is_dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes",
            "Save changes before continuing?",
            parent=self.root,
        )
        if answer is None:
            return False
        if answer:
            return self.save_file()
        return True

    def new_file(self) -> None:
        if not self._confirm_discard_or_save():
            return
        self.current_path = None
        self.current_title = "Untitled"
        self.active_note_id = None
        self.active_category = self._selected_category()
        self.current_protected = False
        self.current_password = None
        self.current_salt = None
        self._set_text("")
        self.show_editor()

    def open_file(self) -> None:
        if not self._confirm_discard_or_save():
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Open text file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as file:
                content = file.read()
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Open failed", f"Could not open this file:\n{error}", parent=self.root)
            return
        self.current_path = path
        self.current_title = os.path.basename(path)
        self._remember_file(path)
        self.active_note_id = None
        self.current_protected = False
        self.current_password = None
        self.current_salt = None
        self._set_text(content)
        self.show_editor()

    def save_file(self) -> bool:
        if self.active_note_id is not None:
            return self._save_note()
        if self.current_path is None:
            return self.save_as()
        return self._write_file(self.current_path)

    def save_as(self) -> bool:
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save text file",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return False
        if self.current_protected and not messagebox.askyesno(
            "Save an unprotected copy",
            "Save As writes a plain-text copy without the note password. Continue?",
            parent=self.root,
        ):
            return False
        if self._write_file(path):
            self.active_note_id = None
            self.current_protected = False
            self.current_password = None
            self.current_salt = None
            self.current_path = path
            self.current_title = os.path.basename(path)
            self._remember_file(path)
            self._update_status()
            return True
        return False

    def _write_file(self, path: str) -> bool:
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as existing_file:
                    old_content = existing_file.read()
                if old_content != self._get_text():
                    self.store.add_file_revision(path, old_content)
            with open(path, "w", encoding="utf-8", newline="") as file:
                file.write(self._get_text())
        except (OSError, UnicodeError, sqlite3.Error) as error:
            messagebox.showerror("Save failed", f"Could not save this file:\n{error}", parent=self.root)
            return False
        self.is_dirty = False
        self.text.edit_modified(False)
        self._remove_recovery_file()
        self._update_status()
        return True

    def close(self) -> None:
        if not self._confirm_discard_or_save():
            return
        self.voice.shutdown()
        if self._timer_job is not None:
            self.root.after_cancel(self._timer_job)
        if self._ui_poll_job is not None:
            self.root.after_cancel(self._ui_poll_job)
        self._remove_recovery_file()
        self.root.destroy()

    def undo(self) -> None:
        try:
            self.text.edit_undo()
        except tk.TclError:
            self.root.bell()

    def redo(self) -> None:
        try:
            self.text.edit_redo()
        except tk.TclError:
            self.root.bell()

    def cut(self) -> None:
        self.text.event_generate("<<Cut>>")

    def copy(self) -> None:
        self.text.event_generate("<<Copy>>")

    def paste(self) -> None:
        self.text.event_generate("<<Paste>>")

    def select_all(self) -> str:
        self.text.tag_add(tk.SEL, "1.0", tk.END)
        self.text.mark_set(tk.INSERT, "1.0")
        self.text.see(tk.INSERT)
        return "break"

    def find_replace(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Find and Replace")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)

        tk.Label(dialog, text="Find:").grid(row=0, column=0, padx=10, pady=8, sticky="w")
        find_entry = tk.Entry(dialog, width=34)
        find_entry.grid(row=0, column=1, padx=10, pady=8, sticky="ew")
        tk.Label(dialog, text="Replace with:").grid(
            row=1, column=0, padx=10, pady=8, sticky="w"
        )
        replace_entry = tk.Entry(dialog, width=34)
        replace_entry.grid(row=1, column=1, padx=10, pady=8, sticky="ew")
        case_sensitive = tk.BooleanVar(value=False)
        tk.Checkbutton(dialog, text="Match case", variable=case_sensitive).grid(
            row=2, column=1, padx=10, sticky="w"
        )

        def find_next() -> None:
            query = find_entry.get()
            if not query:
                return
            start = self.text.index(tk.INSERT)
            options = {"nocase": not case_sensitive.get()}
            found = self.text.search(query, start, stopindex=tk.END, **options)
            if not found:
                found = self.text.search(query, "1.0", stopindex=start, **options)
            if found:
                end = f"{found}+{len(query)}c"
                self.text.tag_remove(tk.SEL, "1.0", tk.END)
                self.text.tag_add(tk.SEL, found, end)
                self.text.mark_set(tk.INSERT, end)
                self.text.see(found)
                self.text.focus_set()
            else:
                messagebox.showinfo("Find", "No more matches were found.", parent=dialog)

        def replace_one() -> None:
            query = find_entry.get()
            if not query:
                return
            selected = self.text.tag_ranges(tk.SEL)
            if selected and self.text.get(*selected).casefold() == query.casefold():
                if case_sensitive.get() and self.text.get(*selected) != query:
                    find_next()
                    return
                self.text.delete(*selected)
                self.text.insert(tk.INSERT, replace_entry.get())
            find_next()

        def replace_all() -> None:
            query = find_entry.get()
            if not query:
                return
            content = self._get_text()
            if case_sensitive.get():
                updated = content.replace(query, replace_entry.get())
            else:
                import re

                updated = re.sub(re.escape(query), lambda _match: replace_entry.get(), content, flags=re.IGNORECASE)
            if updated != content:
                self.text.edit_separator()
                self.text.replace("1.0", tk.END, updated)
                self.text.edit_separator()

        button_row = tk.Frame(dialog)
        button_row.grid(row=3, column=0, columnspan=2, pady=10)
        tk.Button(button_row, text="Find Next", command=find_next).pack(side=tk.LEFT, padx=4)
        tk.Button(button_row, text="Replace", command=replace_one).pack(side=tk.LEFT, padx=4)
        tk.Button(button_row, text="Replace All", command=replace_all).pack(side=tk.LEFT, padx=4)
        find_entry.focus_set()
        dialog.bind("<Return>", lambda _event: find_next())
        self._apply_popup_theme(dialog)

    def show_counts(self) -> None:
        counts = count_text(self._get_text())
        messagebox.showinfo(
            "Document Statistics",
            f"Words: {counts['words']}\n"
            f"Characters: {counts['characters']}\n"
            f"Lines: {counts['lines']}",
            parent=self.root,
        )

    def choose_font(self) -> None:
        available = sorted(set(font.families(self.root)), key=str.casefold)
        selected = simpledialog.askstring(
            "Font Family",
            "Enter a font family name (for example: Consolas, Arial, or Segoe UI):",
            initialvalue=font.Font(font=self.text.cget("font")).cget("family"),
            parent=self.root,
        )
        if selected is None:
            return
        if selected.casefold() not in {family.casefold() for family in available}:
            messagebox.showerror("Font not found", f"'{selected}' is not an available font.", parent=self.root)
            return
        current = font.Font(font=self.text.cget("font"))
        current.configure(family=selected)
        self.text.configure(font=current)

    def toggle_bold(self) -> None:
        current = font.Font(font=self.text.cget("font"))
        current.configure(weight="normal" if current.cget("weight") == "bold" else "bold")
        self.text.configure(font=current)

    def toggle_italic(self) -> None:
        current = font.Font(font=self.text.cget("font"))
        current.configure(slant="roman" if current.cget("slant") == "italic" else "italic")
        self.text.configure(font=current)

    def choose_font_size(self) -> None:
        current_font = font.Font(font=self.text.cget("font"))
        size = simpledialog.askinteger(
            "Font Size",
            "Choose a font size (6–72):",
            initialvalue=abs(current_font.cget("size")),
            minvalue=6,
            maxvalue=72,
            parent=self.root,
        )
        if size is not None:
            current_font.configure(size=size)
            self.text.configure(font=current_font)

    def choose_text_color(self) -> None:
        selected = colorchooser.askcolor(
            color=self.text.cget("fg"), title="Choose text color", parent=self.root
        )
        if selected and selected[1]:
            self.text.configure(fg=selected[1])

    def toggle_word_wrap(self) -> None:
        self.text.configure(wrap=tk.WORD if self.word_wrap.get() else tk.NONE)

    def insert_datetime(self) -> None:
        self.text.insert(tk.INSERT, current_datetime())
        self.text.focus_set()

    def change_case(self, mode: str) -> None:
        try:
            start, end = self.text.index(tk.SEL_FIRST), self.text.index(tk.SEL_LAST)
        except tk.TclError:
            messagebox.showinfo("Select text", "Select some text first.", parent=self.root)
            return
        selected = self.text.get(start, end)
        self.text.edit_separator()
        self.text.replace(start, end, convert_case(selected, mode))
        self.text.edit_separator()

    def toggle_theme(self) -> None:
        self.set_theme("dark" if self.theme_name == "light" else "light")

    def set_theme(self, name: str) -> None:
        self.theme_name = name
        try:
            self.store.set_setting("theme", name)
        except sqlite3.Error as error:
            messagebox.showwarning(
                "Theme preference not saved",
                f"The theme changed, but SmartPad could not save this preference:\n{error}",
                parent=self.root,
            )
        self.apply_theme()

    def apply_theme(self) -> None:
        palette = THEMES[self.theme_name]
        self.root.configure(bg=palette["window"])
        self.menu_bar.configure(
            bg=palette["toolbar"],
            fg=palette["text"],
            activebackground=palette["accent"],
            activeforeground="#ffffff",
        )
        self._theme_menu(self.menu_bar, palette)
        for frame in (
            self.toolbar,
            self.workspace,
            self.content,
            self.welcome,
            self.dashboard_metrics,
            self.editor_frame,
            self.status_bar,
            self.student_bar,
            self.focus_bar,
            self.sidebar_actions,
        ):
            frame.configure(bg=palette["window"])
        self.toolbar.configure(bg=palette["toolbar"])
        for button in self.toolbar_buttons:
            button.configure(
                bg=palette["surface"],
                fg=palette["text"],
                activebackground=palette["accent"],
                activeforeground="#ffffff",
                highlightthickness=0,
            )
        self.voice_status.configure(bg=palette["toolbar"], fg=palette["muted"])
        self.sidebar.configure(bg=palette["sidebar"])
        self.sidebar_heading.configure(bg=palette["sidebar"], fg=palette["accent"])
        self.notes_heading.configure(bg=palette["sidebar"], fg=palette["muted"])
        self.search_entry.configure(
            bg=palette["surface"], fg=palette["text"], insertbackground=palette["text"],
            relief=tk.FLAT,
        )
        self.category_menu.nametowidget(self.category_menu.cget("menu")).configure(
            bg=palette["toolbar"], fg=palette["text"],
            activebackground=palette["accent"], activeforeground="#ffffff",
        )
        self.notes_list.configure(
            bg=palette["sidebar"], fg=palette["text"],
            selectbackground=palette["accent"], selectforeground="#ffffff",
        )
        self.category_menu.configure(
            bg=palette["surface"], fg=palette["text"],
            activebackground=palette["accent"], activeforeground="#ffffff",
            relief=tk.FLAT,
        )
        for button in (self.sidebar_new, self.sidebar_category):
            button.configure(
                bg=palette["surface"], fg=palette["text"], relief=tk.FLAT,
                activebackground=palette["accent"], activeforeground="#ffffff",
            )
        for button in self.sidebar_actions.winfo_children():
            button.configure(
            bg=palette["surface"], fg=palette["text"], relief=tk.FLAT,
            activebackground=palette["accent"], activeforeground="#ffffff",
            )
        for button in self.sidebar.winfo_children():
            if isinstance(button, tk.Button):
                button.configure(
                    bg=palette["surface"], fg=palette["text"], relief=tk.FLAT,
                    activebackground=palette["accent"], activeforeground="#ffffff",
                )
        self.student_toggle.configure(
            bg=palette["window"], fg=palette["text"], selectcolor=palette["surface"],
            activebackground=palette["window"], activeforeground=palette["text"],
        )
        for widget in (self.target_button, self.study_button):
            widget.configure(
                bg=palette["surface"], fg=palette["text"], relief=tk.FLAT,
                activebackground=palette["accent"], activeforeground="#ffffff",
            )
        for widget in (self.assignment_status, self.study_clock, self.focus_clock):
            widget.configure(bg=palette["window"], fg=palette["muted"])
        self.focus_word_count.configure(bg=palette["window"], fg=palette["text"])
        self.text.tag_configure("important", background=palette["highlight"])
        for widget in (self.focus_exit, self.focus_color_button):
            widget.configure(
                bg=palette["surface"], fg=palette["text"], relief=tk.FLAT,
                activebackground=palette["accent"], activeforeground="#ffffff",
            )
        self.focus_timer_label.configure(bg=palette["window"], fg=palette["muted"])
        if not self._focus_mode or not getattr(self, "focus_background", None):
            self.text.configure(bg=palette["surface"])
        for label in (
            self.welcome_title, self.welcome_subtitle,
            self.dashboard_note_count, self.dashboard_favorite_count,
            self.dashboard_recent_count,
        ):
            label.configure(bg=palette["window"], fg=palette["text"])
        for button in (self.welcome_new, self.welcome_open):
            button.configure(
                bg=palette["accent"],
                fg="#ffffff",
                activebackground=palette["accent_hover"],
                activeforeground="#ffffff",
                padx=14,
                pady=9,
                relief=tk.FLAT,
                cursor="hand2",
            )
        self.text.configure(
            bg=(
                self.focus_background
                if self._focus_mode and getattr(self, "focus_background", None)
                else palette["surface"]
            ),
            fg=palette["text"],
            insertbackground=palette["text"],
            selectbackground=palette["selection"],
        )
        self.scrollbar.configure(
            bg=palette["toolbar"],
            troughcolor=palette["surface"],
            activebackground=palette["accent"],
        )
        for label in (self.document_status, self.position_status, self.count_status):
            label.configure(bg=palette["window"], fg=palette["muted"])

    def _theme_menu(self, menu: tk.Menu, palette: dict[str, str]) -> None:
        menu.configure(
            bg=palette["toolbar"],
            fg=palette["text"],
            activebackground=palette["accent"],
            activeforeground="#ffffff",
        )
        for item in menu.winfo_children():
            if isinstance(item, tk.Menu):
                self._theme_menu(item, palette)
        for item in getattr(self, "menu_widgets", ()):
            item.configure(
                bg=palette["toolbar"],
                fg=palette["text"],
                activebackground=palette["accent"],
                activeforeground="#ffffff",
            )

    def _selected_category(self) -> str:
        category = self.category_var.get() if hasattr(self, "category_var") else "College Notes"
        return "College Notes" if category == "All Notes" else category

    def refresh_notes(self) -> None:
        query = self.search_entry.get().strip()
        if query == "Search notes…":
            query = ""
        try:
            notes = self.store.list_notes(query, self.category_var.get())
        except sqlite3.Error as error:
            messagebox.showerror("Notes unavailable", f"Could not load notes:\n{error}", parent=self.root)
            return
        self._note_ids = []
        self.notes_list.delete(0, tk.END)
        active_index = None
        for note in notes:
            marker = "★ " if note["favorite"] else ""
            lock = "🔒 " if note["encrypted"] else ""
            self.notes_list.insert(tk.END, f"{marker}{lock}{note['title']}")
            self._note_ids.append(note["id"])
            if note["id"] == self.active_note_id:
                active_index = len(self._note_ids) - 1
        if active_index is not None:
            self.notes_list.selection_set(active_index)

    def _recent_files(self) -> list[str]:
        try:
            values = json.loads(self.store.get_setting("recent_files", "[]"))
        except (json.JSONDecodeError, sqlite3.Error):
            return []
        if not isinstance(values, list):
            return []
        return [value for value in values if isinstance(value, str) and os.path.isfile(value)]

    def _remember_file(self, path: str) -> None:
        recent = [path, *[item for item in self._recent_files() if item != path]][:8]
        self.store.set_setting("recent_files", json.dumps(recent))
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        if not hasattr(self, "recent_menu"):
            return
        self.recent_menu.delete(0, tk.END)
        recent = self._recent_files()
        if not recent:
            self.recent_menu.add_command(label="No recent documents", state=tk.DISABLED)
            return
        for path in recent:
            self.recent_menu.add_command(
                label=os.path.basename(path),
                command=lambda value=path: self._open_recent_file(value),
            )

    def _open_recent_file(self, path: str) -> None:
        if not self._confirm_discard_or_save():
            return
        try:
            with open(path, "r", encoding="utf-8") as file:
                content = file.read()
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Open failed", f"Could not open this file:\n{error}", parent=self.root)
            self._refresh_recent_menu()
            return
        self.current_path = path
        self.current_title = os.path.basename(path)
        self._remember_file(path)
        self.active_note_id = None
        self.current_protected = False
        self.current_password = None
        self.current_salt = None
        self._set_text(content)
        self.show_editor()

    def _selected_note_id(self) -> int | None:
        selection = self.notes_list.curselection()
        if not selection:
            return self.active_note_id
        index = selection[0]
        return self._note_ids[index] if index < len(self._note_ids) else None

    def _show_note_context_menu(self, event: tk.Event) -> None:
        index = self.notes_list.nearest(event.y)
        if index < len(self._note_ids):
            self.notes_list.selection_clear(0, tk.END)
            self.notes_list.selection_set(index)
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Open", command=self.open_selected_note)
        menu.add_command(label="Rename", command=self.rename_note)
        menu.add_command(label="Toggle favorite", command=self.toggle_favorite)
        category_menu = tk.Menu(menu, tearoff=False)
        for category in self.store.list_categories():
            category_menu.add_command(
                label=category,
                command=lambda value=category: self.move_note_to_category(value),
            )
        menu.add_cascade(label="Move to category", menu=category_menu)
        menu.add_command(label="Delete", command=self.delete_note)
        menu.tk_popup(event.x_root, event.y_root)

    def move_note_to_category(self, category: str) -> None:
        note_id = self._selected_note_id()
        if note_id is None:
            return
        note = self.store.get_note(note_id)
        if note is None:
            return
        try:
            self.store.update_note(
                note_id, note["title"], note["content"], category,
                bool(note["encrypted"]), note["salt"], keep_revision=False,
            )
        except sqlite3.Error as error:
            messagebox.showerror("Category update failed", str(error), parent=self.root)
            return
        if note_id == self.active_note_id:
            self.active_category = category
        self.refresh_notes()
        self._select_note_in_list(note_id)

    def create_note(self) -> None:
        if not self._confirm_discard_or_save():
            return
        title = simpledialog.askstring(
            "New note", "Note title:", initialvalue="Untitled", parent=self.root
        )
        if title is None:
            return
        try:
            self.active_category = self._selected_category()
            self.active_note_id = self.store.create_note(
                title, category=self.active_category
            )
        except sqlite3.Error as error:
            messagebox.showerror("Create note failed", str(error), parent=self.root)
            self.active_note_id = None
            return
        self.current_title = title.strip() or "Untitled"
        self.current_path = None
        self.current_protected = False
        self.current_password = None
        self.current_salt = None
        self._set_text("")
        self.show_editor()
        self.refresh_notes()
        self._select_note_in_list(self.active_note_id)

    def _select_note_in_list(self, note_id: int) -> None:
        if note_id in self._note_ids:
            index = self._note_ids.index(note_id)
            self.notes_list.selection_clear(0, tk.END)
            self.notes_list.selection_set(index)
            self.notes_list.see(index)

    def open_selected_note(self) -> None:
        note_id = self._selected_note_id()
        if note_id is None or not self._confirm_discard_or_save():
            return
        try:
            note = self.store.get_note(note_id)
            if note is None:
                raise KeyError("This note no longer exists.")
            if note["encrypted"]:
                password = simpledialog.askstring(
                    "Protected note", f"Enter the password for “{note['title']}”:",
                    show="*", parent=self.root,
                )
                if password is None:
                    return
                content = decrypt_document(note["content"], password, note["salt"])
            else:
                password = None
                stored = note["content"]
                content = stored.decode("utf-8") if isinstance(stored, bytes) else stored
            self.current_path = None
            self.active_note_id = note_id
            self.current_title = note["title"]
            self.active_category = note["category"]
            self.current_protected = bool(note["encrypted"])
            self.current_password = password
            self.current_salt = note["salt"]
            self.store.mark_opened(note_id)
            self._set_text(content)
            self.show_editor()
            self.refresh_notes()
            self._select_note_in_list(note_id)
        except InvalidDocumentPasswordError as error:
            messagebox.showerror("Cannot unlock note", str(error), parent=self.root)
        except (OSError, UnicodeError, KeyError, EncryptionUnavailableError) as error:
            messagebox.showerror("Open note failed", str(error), parent=self.root)
        except sqlite3.Error as error:
            messagebox.showerror("Open note failed", f"Could not open this note:\n{error}", parent=self.root)

    def _save_note(self, keep_revision: bool = True) -> bool:
        if self.active_note_id is None:
            return False
        note_id = self.active_note_id
        content = self._get_text()
        encrypted = self.current_protected
        salt = self.current_salt
        try:
            if encrypted:
                if not self.current_password:
                    raise ValueError("Unlock the note before saving it.")
                payload, salt = encrypt_document(content, self.current_password)
            else:
                payload = content
            self.store.update_note(
                note_id,
                self.current_title,
                payload,
                self.active_category,
                encrypted,
                salt,
                keep_revision=keep_revision,
            )
        except (EncryptionUnavailableError, ValueError, OSError) as error:
            messagebox.showerror("Save note failed", str(error), parent=self.root)
            return False
        except sqlite3.Error as error:
            messagebox.showerror("Save note failed", f"Could not save this note:\n{error}", parent=self.root)
            return False
        self.current_salt = salt
        self.is_dirty = False
        self.text.edit_modified(False)
        self.store.clear_recovery()
        self.refresh_notes()
        self._update_status()
        return True

    def rename_note(self) -> None:
        note_id = self._selected_note_id()
        if note_id is None:
            messagebox.showinfo("Rename note", "Select a note first.", parent=self.root)
            return
        note = self.store.get_note(note_id)
        if note is None:
            return
        title = simpledialog.askstring(
            "Rename note", "New title:", initialvalue=note["title"], parent=self.root
        )
        if title is None or not title.strip():
            return
        try:
            self.store.rename_note(note_id, title.strip())
        except sqlite3.Error as error:
            messagebox.showerror("Rename failed", str(error), parent=self.root)
            return
        if note_id == self.active_note_id:
            self.current_title = title.strip()
        self.refresh_notes()
        self._select_note_in_list(note_id)
        self._update_status()

    def delete_note(self) -> None:
        note_id = self._selected_note_id()
        if note_id is None:
            messagebox.showinfo("Delete note", "Select a note first.", parent=self.root)
            return
        note = self.store.get_note(note_id)
        if note is None:
            return
        if not messagebox.askyesno(
            "Delete note", f"Delete “{note['title']}” permanently?", parent=self.root
        ):
            return
        if note_id == self.active_note_id and not self._confirm_discard_or_save():
            return
        try:
            self.store.delete_note(note_id)
        except sqlite3.Error as error:
            messagebox.showerror("Delete failed", str(error), parent=self.root)
            return
        if note_id == self.active_note_id:
            self.active_note_id = None
            self.current_title = "Untitled"
            self.current_protected = False
            self.current_password = None
            self.current_salt = None
            self._set_text("")
            self.show_welcome()
        self.refresh_notes()

    def toggle_favorite(self) -> None:
        note_id = self._selected_note_id()
        if note_id is None:
            messagebox.showinfo("Favorite", "Select a note first.", parent=self.root)
            return
        note = self.store.get_note(note_id)
        if note is None:
            return
        try:
            self.store.set_favorite(note_id, not bool(note["favorite"]))
        except sqlite3.Error as error:
            messagebox.showerror("Favorite update failed", str(error), parent=self.root)
            return
        self.refresh_notes()
        self._select_note_in_list(note_id)

    def add_category(self) -> None:
        category = simpledialog.askstring(
            "Add category", "Category name:", parent=self.root
        )
        if category is None:
            return
        try:
            self.store.add_category(category)
        except (ValueError, OSError) as error:
            messagebox.showerror("Category not added", str(error), parent=self.root)
            return
        except sqlite3.Error as error:
            messagebox.showerror("Category not added", f"Could not add category:\n{error}", parent=self.root)
            return
        categories = self.store.list_categories()
        menu = self.category_menu["menu"]
        menu.delete(0, "end")
        for item in ["All Notes", *categories]:
            menu.add_command(
                label=item,
                command=lambda value=item: (
                    self.category_var.set(value), self.refresh_notes()
                ),
            )
        self.category_var.set(category.strip())
        self.active_category = category.strip()
        self.refresh_notes()

    def protect_note(self) -> None:
        if self.active_note_id is None:
            messagebox.showinfo("Password protection", "Create or open a note first.", parent=self.root)
            return
        if self.current_protected:
            if not messagebox.askyesno(
                "Remove password",
                "Remove password protection from this note?",
                parent=self.root,
            ):
                return
            self.current_protected = False
            self.current_password = None
            self.current_salt = None
            self.is_dirty = True
            self._save_note()
            return
        password = simpledialog.askstring(
            "Protect note", "Set a password:", show="*", parent=self.root
        )
        if password is None:
            return
        if not password:
            messagebox.showerror("Password required", "Choose a non-empty password.", parent=self.root)
            return
        confirmation = simpledialog.askstring(
            "Confirm password", "Enter the password again:", show="*", parent=self.root
        )
        if confirmation is None:
            return
        if password != confirmation:
            messagebox.showerror("Password mismatch", "The passwords did not match.", parent=self.root)
            return
        try:
            encrypt_document(self._get_text(), password)
        except EncryptionUnavailableError as error:
            messagebox.showerror("Encryption unavailable", str(error), parent=self.root)
            return
        self.store.clear_revisions(self.active_note_id)
        self.current_protected = True
        self.current_password = password
        self.is_dirty = True
        if self._save_note(keep_revision=False):
            messagebox.showinfo(
                "Note protected",
                "The note and future versions are encrypted. The password cannot be recovered if lost.",
                parent=self.root,
            )

    def restore_version(self) -> None:
        if self.active_note_id is not None:
            revisions = self.store.revisions(self.active_note_id)
            source = "note"
        elif self.current_path:
            revisions = self.store.file_revisions(self.current_path)
            source = "file"
        else:
            messagebox.showinfo(
                "Version history", "Open a saved note or file first.", parent=self.root
            )
            return
        if not revisions:
            messagebox.showinfo("Version history", "No previous versions are available yet.", parent=self.root)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Restore previous version")
        dialog.transient(self.root)
        dialog.grab_set()
        listbox = tk.Listbox(dialog, width=48, height=10)
        listbox.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        for revision in revisions:
            is_encrypted = revision.get("encrypted", False)
            label = "Encrypted version" if is_encrypted else "Version"
            listbox.insert(tk.END, f"{revision['created_at']}  {label}")

        def restore() -> None:
            selection = listbox.curselection()
            if not selection:
                messagebox.showinfo("Restore version", "Select a version first.", parent=dialog)
                return
            try:
                if source == "file":
                    content = self.store.get_file_revision(
                        revisions[selection[0]]["id"]
                    )
                else:
                    revision = self.store.get_revision(revisions[selection[0]]["id"])
                    if revision["encrypted"]:
                        password = simpledialog.askstring(
                            "Protected version", "Enter this note's password:",
                            show="*", parent=dialog,
                        )
                        if password is None:
                            return
                        content = decrypt_document(
                            revision["content"], password, revision["salt"]
                        )
                    else:
                        value = revision["content"]
                        content = value.decode("utf-8") if isinstance(value, bytes) else value
            except (InvalidDocumentPasswordError, EncryptionUnavailableError) as error:
                messagebox.showerror("Restore failed", str(error), parent=dialog)
                return
            except (sqlite3.Error, OSError, UnicodeError, KeyError) as error:
                messagebox.showerror("Restore failed", str(error), parent=dialog)
                return
            self._set_text(content, modified=True)
            dialog.destroy()
            self.text.focus_set()

        tk.Button(dialog, text="Restore selected version", command=restore).pack(pady=(0, 12))
        self._apply_popup_theme(dialog)

    def manage_backups(self) -> None:
        if self.active_note_id is not None:
            revisions = self.store.revisions(self.active_note_id)
        elif self.current_path:
            revisions = self.store.file_revisions(self.current_path)
        else:
            revisions = []
        recovery = self.store.get_recovery()
        dialog = tk.Toplevel(self.root)
        dialog.title("Backup manager")
        dialog.transient(self.root)
        dialog.grab_set()
        tk.Label(
            dialog,
            text=f"{len(revisions)} previous version(s) for this document.",
            anchor=tk.W,
        ).pack(fill=tk.X, padx=14, pady=(14, 8))
        history = tk.Listbox(dialog, width=58, height=10)
        history.pack(fill=tk.BOTH, expand=True, padx=14, pady=8)
        for revision in revisions:
            history.insert(tk.END, revision["created_at"])
        if recovery:
            tk.Label(
                dialog,
                text=f"Recovery draft saved: {recovery['saved_at']}",
                anchor=tk.W,
            ).pack(fill=tk.X, padx=14, pady=5)

        def clear_versions() -> None:
            if not revisions:
                messagebox.showinfo("Backup manager", "There are no document versions to clear.", parent=dialog)
                return
            if not messagebox.askyesno(
                "Clear versions",
                "Permanently remove every previous version for this document?",
                parent=dialog,
            ):
                return
            try:
                if self.active_note_id is not None:
                    self.store.clear_revisions(self.active_note_id)
                elif self.current_path:
                    self.store.clear_file_revisions(self.current_path)
                history.delete(0, tk.END)
                messagebox.showinfo("Backup manager", "Previous versions cleared.", parent=dialog)
                dialog.destroy()
            except sqlite3.Error as error:
                messagebox.showerror("Backup manager", str(error), parent=dialog)

        def clear_recovery() -> None:
            if not recovery:
                return
            if messagebox.askyesno(
                "Clear recovery", "Permanently remove the recovery draft?", parent=dialog
            ):
                try:
                    self._remove_recovery_file()
                    dialog.destroy()
                except sqlite3.Error as error:
                    messagebox.showerror("Backup manager", str(error), parent=dialog)

        button_row = tk.Frame(dialog)
        button_row.pack(fill=tk.X, padx=14, pady=(8, 14))
        tk.Button(button_row, text="Restore version…", command=self.restore_version).pack(side=tk.LEFT)
        tk.Button(button_row, text="Clear versions", command=clear_versions).pack(side=tk.LEFT, padx=8)
        tk.Button(button_row, text="Clear recovery draft", command=clear_recovery).pack(side=tk.LEFT)
        self._apply_popup_theme(dialog)

    def insert_template(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Document templates")
        dialog.transient(self.root)
        dialog.grab_set()
        tk.Label(dialog, text="Choose a template to insert:").pack(padx=16, pady=(16, 8))
        choice = tk.StringVar(value=next(iter(DOCUMENT_TEMPLATES)))
        menu = tk.OptionMenu(dialog, choice, *DOCUMENT_TEMPLATES.keys())
        menu.pack(fill=tk.X, padx=16, pady=8)

        def insert() -> None:
            template = DOCUMENT_TEMPLATES[choice.get()]
            if self._get_text() and not messagebox.askyesno(
                "Insert template", "Insert this template at the cursor?", parent=dialog
            ):
                return
            self.text.insert(tk.INSERT, template)
            self.text.focus_set()
            dialog.destroy()

        tk.Button(dialog, text="Insert template", command=insert).pack(pady=12)
        self._apply_popup_theme(dialog)

    def open_ai_assistant(self) -> None:
        if self._ai_window is not None and self._ai_window.winfo_exists():
            self._ai_window.deiconify()
            self._ai_window.lift()
            return
        dialog = tk.Toplevel(self.root)
        self._ai_window = dialog
        dialog.title("SmartPad Writing Assistant")
        dialog.geometry("620x560")
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        tk.Label(
            dialog, text="Writing Assistant",
            font=("Segoe UI", 16, "bold"), anchor=tk.W,
        ).pack(fill=tk.X, padx=16, pady=(16, 5))
        tk.Label(
            dialog,
            text=(
                "Choose an action. Selected editor text is loaded below. "
                "Text is sent to the configured AI provider when you generate."
            ),
            anchor=tk.W, justify=tk.LEFT,
        ).pack(fill=tk.X, padx=16, pady=(0, 10))
        action = tk.StringVar(value="Improve writing")
        tk.OptionMenu(dialog, action, *(
            "Correct grammar", "Improve writing", "Rewrite selected text",
            "Summarize", "Explain difficult words", "Generate paragraph",
        )).pack(fill=tk.X, padx=16, pady=(0, 10))
        tk.Label(dialog, text="Text or topic:", anchor=tk.W).pack(fill=tk.X, padx=16)
        input_box = tk.Text(dialog, height=8, wrap=tk.WORD)
        input_box.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 10))
        try:
            input_box.insert("1.0", self.text.get(tk.SEL_FIRST, tk.SEL_LAST))
        except tk.TclError:
            pass
        tk.Label(dialog, text="Assistant result:", anchor=tk.W).pack(fill=tk.X, padx=16)
        output_box = tk.Text(dialog, height=8, wrap=tk.WORD)
        output_box.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 10))
        status = tk.Label(dialog, text="AI is optional; configure a provider in the README.", anchor=tk.W)
        status.pack(fill=tk.X, padx=16, pady=(0, 6))
        button_row = tk.Frame(dialog)
        button_row.pack(fill=tk.X, padx=16, pady=(0, 14))
        result_ready = {"value": False}

        def run() -> None:
            prompt = input_box.get("1.0", "end-1c")
            selected_action = action.get()
            status.config(text="Contacting configured AI provider…")
            run_button.config(state=tk.DISABLED)

            def work() -> None:
                try:
                    result = self.ai_assistant.run(selected_action, prompt)
                    self._queue_ui_callback(lambda: show_result(result, ""))
                except (AIConfigurationError, AIRequestError, ValueError) as error:
                    message = str(error)
                    self._queue_ui_callback(lambda: show_result("", message))
                except (
                    OSError, RuntimeError, TypeError, KeyError, IndexError, UnicodeError
                ) as error:
                    message = f"AI request failed: {error}"
                    self._queue_ui_callback(lambda: show_result("", message))

            threading.Thread(target=work, daemon=True).start()

        def show_result(result: str, error: str) -> None:
            if not dialog.winfo_exists():
                return
            output_box.delete("1.0", tk.END)
            if error:
                output_box.insert("1.0", error)
                status.config(text="Assistant setup or request failed.")
                result_ready["value"] = False
            else:
                output_box.insert("1.0", result)
                status.config(text="Result ready.")
                result_ready["value"] = True
            run_button.config(state=tk.NORMAL)

        def insert_result(replace: bool = False) -> None:
            if not result_ready["value"]:
                messagebox.showinfo(
                    "No generated result",
                    "Generate a successful assistant result before inserting text.",
                    parent=dialog,
                )
                return
            result = output_box.get("1.0", "end-1c")
            if not result.strip():
                messagebox.showinfo("No result", "Generate a result first.", parent=dialog)
                return
            if replace:
                try:
                    self.text.replace(tk.SEL_FIRST, tk.SEL_LAST, result)
                except tk.TclError:
                    messagebox.showinfo(
                        "Select text", "Select text in the editor to replace it.", parent=dialog
                    )
                    return
            else:
                self.text.insert(tk.INSERT, result)
            self.text.focus_set()

        run_button = tk.Button(button_row, text="Generate", command=run)
        run_button.pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(button_row, text="Insert at cursor", command=insert_result).pack(side=tk.LEFT, padx=4)
        tk.Button(button_row, text="Replace selection", command=lambda: insert_result(True)).pack(side=tk.LEFT, padx=4)
        self._apply_popup_theme(dialog)

    def _queue_ui_callback(self, callback: Callable[[], None]) -> None:
        self._ui_callbacks.put(callback)

    def _drain_ui_callbacks(self) -> None:
        while True:
            try:
                callback = self._ui_callbacks.get_nowait()
            except queue.Empty:
                break
            callback()
        self._ui_poll_job = self.root.after(100, self._drain_ui_callbacks)

    def _apply_popup_theme(self, dialog: tk.Toplevel) -> None:
        palette = THEMES[self.theme_name]
        dialog.configure(bg=palette["window"])

        def style(widget: tk.Widget) -> None:
            if isinstance(widget, (tk.Frame, tk.LabelFrame)):
                widget.configure(bg=palette["window"])
            elif isinstance(widget, tk.Label):
                widget.configure(bg=palette["window"], fg=palette["text"])
            elif isinstance(widget, tk.Text):
                widget.configure(
                    bg=palette["surface"], fg=palette["text"],
                    insertbackground=palette["text"],
                    selectbackground=palette["selection"],
                )
            elif isinstance(widget, (tk.Entry, tk.Listbox)):
                widget.configure(
                    bg=palette["surface"], fg=palette["text"],
                    insertbackground=palette["text"],
                    selectbackground=palette["selection"],
                )
            elif isinstance(widget, (tk.Button, tk.OptionMenu)):
                widget.configure(
                    bg=palette["surface"], fg=palette["text"],
                    activebackground=palette["accent"],
                    activeforeground="#ffffff", relief=tk.FLAT,
                )
                if isinstance(widget, tk.OptionMenu):
                    menu = widget.nametowidget(widget.cget("menu"))
                    menu.configure(
                        bg=palette["toolbar"], fg=palette["text"],
                        activebackground=palette["accent"],
                        activeforeground="#ffffff",
                    )
            elif isinstance(widget, tk.Checkbutton):
                widget.configure(
                    bg=palette["window"], fg=palette["text"],
                    selectcolor=palette["surface"],
                    activebackground=palette["window"],
                )
            for child in widget.winfo_children():
                style(child)

        for child in dialog.winfo_children():
            style(child)

    def start_voice_typing(self) -> None:
        try:
            self.voice.start_listening()
        except VoiceFeatureError as error:
            messagebox.showinfo("Voice typing", str(error), parent=self.root)

    def stop_voice_typing(self) -> None:
        self.voice.stop_listening()

    def speak_selection(self) -> None:
        try:
            text = self.text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            text = self._get_text()
        try:
            self.voice.speak(text)
        except VoiceFeatureError as error:
            messagebox.showinfo("Read aloud", str(error), parent=self.root)

    def stop_speech(self) -> None:
        self.voice.stop_speech()

    def _insert_voice_text(self, text: str) -> None:
        if self.root.winfo_exists():
            self.text.insert(tk.INSERT, text + " ")
            self.text.focus_set()

    def _voice_error(self, message: str) -> None:
        if self.root.winfo_exists():
            self.voice_status.config(text="Voice unavailable")
            messagebox.showwarning("Voice feature", message, parent=self.root)

    def _set_voice_status(self, message: str) -> None:
        if self.root.winfo_exists():
            self.voice_status.config(text=message)

    def set_word_target(self) -> None:
        current = int(self.store.get_setting("word_target", "1000") or "1000")
        target = simpledialog.askinteger(
            "Assignment word target", "Target number of words:",
            initialvalue=current or 1000, minvalue=1, maxvalue=1_000_000,
            parent=self.root,
        )
        if target is not None:
            self.store.set_setting("word_target", str(target))
            self._update_student_progress(count_text(self._get_text())["words"])

    def _restore_student_preferences(self) -> None:
        target = self.store.get_setting("word_target", "1000")
        try:
            self._word_target = max(0, int(target))
        except ValueError:
            self._word_target = 0
        self.student_mode.set(self.store.get_setting("student_mode", "1") == "1")
        self._toggle_student_mode()
        self._update_student_progress(count_text(self._get_text())["words"])

    def _toggle_student_mode(self) -> None:
        if not hasattr(self, "student_bar"):
            return
        self.store.set_setting("student_mode", "1" if self.student_mode.get() else "0")
        if self.student_mode.get():
            self.target_button.pack(side=tk.LEFT, padx=(12, 6))
            self.assignment_status.pack(side=tk.LEFT, padx=8)
            self.study_button.pack(side=tk.RIGHT, padx=4)
            self.study_clock.pack(side=tk.RIGHT, padx=8)
        else:
            self.target_button.pack_forget()
            self.assignment_status.pack_forget()
            self.study_button.pack_forget()
            self.study_clock.pack_forget()

    def _update_student_progress(self, words: int) -> None:
        if not hasattr(self, "assignment_status"):
            return
        target = getattr(self, "_word_target", 1000)
        if target <= 0:
            self.assignment_status.config(text=f"Words written: {words} · Set a target")
            return
        percentage = min(100, round(words / target * 100))
        self.assignment_status.config(
            text=f"Target {target}  ·  {words} written  ·  {percentage}%"
        )

    @staticmethod
    def _format_duration(seconds: int) -> str:
        hours, remainder = divmod(max(0, seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def toggle_study_timer(self) -> None:
        self._study_running = not self._study_running
        self.study_button.config(
            text="Pause study timer" if self._study_running else "Start study timer"
        )
        self._schedule_timer()

    def reset_study_timer(self) -> None:
        self._study_seconds = 0
        self._study_running = False
        self.study_button.config(text="Start study timer")
        self.study_clock.config(text="Study 00:00:00")
        self._schedule_timer()

    def start_focus_timer(self) -> None:
        minutes = simpledialog.askinteger(
            "Focus timer", "Focus duration in minutes:",
            initialvalue=25, minvalue=1, maxvalue=240, parent=self.root,
        )
        if minutes is None:
            return
        self._focus_seconds = minutes * 60
        self._focus_running = True
        self.toggle_focus_mode(True)
        self._schedule_timer()

    def _schedule_timer(self) -> None:
        if self._timer_job is None:
            self._timer_job = self.root.after(1000, self._tick_timers)

    def _tick_timers(self) -> None:
        self._timer_job = None
        if self._study_running:
            self._study_seconds += 1
        self.study_clock.config(
            text=f"Study {self._format_duration(self._study_seconds)}"
        )
        if self._focus_running:
            self._focus_seconds -= 1
            if self._focus_seconds <= 0:
                self._focus_running = False
                self.focus_timer_label.config(text="Focus session complete")
                messagebox.showinfo("Focus complete", "Your focus session is complete.", parent=self.root)
        if self._focus_running:
            self.focus_timer_label.config(
                text=f"Focus {self._format_duration(self._focus_seconds)}"
            )
        self.focus_clock.config(
            text=(
                f"Focus {self._format_duration(self._focus_seconds)}"
                if self._focus_running else "Focus —"
            )
        )
        if self._study_running or self._focus_running:
            self._schedule_timer()

    def toggle_focus_mode(self, force: bool | None = None) -> None:
        enabled = not self._focus_mode if force is None else force
        if enabled == self._focus_mode:
            return
        self._focus_mode = enabled
        if enabled:
            self._normal_font = self.text.cget("font")
            self.toolbar.pack_forget()
            self.sidebar.pack_forget()
            self.student_bar.pack_forget()
            self.status_bar.pack_forget()
            self.root.config(menu="")
            self.focus_bar.pack(fill=tk.X, before=self.text)
            self.text.configure(font=("Segoe UI", 16))
            self.editor_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.focus_bar.pack_forget()
            self.root.config(menu=self.menu_bar)
            self.toolbar.pack(side=tk.TOP, fill=tk.X, before=self.workspace)
            self.sidebar.pack(side=tk.LEFT, fill=tk.Y, before=self.content)
            self.student_bar.pack(side=tk.TOP, fill=tk.X, before=self.editor_frame)
            self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
            self.text.configure(font=getattr(self, "_normal_font", ("Consolas", 12)))
            self.apply_theme()
            self._update_status()
        self.text.focus_set()

    def choose_focus_background(self) -> None:
        palette = THEMES[self.theme_name]
        selected = colorchooser.askcolor(
            color=self.text.cget("bg"), title="Focus writing background", parent=self.root
        )
        if selected and selected[1]:
            self.focus_background = selected[1]
            self.text.configure(bg=self.focus_background)
            self.text.configure(
                insertbackground=THEMES[self.theme_name]["text"],
                selectbackground=palette["selection"],
            )

    def highlight_selection(self) -> None:
        try:
            self.text.tag_add("important", tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            messagebox.showinfo("Highlight", "Select text to highlight it.", parent=self.root)

    def _auto_save(self) -> None:
        try:
            if self.is_dirty:
                if self.active_note_id is not None:
                    self._save_note()
                elif self.current_path:
                    self._write_file(self.current_path)
                else:
                    content: bytes | str = self._get_text()
                    salt = None
                    if self.current_protected and self.current_password:
                        content, salt = encrypt_document(
                            self._get_text(), self.current_password
                        )
                    self.store.save_recovery(
                        None, content, self.current_protected, salt
                    )
        except (OSError, EncryptionUnavailableError) as error:
            messagebox.showwarning(
                "Auto-save unavailable", f"SmartPad could not save a recovery copy:\n{error}",
                parent=self.root,
            )
        except sqlite3.Error as error:
            messagebox.showwarning(
                "Auto-save unavailable", f"Could not auto-save this document:\n{error}",
                parent=self.root,
            )
        finally:
            self.root.after(self.AUTOSAVE_SECONDS * 1000, self._auto_save)

    def _offer_recovery(self) -> None:
        try:
            recovery = self.store.get_recovery()
            if recovery is None and os.path.isfile(self._autosave_path):
                with open(self._autosave_path, "r", encoding="utf-8") as file:
                    recovery = {
                        "content": file.read(),
                        "encrypted": 0,
                        "salt": None,
                        "note_id": None,
                    }
        except (OSError, UnicodeError) as error:
            messagebox.showwarning(
                "Recovery unavailable", f"Could not read the recovery copy:\n{error}",
                parent=self.root,
            )
            return
        except sqlite3.Error as error:
            messagebox.showwarning(
                "Recovery unavailable", f"Could not load recovery data:\n{error}",
                parent=self.root,
            )
            return
        if recovery is None:
            return
        if messagebox.askyesno(
            "Recover draft",
            "A draft from an earlier session was auto-saved. Recover it now?",
            parent=self.root,
        ):
            password = None
            try:
                if recovery["encrypted"]:
                    password = simpledialog.askstring(
                        "Protected recovery", "Enter the document password:",
                        show="*", parent=self.root,
                    )
                    if password is None:
                        return
                    recovered_text = decrypt_document(
                        recovery["content"], password, recovery["salt"]
                    )
                else:
                    stored = recovery["content"]
                    recovered_text = (
                        stored.decode("utf-8") if isinstance(stored, bytes) else stored
                    )
                note_id = recovery.get("note_id")
                note = self.store.get_note(note_id) if note_id else None
                if note:
                    self.active_note_id = note_id
                    self.current_title = note["title"]
                    self.active_category = note["category"]
                    self.current_protected = bool(recovery["encrypted"])
                    self.current_password = password
                    self.current_salt = recovery["salt"]
                else:
                    self.current_path = None
                    self.active_note_id = None
                    self.current_title = "Untitled"
                    self.current_protected = bool(recovery["encrypted"])
                    self.current_password = password
                    self.current_salt = recovery["salt"]
                self._set_text(recovered_text, modified=True)
                self.show_editor()
            except (InvalidDocumentPasswordError, EncryptionUnavailableError) as error:
                messagebox.showerror("Recovery failed", str(error), parent=self.root)
            except (
                sqlite3.Error, OSError, UnicodeError, KeyError, TypeError, ValueError
            ) as error:
                messagebox.showerror(
                    "Recovery failed", f"Could not restore the draft:\n{error}",
                    parent=self.root,
                )
        else:
            self._remove_recovery_file()

    def _remove_recovery_file(self) -> None:
        try:
            self.store.clear_recovery()
            if os.path.exists(self._autosave_path):
                os.remove(self._autosave_path)
        except (OSError, sqlite3.Error) as error:
            messagebox.showwarning(
                "Recovery cleanup failed",
                f"Could not remove the recovery copy:\n{error}",
                parent=self.root,
            )
