import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, Toplevel, Button, Text

import anki_utils
import config
import parsers


class AnkiImporterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Anki Card Importer")
        self.root.geometry("900x650")

        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # A dictionary to map deck names to their UI panes, allowing for concurrent updates.
        self.panes_by_deck_name = {}

        self.passive_pane = self.create_input_pane(main_frame, "Passive Cards", self.start_passive_import)
        self.passive_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        self.panes_by_deck_name[config.PASSIVE_DECK_NAME] = self.passive_pane

        self.active_pane = self.create_input_pane(main_frame, "Active Cards", self.start_active_import)
        self.active_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        self.panes_by_deck_name[config.ACTIVE_DECK_NAME] = self.active_pane

        self.import_queue = queue.Queue()
        # Start the single, persistent queue checker that handles all updates.
        self.process_import_queue()

    def create_input_pane(self, parent, title, start_command):
        pane = ttk.LabelFrame(parent, text=title, padding="10")

        text_widget = Text(pane, wrap=tk.WORD, height=10, width=40)
        text_widget.pack(fill=tk.BOTH, expand=True)
        pane.text_widget = text_widget

        button_frame = ttk.Frame(pane, padding=(0, 10))
        button_frame.pack(fill=tk.X)

        def paste_from_clipboard():
            try:
                text_widget.delete("1.0", tk.END)
                text_widget.insert("1.0", self.root.clipboard_get())
            except tk.TclError:
                messagebox.showwarning("Paste Error", "Clipboard is empty or contains incompatible content.")

        paste_button = ttk.Button(button_frame, text="Paste", command=paste_from_clipboard)
        paste_button.pack(side=tk.LEFT)

        start_button = ttk.Button(button_frame, text="Start Import", command=start_command)
        pane.start_button = start_button
        start_button.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))

        progress_label = ttk.Label(button_frame, text="")
        pane.progress_label = progress_label
        progress_label.pack(side=tk.RIGHT)

        return pane

    def start_passive_import(self):
        deck_config = next(c for c in config.PROCESSING_CONFIGS if c["deck_name"] == config.PASSIVE_DECK_NAME)
        self.launch_import_thread(deck_config, self.passive_pane)

    def start_active_import(self):
        deck_config = next(c for c in config.PROCESSING_CONFIGS if c["deck_name"] == config.ACTIVE_DECK_NAME)
        self.launch_import_thread(deck_config, self.active_pane)

    def launch_import_thread(self, deck_config, pane):
        pane.start_button.config(state=tk.DISABLED)
        raw_text = pane.text_widget.get("1.0", tk.END)
        lines = [line for line in raw_text.strip().split('\n') if line.strip()]

        if not lines:
            messagebox.showinfo("No Input", "The input box is empty.")
            pane.start_button.config(state=tk.NORMAL)
            return

        thread = threading.Thread(
            target=self._import_worker,
            args=(deck_config, lines, self.import_queue),
            daemon=True
        )
        thread.start()

    def _import_worker(self, deck_config, lines, q):
        deck_name = deck_config["deck_name"]
        parser_func = getattr(parsers, deck_config["parser_func_name"])
        tag_func = deck_config["tag_generation_func"]

        if not anki_utils.ensure_deck_exists(deck_name):
            # Include deck_name in message to identify the source pane.
            q.put({"type": "error", "deck_name": deck_name, "message": f"Could not create/find deck: {deck_name}"})
            return

        counts = {"added": 0, "skipped": 0, "failed": 0, "unparsable": 0}
        skipped_cards = []
        failed_cards = []
        unparsable_lines = []
        total = len(lines)

        for line in lines:
            front, back, tag_suffix = parser_func(line)
            if front and back:
                tags = tag_func(tag_suffix)
                status, note_id = anki_utils.add_card(deck_name, config.MODEL_NAME, front, back, tags)

                counts[status] += 1
                if status == "skipped":
                    card_data = {"front": front, "back_new": back, 'note_id': note_id}
                    skipped_cards.append(card_data)
                elif status == "failed":
                    failed_cards.append({"front": front, "back": back, "line": line.strip()})
            else:
                counts["unparsable"] += 1
                unparsable_lines.append(line)

            # Include deck_name in message to identify the source pane.
            q.put({"type": "progress", "deck_name": deck_name, "counts": counts, "total": total})

        # Fetch detailed info for skipped cards after the main loop
        if skipped_cards:
            for card in skipped_cards:
                info = anki_utils.get_note_info(card['note_id'])
                card['back_old'] = info['result'][0]['fields']['Back']['value'] if info and info.get(
                    'result') else "[Not Found]"

        q.put({
            "type": "complete",
            "deck_name": deck_name,
            "counts": counts,
            "skipped_cards": skipped_cards,
            "failed_cards": failed_cards,
            "unparsable_lines": unparsable_lines
        })

    def process_import_queue(self):
        """
        Processes messages from all import threads. This single, persistent loop
        replaces the old method and allows for concurrent UI updates.
        """
        try:
            msg = self.import_queue.get(block=False)

            deck_name = msg.get("deck_name")
            if not deck_name or deck_name not in self.panes_by_deck_name:
                print(f"Queue message has invalid/missing deck_name: {msg}")
                return

            pane = self.panes_by_deck_name[deck_name]

            if msg["type"] == "progress":
                counts = msg["counts"]
                pane.progress_label.config(
                    text=f"A:{counts['added']} S:{counts['skipped']} F:{counts['failed']} U:{counts['unparsable']} / T:{msg['total']}")
            elif msg["type"] == "complete":
                pane.start_button.config(state=tk.NORMAL)
                pane.progress_label.config(text="")  # Clear progress

                has_issues = msg["skipped_cards"] or msg.get("failed_cards") or msg.get("unparsable_lines")
                if has_issues:
                    ImportResultsWindow(self.root, msg)
                else:
                    summary = f"Import for '{msg['deck_name']}' complete!\n\n" + "\n".join(
                        [f"{k.capitalize()}: {v}" for k, v in msg['counts'].items()])
                    messagebox.showinfo("Import Complete", summary)
            elif msg["type"] == "error":
                messagebox.showerror("Error", msg["message"])
                pane.start_button.config(state=tk.NORMAL)
                pane.progress_label.config(text="")
        except queue.Empty:
            pass  # No message, do nothing.
        finally:
            # Always reschedule the check to keep the loop running.
            self.root.after(100, self.process_import_queue)


