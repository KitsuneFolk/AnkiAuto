# main_gui.py
import tkinter as tk
from tkinter import ttk, messagebox, Toplevel, Frame, Label, Button, Text
import threading
import queue
import config
import anki_utils
import parsers


class AnkiImporterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Anki Card Importer")
        self.root.geometry("900x650")

        # --- Main Layout & Panes ---
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.passive_pane = self.create_input_pane(main_frame, "Passive Cards", self.start_passive_import)
        self.passive_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.active_pane = self.create_input_pane(main_frame, "Active Cards", self.start_active_import)
        self.active_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        # --- Status Bar ---
        self.status_bar = ttk.Frame(root, padding=(5, 2))
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_label = ttk.Label(self.status_bar, text="Ready")
        self.status_label.pack(side=tk.LEFT)
        self.progress_bar = ttk.Progressbar(self.status_bar, mode='indeterminate')
        self.progress_bar.pack(side=tk.RIGHT)

        # Queue for thread communication
        self.results_queue = queue.Queue()

    def create_input_pane(self, parent, title, start_command):
        pane = ttk.LabelFrame(parent, text=title, padding="10")

        text_widget = Text(pane, wrap=tk.WORD, height=10, width=40)
        text_widget.pack(fill=tk.BOTH, expand=True)
        pane.text_widget = text_widget  # Store reference to the text widget

        button_frame = ttk.Frame(pane, padding=(0, 10))
        button_frame.pack(fill=tk.X)

        def paste_from_clipboard():
            try:
                clipboard_content = self.root.clipboard_get()
                text_widget.delete("1.0", tk.END)
                text_widget.insert("1.0", clipboard_content)
            except tk.TclError:
                self.status_label.config(text="Clipboard is empty.")

        paste_button = ttk.Button(button_frame, text="Paste from Clipboard", command=paste_from_clipboard)
        paste_button.pack(side=tk.LEFT)

        start_button = ttk.Button(button_frame, text="Start Import", command=start_command)
        start_button.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))

        return pane

    def start_passive_import(self):
        deck_config = next(c for c in config.PROCESSING_CONFIGS if c["deck_name"] == config.PASSIVE_DECK_NAME)
        raw_text = self.passive_pane.text_widget.get("1.0", tk.END)
        self.launch_import_thread(deck_config, raw_text)

    def start_active_import(self):
        deck_config = next(c for c in config.PROCESSING_CONFIGS if c["deck_name"] == config.ACTIVE_DECK_NAME)
        raw_text = self.active_pane.text_widget.get("1.0", tk.END)
        self.launch_import_thread(deck_config, raw_text)

    def launch_import_thread(self, deck_config, raw_text):
        self.status_label.config(text=f"Importing to '{deck_config['deck_name']}'...")
        self.progress_bar.start()

        # Create and start the worker thread
        thread = threading.Thread(
            target=self._import_worker,
            args=(deck_config, raw_text, self.results_queue),
            daemon=True
        )
        thread.start()

        # Start checking the queue for results
        self.root.after(100, self.check_queue)

    def _import_worker(self, deck_config, raw_text, q):
        """This function runs in a separate thread."""
        deck_name = deck_config["deck_name"]
        parser_func = getattr(parsers, deck_config["parser_func_name"])
        tag_func = deck_config["tag_generation_func"]

        if not anki_utils.ensure_deck_exists(deck_name):
            q.put({"error": f"Could not create or find Anki deck: {deck_name}"})
            return

        added, skipped_raw, failed, unparsable = [], [], [], 0
        lines = raw_text.strip().split('\n')

        for line in lines:
            if not line.strip(): continue
            front, back, tag_suffix = parser_func(line)
            if front and back:
                tags = tag_func(tag_suffix)
                status, note_id = anki_utils.add_card(deck_name, config.MODEL_NAME, front, back, tags)

                card_data = {"front": front, "back_new": back}
                if status == "added":
                    added.append(card_data)
                elif status == "failed":
                    failed.append(card_data)
                elif status == "skipped":
                    card_data['note_id'] = note_id
                    skipped_raw.append(card_data)
            else:
                unparsable += 1

        # For skipped cards, fetch their current "Back" field
        skipped_detailed = []
        for card in skipped_raw:
            info = anki_utils.get_note_info(card['note_id'])
            if info and info.get('result'):
                card['back_old'] = info['result'][0]['fields']['Back']['value']
            else:
                card['back_old'] = "[Could not fetch current back]"
            skipped_detailed.append(card)

        q.put({
            "deck_name": deck_name, "added": added, "skipped": skipped_detailed,
            "failed": failed, "unparsable": unparsable
        })

    def check_queue(self):
        """Periodically check the queue for results from the worker thread."""
        try:
            result = self.results_queue.get(block=False)

            self.progress_bar.stop()
            self.status_label.config(text="Ready")

            if "error" in result:
                messagebox.showerror("Error", result["error"])
                return

            # Display results window
            if result["skipped"]:
                SkippedCardsWindow(self.root, result)
            else:
                summary = f"Import for '{result['deck_name']}' complete!\n\n"
                summary += f"Successfully Added: {len(result['added'])}\n"
                summary += f"Skipped (Duplicates): {len(result['skipped'])}\n"
                summary += f"Failed: {len(result['failed'])}\n"
                summary += f"Unparsable Lines: {result['unparsable']}"
                messagebox.showinfo("Import Complete", summary)

        except queue.Empty:
            # If the queue is empty, check again after 100ms
            self.root.after(100, self.check_queue)


