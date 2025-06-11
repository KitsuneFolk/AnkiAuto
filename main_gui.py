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

        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.passive_pane = self.create_input_pane(main_frame, "Passive Cards", self.start_passive_import)
        self.passive_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.active_pane = self.create_input_pane(main_frame, "Active Cards", self.start_active_import)
        self.active_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        self.import_queue = queue.Queue()

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
        self.check_import_queue(pane)

    def _import_worker(self, deck_config, lines, q):
        deck_name = deck_config["deck_name"]
        parser_func = getattr(parsers, deck_config["parser_func_name"])
        tag_func = deck_config["tag_generation_func"]

        if not anki_utils.ensure_deck_exists(deck_name):
            q.put({"type": "error", "message": f"Could not create/find deck: {deck_name}"})
            return

        counts = {"added": 0, "skipped": 0, "failed": 0, "unparsable": 0}
        skipped_cards = []
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
            else:
                counts["unparsable"] += 1

            q.put({"type": "progress", "counts": counts, "total": total})

        # Fetch detailed info for skipped cards after the main loop
        for card in skipped_cards:
            info = anki_utils.get_note_info(card['note_id'])
            card['back_old'] = info['result'][0]['fields']['Back']['value'] if info and info.get(
                'result') else "[Not Found]"

        q.put({"type": "complete", "deck_name": deck_name, "counts": counts, "skipped_cards": skipped_cards})

    def check_import_queue(self, pane):
        try:
            msg = self.import_queue.get(block=False)
            if msg["type"] == "progress":
                counts = msg["counts"]
                pane.progress_label.config(
                    text=f"A:{counts['added']} S:{counts['skipped']} F:{counts['failed']} / T:{msg['total']}")
                self.root.after(100, self.check_import_queue, pane)
            elif msg["type"] == "complete":
                pane.start_button.config(state=tk.NORMAL)
                pane.progress_label.config(text="")  # Clear progress
                if msg["skipped_cards"]:
                    SkippedCardsWindow(self.root, msg)
                else:
                    summary = f"Import for '{msg['deck_name']}' complete!\n\n" + "\n".join(
                        [f"{k.capitalize()}: {v}" for k, v in msg['counts'].items()])
                    messagebox.showinfo("Import Complete", summary)
            elif msg["type"] == "error":
                messagebox.showerror("Error", msg["message"])
                pane.start_button.config(state=tk.NORMAL)
        except queue.Empty:
            self.root.after(100, self.check_import_queue, pane)


class SkippedCardsWindow(Toplevel):
    def __init__(self, parent, results):
        super().__init__(parent)
        self.title(f"Handle Duplicates in '{results['deck_name']}'")
        self.transient(parent)
        self.grab_set()

        counts = results['counts']
        summary_text = (f"Import Summary:\n" + "\n".join([f"  - {k.capitalize()}: {v}" for k, v in counts.items()]))
        ttk.Label(self, text=summary_text, padding=10).pack(anchor='w')
        ttk.Separator(self, orient='horizontal').pack(fill='x', pady=5)

        # Canvas and Scrollbar for list of cards
        canvas = tk.Canvas(self, borderwidth=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.pack(side="right", fill="y")

        for card in results['skipped_cards']:
            self.create_card_frame(scrollable_frame, card)

    def create_card_frame(self, parent, card_data):
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
            # Disable all buttons in this frame during operation
            for btn in buttons: btn.config(state=tk.DISABLED)

            def worker():
                target_func(*args)
                # Safely destroy the frame from the main thread
                card_frame.after(0, card_frame.destroy)

            threading.Thread(target=worker, daemon=True).start()

        def on_append():
            updated_back = f"{card_data['back_old']}<hr>{card_data['back_new']}"
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