class ImportResultsWindow(Toplevel):
    def __init__(self, parent, results):
        super().__init__(parent)
        self.title(f"Import Results for '{results['deck_name']}'")
        self.transient(parent)
        self.grab_set()
        self.geometry("800x600")

        # Main frame and summary
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        counts = results['counts']
        summary_text = (f"Import Summary:\n" + "\n".join([f"  - {k.capitalize()}: {v}" for k, v in counts.items()]))
        ttk.Label(main_frame, text=summary_text, justify=tk.LEFT).pack(anchor='w')
        ttk.Separator(main_frame, orient='horizontal').pack(fill='x', pady=10)

        # Canvas and Scrollbar for list of issues
        canvas = tk.Canvas(main_frame, borderwidth=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Section for Skipped Cards (if any)
        if results.get('skipped_cards'):
            skipped_frame = ttk.LabelFrame(scrollable_frame, text="Skipped Cards (Duplicates)", padding=10)
            skipped_frame.pack(fill=tk.X, expand=True, padx=5, pady=5)
            for card in results['skipped_cards']:
                self.create_skipped_card_frame(skipped_frame, card)

        # Section for Failed Cards (if any)
        if results.get('failed_cards'):
            self.create_simple_list_frame(scrollable_frame, "Failed to Add to Anki", results['failed_cards'],
                                          lambda card: f"Line: {card['line']}")

        # Section for Unparsable Lines (if any)
        if results.get('unparsable_lines'):
            self.create_simple_list_frame(scrollable_frame, "Unparsable Lines", results['unparsable_lines'],
                                          lambda line: f"Line: {line.strip()}")

    def create_simple_list_frame(self, parent, title, items, formatter):
        """Creates a frame with a read-only text box for listing items."""
        frame = ttk.LabelFrame(parent, text=title, padding=10)
        frame.pack(fill=tk.X, expand=True, padx=5, pady=5)

        text_content = "\n".join(formatter(item) for item in items)
        text_widget = Text(frame, wrap=tk.WORD, height=min(len(items), 6), bg=self.cget('bg'), relief=tk.FLAT)
        text_widget.insert("1.0", text_content)
        text_widget.config(state=tk.DISABLED)
        text_widget.pack(fill=tk.X, expand=True)

    def create_skipped_card_frame(self, parent, card_data):
        card_frame = ttk.LabelFrame(parent, text=f"Card: {card_data['front']}", padding=10)
        card_frame.pack(fill=tk.X, padx=5, pady=5, expand=True)

        content_frame = ttk.Frame(card_frame)
        content_frame.pack(fill=tk.X, expand=True, pady=5)

        ttk.Label(content_frame, text="Current Back in Anki:", font=("", 9, "bold")).grid(row=0, column=0, sticky='nw')
        ttk.Label(content_frame, text=card_data['back_old'], wraplength=350, justify=tk.LEFT).grid(row=1, column=0,
                                                                                                   sticky='w',
                                                                                                   pady=(0, 10))
        ttk.Label(content_frame, text="New Back from input:", font=("", 9, "bold")).grid(row=0, column=1, sticky='nw',
                                                                                         padx=(20, 0))
        ttk.Label(content_frame, text=card_data['back_new'], wraplength=350, justify=tk.LEFT).grid(row=1, column=1,
                                                                                                   sticky='w',
                                                                                                   padx=(20, 0))
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_columnconfigure(1, weight=1)

        action_frame = ttk.Frame(card_frame)
        action_frame.pack(fill=tk.X)

        buttons = []

        def run_task_in_thread(target_func, *args):
            for btn in buttons: btn.config(state=tk.DISABLED)

            def worker():
                target_func(*args)
                card_frame.after(0, card_frame.destroy)

            threading.Thread(target=worker, daemon=True).start()

        def on_append():
            updated_back = f"{card_data['back_old']}<br>{card_data['back_new']}"
            anki_utils.update_note_fields(card_data['note_id'], {"Back": updated_back})
            anki_utils.reset_cards([card_data['note_id']])

        def on_reset():
            anki_utils.reset_cards([card_data['note_id']])

        def on_modify():
            anki_utils.open_editor_for_note(card_data['note_id'])
            anki_utils.reset_cards([card_data['note_id']])

        append_btn = Button(action_frame, text="Append & Reset", command=lambda: run_task_in_thread(on_append))
        reset_btn = Button(action_frame, text="Just Reset", command=lambda: run_task_in_thread(on_reset))
        modify_btn = Button(action_frame, text="Modify & Reset", command=lambda: run_task_in_thread(on_modify))

        buttons.extend([append_btn, reset_btn, modify_btn])
        for btn in buttons:
            btn.pack(side=tk.LEFT, padx=5)


if __name__ == "__main__":
    if anki_utils.anki_request('version') is None:
        messagebox.showerror("Anki Connection Error",
                             "Could not connect to Anki.\nPlease ensure Anki is running with the AnkiConnect add-on.")
    else:
        root = tk.Tk()
        app = AnkiImporterApp(root)
        root.mainloop()
