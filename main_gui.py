import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, Toplevel, Button, Text

import anki_utils
import config
import logger_setup
import parsers

logger = logging.getLogger(__name__)


class AnkiImporterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Anki Card Importer")
        self.root.geometry("900x650")

        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.panes_by_deck_name = {}

        self.passive_pane = self.create_input_pane(main_frame, "Passive Cards", self.start_passive_import)
        self.passive_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        self.panes_by_deck_name[config.PASSIVE_DECK_NAME] = self.passive_pane

        self.active_pane = self.create_input_pane(main_frame, "Active Cards", self.start_active_import)
        self.active_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        self.panes_by_deck_name[config.ACTIVE_DECK_NAME] = self.active_pane

        self.import_queue = queue.Queue()
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

        logger.info(f"Starting import for deck '{deck_config['deck_name']}' with {len(lines)} lines.")
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

        try:
            q.put({"type": "progress_text", "deck_name": deck_name, "text": "Checking deck..."})
            if not anki_utils.ensure_deck_exists(deck_name):
                q.put({"type": "error", "deck_name": deck_name, "message": f"Could not create/find deck: {deck_name}"})
                return

            q.put({"type": "progress_text", "deck_name": deck_name, "text": f"Parsing {len(lines)} lines..."})
            parsed_cards = []
            unparsable_lines = []
            for line in lines:
                front, back, tag_suffix = parser_func(line)
                if front and back:
                    parsed_cards.append({
                        "front": front, "back": back, "tags": tag_func(tag_suffix), "line": line.strip()
                    })
                else:
                    unparsable_lines.append(line)

            q.put({"type": "progress_text", "deck_name": deck_name,
                   "text": f"Checking {len(parsed_cards)} for duplicates..."})
            all_fronts = [card["front"] for card in parsed_cards]
            existing_notes_map = anki_utils.get_info_for_existing_notes(deck_name, all_fronts)

            notes_to_add = []
            skipped_cards = []
            # Use a set to track fronts for this batch to prevent intra-batch duplicates
            fronts_for_bulk_add = set()

            for card in parsed_cards:
                front = card["front"]
                # Case 1: Card already exists in Anki
                if front in existing_notes_map:
                    existing_info = existing_notes_map[front]
                    card_data = {
                        "front": front, "back_new": card["back"],
                        "note_id": existing_info["noteId"], "back_old": existing_info["fields"]["Back"]["value"]
                    }
                    skipped_cards.append(card_data)
                    continue

                # Case 2: Card is a duplicate within the input itself
                if front in fronts_for_bulk_add:
                    logger.info(f"Skipping card '{front}' as it is a duplicate within the input batch.")
                    card_data = {
                        "front": front, "back_new": card["back"],
                        "note_id": None, "back_old": "[Duplicate in this import session]"
                    }
                    skipped_cards.append(card_data)
                    continue

                # Case 3: This is a new, unique card to be added
                fronts_for_bulk_add.add(front)
                note = {
                    "deckName": deck_name, "modelName": config.MODEL_NAME,
                    "fields": {"Front": front, "Back": card["back"]},
                    "options": {"allowDuplicate": False}, "tags": card["tags"]
                }
                notes_to_add.append(note)

            q.put({"type": "progress_text", "deck_name": deck_name, "text": f"Adding {len(notes_to_add)} new cards..."})
            add_results = anki_utils.add_notes_bulk(notes_to_add)

            counts = {"added": 0, "skipped": len(skipped_cards), "failed": 0, "unparsable": len(unparsable_lines)}
            failed_cards = []
            if add_results and add_results.get("result"):
                results_list = add_results["result"]
                counts["added"] = sum(1 for r in results_list if r is not None)
                # This should ideally not happen now, but we keep the logic as a safeguard
                if None in results_list:
                    for i, result_id in enumerate(results_list):
                        if result_id is None:
                            counts["failed"] += 1
                            failed_note_data = notes_to_add[i]
                            logger.warning(
                                f"A single card failed to add inside a batch. Front: '{failed_note_data['fields']['Front']}'")
                            failed_cards.append({"front": failed_note_data['fields']['Front'],
                                                 "back": failed_note_data['fields']['Back'], "line": "N/A"})

            elif notes_to_add and not (add_results and add_results.get("result")):
                anki_error = add_results.get('error',
                                             'Response was empty or malformed.') if add_results else "Connection to Anki failed."
                logger.error(f"The entire bulk 'addNotes' request failed. AnkiConnect error: {anki_error}")
                counts["failed"] = len(notes_to_add)
                failed_cards = [{"front": n["fields"]["Front"], "back": n["fields"]["Back"], "line": ""} for n in
                                notes_to_add]

            q.put({
                "type": "complete", "deck_name": deck_name, "counts": counts,
                "skipped_cards": skipped_cards, "failed_cards": failed_cards, "unparsable_lines": unparsable_lines
            })

        except Exception as e:
            logger.error(f"Unhandled exception in worker thread for deck '{deck_name}'", exc_info=True)
            q.put({"type": "error", "deck_name": deck_name,
                   "message": f"A critical error occurred: {e}\nCheck logs.txt for details."})

    def process_import_queue(self):
        try:
            msg = self.import_queue.get(block=False)

            if msg["type"] == "destroy_widget":
                widget = msg.get("widget")
                if widget and widget.winfo_exists():
                    widget.destroy()
                return

            deck_name = msg.get("deck_name")
            if not deck_name or deck_name not in self.panes_by_deck_name:
                logger.warning(f"Queue message has invalid/missing deck_name: {msg}")
                return

            pane = self.panes_by_deck_name[deck_name]

            if msg["type"] == "progress_text":
                pane.progress_label.config(text=msg["text"])
            elif msg["type"] == "complete":
                logger.info(f"Import complete for '{deck_name}'. Results: {msg['counts']}")
                pane.start_button.config(state=tk.NORMAL)
                pane.progress_label.config(text="")

                has_issues = msg["skipped_cards"] or msg.get("failed_cards") or msg.get("unparsable_lines")
                if has_issues:
                    ImportResultsWindow(self.root, msg, self.import_queue)
                else:
                    summary = f"Import for '{msg['deck_name']}' complete!\n\n" + "\n".join(
                        [f"{k.capitalize()}: {v}" for k, v in msg['counts'].items()])
                    messagebox.showinfo("Import Complete", summary)
            elif msg["type"] == "error":
                logger.error(f"Received error message for pane '{deck_name}': {msg['message']}")
                messagebox.showerror("Error", msg["message"])
                pane.start_button.config(state=tk.NORMAL)
                pane.progress_label.config(text="")
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_import_queue)


