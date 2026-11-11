"""Focused tests for SmartPad's persistence and integration logic."""

import os
import json
import tempfile
import tkinter as tk
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

from ai_assistant import AIConfigurationError, WritingAssistant
from database import DEFAULT_CATEGORIES, SmartPadStore
from editor import SmartPad
from features import DOCUMENT_TEMPLATES, convert_case, count_text
from security import InvalidDocumentPasswordError, decrypt_document, encrypt_document
from voice import VoiceController


class FeatureTests(unittest.TestCase):
    def test_text_tools_and_templates(self) -> None:
        self.assertEqual(
            count_text("one two\nthree\n"),
            {"words": 3, "characters": 14, "lines": 3},
        )
        self.assertEqual(convert_case("smart pad", "title"), "Smart Pad")
        self.assertEqual(len(DOCUMENT_TEMPLATES), 6)

    def test_encrypted_content_authenticates_password(self) -> None:
        ciphertext, salt = encrypt_document("private note", "demo-password")
        self.assertNotIn(b"private note", ciphertext)
        self.assertEqual(decrypt_document(ciphertext, "demo-password", salt), "private note")
        with self.assertRaises(InvalidDocumentPasswordError):
            decrypt_document(ciphertext, "incorrect-password", salt)

    def test_assistant_requires_provider_configuration(self) -> None:
        with patch.dict(
            os.environ,
            {"SMARTPAD_AI_BASE_URL": "", "SMARTPAD_AI_MODEL": ""},
        ):
            with self.assertRaises(AIConfigurationError) as error:
                WritingAssistant().run("Improve writing", "sample")
        self.assertIn("SMARTPAD_AI_BASE_URL", str(error.exception))

    def test_assistant_uses_configured_openai_compatible_endpoint(self) -> None:
        received: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                received.update(json.loads(body.decode("utf-8")))
                response = json.dumps(
                    {"choices": [{"message": {"content": "Edited result"}}]}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.dict(
                os.environ,
                {
                    "SMARTPAD_AI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                    "SMARTPAD_AI_MODEL": "test-model",
                    "SMARTPAD_AI_API_KEY": "",
                },
            ):
                result = WritingAssistant().run("Improve writing", "sample")
            self.assertEqual(result, "Edited result")
            self.assertEqual(received["model"], "test-model")
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_voice_typing_reports_missing_microphone(self) -> None:
        errors: list[str] = []
        completed = threading.Event()
        controller = VoiceController(
            on_text=lambda _text: None,
            on_error=lambda message: (errors.append(message), completed.set()),
            on_status=lambda _status: None,
        )
        with patch("speech_recognition.Microphone", side_effect=OSError("permission denied")):
            controller.start_listening()
            self.assertTrue(completed.wait(2))
        self.assertIn("permission denied", errors[0])


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SmartPadStore(os.path.join(self.temp_dir.name, "test.sqlite3"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_notes_categories_favorites_revisions_and_recovery(self) -> None:
        self.assertTrue(set(DEFAULT_CATEGORIES).issubset(self.store.list_categories()))
        note_id = self.store.create_note("Lecture", "first draft", "College Notes")
        self.store.update_note(
            note_id, "Lecture", "revised draft", "Programming", False, None
        )
        note = self.store.get_note(note_id)
        self.assertEqual(note["content"], "revised draft")
        self.assertEqual(len(self.store.revisions(note_id)), 1)
        self.store.set_favorite(note_id, True)
        self.store.mark_opened(note_id)
        self.assertTrue(self.store.list_notes("Lecture")[0]["favorite"])
        self.assertEqual(self.store.list_notes(category="Programming")[0]["id"], note_id)
        self.store.save_recovery(note_id, "recovery text")
        self.assertEqual(self.store.get_recovery()["content"], "recovery text")
        self.store.clear_recovery()
        self.assertIsNone(self.store.get_recovery())

    def test_file_revisions_and_connection_cleanup(self) -> None:
        self.store.add_file_revision("note.txt", "previous")
        revision = self.store.file_revisions("note.txt")[0]
        self.assertEqual(self.store.get_file_revision(revision["id"]), "previous")
        self.store.clear_file_revisions("note.txt")
        self.assertEqual(self.store.file_revisions("note.txt"), [])
        self.temp_dir.cleanup()
        self.assertFalse(os.path.exists(self.store.path))


class EditorSmokeTests(unittest.TestCase):
    def test_notes_encryption_focus_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "smartpad.sqlite3")
            with (
                patch("editor.SmartPadStore", lambda: SmartPadStore(path)),
                patch.object(SmartPad, "_offer_recovery", lambda _self: None),
            ):
                root = tk.Tk()
                root.withdraw()
                try:
                    app = SmartPad(root)
                    with patch("editor.simpledialog.askstring", return_value="Demo note"):
                        app.create_note()
                    app.text.insert("1.0", "Private content")
                    root.update()
                    self.assertTrue(app.save_file())
                    with (
                        patch(
                            "editor.simpledialog.askstring",
                            side_effect=["test-password", "test-password"],
                        ),
                        patch("editor.messagebox.showinfo"),
                    ):
                        app.protect_note()
                    note = app.store.get_note(app.active_note_id)
                    self.assertTrue(note["encrypted"])
                    self.assertNotIn(b"Private content", note["content"])
                    self.assertEqual(
                        decrypt_document(
                            note["content"], "test-password", note["salt"]
                        ),
                        "Private content",
                    )

                    app.current_path = None
                    app.active_note_id = None
                    app._set_text("unsaved recovery", modified=True)
                    app._auto_save()
                    recovery = app.store.get_recovery()
                    self.assertTrue(recovery["encrypted"])
                    self.assertEqual(
                        decrypt_document(
                            recovery["content"],
                            "test-password",
                            recovery["salt"],
                        ),
                        "unsaved recovery",
                    )
                    app._remove_recovery_file()

                    app.toggle_focus_mode(True)
                    root.update()
                    self.assertTrue(app._focus_mode)
                    app.toggle_focus_mode(False)
                    root.update()
                    self.assertFalse(app._focus_mode)

                    app.open_ai_assistant()
                    root.update()
                    dialog = app._ai_window
                    self.assertIsNotNone(dialog)
                    app.ai_assistant.run = lambda *_args: (_ for _ in ()).throw(
                        AIConfigurationError("Provider is not configured.")
                    )

                    def descendants(widget):
                        for child in widget.winfo_children():
                            yield child
                            yield from descendants(child)

                    buttons = [
                        widget for widget in descendants(dialog)
                        if isinstance(widget, tk.Button)
                    ]
                    next(button for button in buttons if button.cget("text") == "Generate").invoke()
                    deadline = time.monotonic() + 2
                    result_ready = False
                    while time.monotonic() < deadline:
                        root.update()
                        if any(
                            "failed" in widget.cget("text")
                            for widget in descendants(dialog)
                            if isinstance(widget, tk.Label)
                        ):
                            result_ready = True
                            break
                        time.sleep(0.01)
                    self.assertTrue(result_ready, "AI setup errors should reach the panel")
                    with patch("editor.messagebox.showinfo"):
                        next(
                            button for button in descendants(dialog)
                            if isinstance(button, tk.Button)
                            and button.cget("text") == "Insert at cursor"
                        ).invoke()
                    self.assertEqual(app._get_text(), "unsaved recovery")
                    dialog.destroy()
                finally:
                    root.destroy()


if __name__ == "__main__":
    unittest.main()