class SkippedCardsWindow(Toplevel):
    def __init__(self, parent, results):
        super().__init__(parent)
        self.title(f"Skipped Cards in '{results['deck_name']}'")
        self.transient(parent)
        self.grab_set()

        summary_text = (
            f"Import Summary:\n"
            f"  - Added: {len(results['added'])}\n"
            f"  - Failed: {len(results['failed'])}\n"
            f"  - Skipped: {len(results['skipped'])}\n"
            f"  - Unparsable Lines: {results['unparsable']}"
        )
        ttk.Label(self, text=summary_text, padding=10).pack(anchor='w')
        ttk.Separator(self, orient='horizontal').pack(fill='x', pady=5)
        ttk.Label(self, text="Choose an action for each skipped card:", font=("", 10, "bold"), padding=10).pack(
            anchor='w')

        # Canvas and Scrollbar for list of cards
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for card in results['skipped']:
            self.create_card_frame(scrollable_frame, card)

    def create_card_frame(self, parent, card_data):
        card_frame = ttk.LabelFrame(parent, text=f"Card: {card_data['front']}", padding=10)
        card_frame.pack(fill=tk.X, padx=10, pady=5)

        # Frame to hold old and new back content
        content_frame = ttk.Frame(card_frame)
        content_frame.pack(fill=tk.X, expand=True, pady=5)

        ttk.Label(content_frame, text="Current Back in Anki:", font=("", 9, "bold")).grid(row=0, column=0, sticky='nw')
        old_back_label = ttk.Label(content_frame, text=card_data['back_old'], wraplength=350, justify=tk.LEFT)
        old_back_label.grid(row=1, column=0, sticky='w', pady=(0, 10))

        ttk.Label(content_frame, text="New Back from input:", font=("", 9, "bold")).grid(row=0, column=1, sticky='nw',
                                                                                         padx=(20, 0))
        new_back_label = ttk.Label(content_frame, text=card_data['back_new'], wraplength=350, justify=tk.LEFT)
        new_back_label.grid(row=1, column=1, sticky='w', padx=(20, 0), pady=(0, 10))

        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_columnconfigure(1, weight=1)

        # Action Buttons
        action_frame = ttk.Frame(card_frame)
        action_frame.pack(fill=tk.X)

        note_id = card_data['note_id']
        new_back = card_data['back_new']
        old_back = card_data['back_old']

        def on_append():
            updated_back = f"{old_back}<hr>{new_back}"
            anki_utils.update_note_fields(note_id, {"Back": updated_back})
            anki_utils.reset_cards([note_id])
            card_frame.destroy()

        def on_reset():
            anki_utils.reset_cards([note_id])
            card_frame.destroy()

        def on_modify():
            anki_utils.open_editor_for_note(note_id)
            anki_utils.reset_cards([note_id])
            card_frame.destroy()

        Button(action_frame, text="Append & Reset", command=on_append).pack(side=tk.LEFT, padx=5)
        Button(action_frame, text="Just Reset", command=on_reset).pack(side=tk.LEFT, padx=5)
        Button(action_frame, text="Modify & Reset", command=on_modify).pack(side=tk.LEFT, padx=5)


if __name__ == "__main__":
    if anki_utils.anki_request('version') is None:
        messagebox.showerror("Anki Connection Error",
                             "Could not connect to Anki.\nPlease ensure Anki is running with the AnkiConnect add-on installed.")
    else:
        root = tk.Tk()
        app = AnkiImporterApp(root)
        root.mainloop()