class ImportResultsWindow(Toplevel):
    def __init__(self, parent, results, action_queue):
        super().__init__(parent)
        self.action_queue = action_queue
        self.title(f"Import Results for '{results['deck_name']}'")
        self.transient(parent)
        self.grab_set()
        self.geometry("800x600")

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        counts = results['counts']
        summary_text = (f"Import Summary:\n" + "\n".join([f"  - {k.capitalize()}: {v}" for k, v in counts.items()]))
        ttk.Label(main_frame, text=summary_text, justify=tk.LEFT).pack(anchor='w')
        ttk.Separator(main_frame, orient='horizontal').pack(fill='x', pady=10)

        canvas = tk.Canvas(main_frame, borderwidth=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        if results.get('skipped_cards'):
            skipped_frame = ttk.LabelFrame(scrollable_frame, text="Skipped Cards (Duplicates)", padding=10)
            skipped_frame.pack(fill=tk.X, expand=True, padx=5, pady=5)
            for card in results['skipped_cards']:
                self.create_skipped_card_frame(skipped_frame, card)

        if results.get('failed_cards'):
            self.create_simple_list_frame(scrollable_frame, "Failed to Add to Anki", results['failed_cards'],
                                          lambda card: f"Line: {card.get('line', card.get('front'))}")

        if results.get('unparsable_lines'):
            self.create_simple_list_frame(scrollable_frame, "Unparsable Lines", results['unparsable_lines'],
                                          lambda line: f"Line: {line.strip()}")

    def create_simple_list_frame(self, parent, title, items, formatter):
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
        ttk.Label(content_frame, text="Reason / Current Back:", font=("", 9, "bold")).grid(row=0, column=0, sticky='nw')
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

        # Only create action buttons if the note exists in Anki (has a note_id)
        if card_data.get('note_id'):
            action_frame = ttk.Frame(card_frame)
            action_frame.pack(fill=tk.X)
            buttons = []

            def run_task_in_thread(target_func, *args):
                for btn in buttons: btn.config(state=tk.DISABLED)

                def worker():
                    try:
                        target_func(*args)
                        self.action_queue.put({"type": "destroy_widget", "widget": card_frame})
                    except Exception:
                        logger.error("Exception in skipped card action thread", exc_info=True)

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
            for btn in buttons: btn.pack(side=tk.LEFT, padx=5)


if __name__ == "__main__":
    logger_setup.setup_logging()

    try:
        if anki_utils.anki_request('version') is None:
            logger.critical("Could not connect to AnkiConnect on startup.")
            messagebox.showerror("Anki Connection Error",
                                 "Could not connect to Anki.\nPlease ensure Anki is running with the AnkiConnect add-on.")
        else:
            logger.info("Successfully connected to AnkiConnect.")
            root = tk.Tk()
            app = AnkiImporterApp(root)
            root.mainloop()
    except Exception as e:
        logger.critical("A fatal error occurred during application initialization.", exc_info=True)
        messagebox.showerror("Fatal Error",
                             f"A fatal error occurred: {e}\n\nPlease check the logs.txt file for details.")

    logger.info("Application shutting down.")
