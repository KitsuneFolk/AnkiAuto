import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, Toplevel, Button, Text, font

import anki_utils
import config
import logger_setup
import parsers

logger = logging.getLogger(__name__)


class AnkiImporterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Anki Card Importer")
        self.root.geometry("950x700") # Increased size
        self.style = ttk.Style()
        self.style.theme_use('clam') # Using a more modern theme

        # Define custom fonts
        self.title_font = font.Font(family="Helvetica", size=14, weight="bold")
        self.label_font = font.Font(family="Arial", size=10)
        self.button_font = font.Font(family="Arial", size=10, weight="bold")
        self.text_font = font.Font(family="Arial", size=10)

        # Configure styles
        self.style.configure("Custom.TLabelFrame", padding=10, relief="groove", borderwidth=2)
        self.style.configure("Custom.TLabelFrame.Label", font=self.title_font, padding=(0,5)) # Style for the label within the custom LabelFrame
        self.style.configure("TButton", font=self.button_font, padding=5) # This is usually fine as it's a common widget
        self.style.configure("Progress.TLabel", font=self.label_font) # For progress text

        main_frame = ttk.Frame(root, padding="20") # Increased padding
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.panes_by_deck_name = {}

        self.passive_pane = self.create_input_pane(main_frame, "Passive Cards", self.start_passive_import)
        self.passive_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10), pady=10) # Added pady
        self.panes_by_deck_name[config.PASSIVE_DECK_NAME] = self.passive_pane

        self.active_pane = self.create_input_pane(main_frame, "Active Cards", self.start_active_import)
        self.active_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=10) # Added pady
        self.panes_by_deck_name[config.ACTIVE_DECK_NAME] = self.active_pane

        self.import_queue = queue.Queue()
        self.process_import_queue()

    def create_input_pane(self, parent, title, start_command):
        pane = ttk.LabelFrame(parent, text=title, style="Custom.TLabelFrame") # Apply custom style
        pane.text_widget_font = self.text_font # Store for later use if needed

        text_widget = Text(pane, wrap=tk.WORD, height=15, width=45, font=self.text_font, relief="solid", borderwidth=1) # Increased size, font, border
        text_widget.pack(fill=tk.BOTH, expand=True, pady=(5,10)) # Added padding
        pane.text_widget = text_widget

        # Frame for buttons and progress
        bottom_frame = ttk.Frame(pane)
        bottom_frame.pack(fill=tk.X, pady=(5,0))

        def paste_from_clipboard():
            try:
                text_widget.delete("1.0", tk.END)
                text_widget.insert("1.0", self.root.clipboard_get())
            except tk.TclError:
                messagebox.showwarning("Paste Error", "Clipboard is empty or contains incompatible content.")

        paste_button = ttk.Button(bottom_frame, text="Paste", command=paste_from_clipboard, style="TButton")
        paste_button.pack(side=tk.LEFT, padx=(0,10)) # Added padding

        start_button = ttk.Button(bottom_frame, text="Start Import", command=start_command, style="TButton")
        pane.start_button = start_button
        start_button.pack(side=tk.LEFT, fill=tk.X, expand=True) # Changed from tk.RIGHT

        # Progress bar and label combined
        progress_frame = ttk.Frame(pane) # Frame to hold progress bar and label
        progress_frame.pack(fill=tk.X, pady=(5,0))

        pane.progress_bar = ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL, length=100, mode='determinate')
        pane.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))

        progress_label = ttk.Label(progress_frame, text="", style="Progress.TLabel") # Apply style
        pane.progress_label = progress_label
        progress_label.pack(side=tk.LEFT)


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
        pane.progress_bar["value"] = 0 # Reset progress bar
        pane.progress_bar["maximum"] = 100 # Default max for stages before card processing

    def _import_worker(self, deck_config, lines, q):
        deck_name = deck_config["deck_name"]
        parser_func = getattr(parsers, deck_config["parser_func_name"])
        tag_func = deck_config["tag_generation_func"]
        total_lines = len(lines)

        try:
            q.put({"type": "progress_update", "deck_name": deck_name, "value": 5, "text": "Checking deck..."})
            if not anki_utils.ensure_deck_exists(deck_name):
                q.put({"type": "error", "deck_name": deck_name, "message": f"Could not create/find deck: {deck_name}"})
                return

            q.put({"type": "progress_update", "deck_name": deck_name, "value": 15, "text": f"Parsing {total_lines} lines..."})
            parsed_cards = []
            unparsable_lines = []
            # Update progress bar during parsing if it's a long list
            # For simplicity, we'll do a single update after parsing, but for very large lists,
            # this could be done incrementally.
            for i, line in enumerate(lines):
                front, back, tag_suffix = parser_func(line)
                if front and back:
                    parsed_cards.append({
                        "front": front, "back": back, "tags": tag_func(tag_suffix), "line": line.strip()
                    })
                else:
                    unparsable_lines.append(line)
                # q.put({"type": "progress_update", "deck_name": deck_name,
                #        "value": 15 + int(35 * (i + 1) / total_lines),  # Parsing takes up to 50% (15 to 50)
                #        "text": f"Parsing line {i+1}/{total_lines}"})


            q.put({"type": "progress_update", "deck_name": deck_name, "value": 50,
                   "text": f"Checking {len(parsed_cards)} for duplicates..."})
            all_fronts = [card["front"] for card in parsed_cards]
            existing_notes_map = anki_utils.get_info_for_existing_notes(deck_name, all_fronts)

            notes_to_add = []
            source_lines_for_notes_to_add = [] # Stores original lines for notes_to_add
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
                source_lines_for_notes_to_add.append(card['line'])

            # Update progress before adding notes
            # Adding notes can be slow, so this stage gets a good chunk of progress bar time
            q.put({"type": "progress_update", "deck_name": deck_name, "value": 65, "text": f"Adding {len(notes_to_add)} new cards..."})
            add_results = anki_utils.add_notes_bulk(notes_to_add)
            # After adding, jump progress significantly
            q.put({"type": "progress_update", "deck_name": deck_name, "value": 95, "text": "Finalizing..."})


            counts = {"added": 0, "skipped": len(skipped_cards), "failed": 0, "unparsable": len(unparsable_lines)}
            failed_cards = []
            if add_results and add_results.get("result"):
                results_list = add_results["result"]
                counts["added"] = sum(1 for r in results_list if r is not None)
                # AnkiConnect's addNotes can return None for individual notes in a batch if they
                # fail to import (e.g., due to errors or if allowDuplicate=false and it's a
                # duplicate within the batch). This logic handles such individual failures.
                if None in results_list:
                    for i, result_id in enumerate(results_list):
                        if result_id is None:
                            counts["failed"] += 1
                            failed_note_data = notes_to_add[i]
                            original_line = source_lines_for_notes_to_add[i]
                            logger.warning(
                                f"A single card failed to add inside a batch. Front: '{failed_note_data['fields']['Front']}'. Original line: '{original_line}'")
                            failed_cards.append({"front": failed_note_data['fields']['Front'],
                                                 "back": failed_note_data['fields']['Back'], "line": original_line})

            elif notes_to_add and not (add_results and add_results.get("result")):
                anki_error = add_results.get('error',
                                             'Response was empty or malformed.') if add_results else "Connection to Anki failed."
                logger.error(f"The entire bulk 'addNotes' request failed. AnkiConnect error: {anki_error}")
                counts["failed"] = len(notes_to_add)
                failed_cards = [{"front": n["fields"]["Front"],
                                 "back": n["fields"]["Back"],
                                 "line": source_lines_for_notes_to_add[idx]}
                                for idx, n in enumerate(notes_to_add)]

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

            if msg["type"] == "progress_update":
                pane.progress_label.config(text=msg["text"])
                if "value" in msg:
                    pane.progress_bar["value"] = msg["value"]
            elif msg["type"] == "complete":
                logger.info(f"Import complete for '{deck_name}'. Results: {msg['counts']}")
                pane.start_button.config(state=tk.NORMAL)
                pane.progress_label.config(text="Done!")
                pane.progress_bar["value"] = 100 # Ensure it shows full

                has_issues = msg["skipped_cards"] or msg.get("failed_cards") or msg.get("unparsable_lines")
                if has_issues:
                    ImportResultsWindow(self.root, msg, self.import_queue, self.style) # Pass style
                else:
                    summary = f"Import for '{msg['deck_name']}' complete!\n\n" + "\n".join(
                        [f"{k.capitalize()}: {v}" for k, v in msg['counts'].items()])
                    messagebox.showinfo("Import Complete", summary)
                # Consider resetting progress bar after a delay or on next action
                self.root.after(3000, lambda p=pane: self.reset_progress(p) if p.winfo_exists() else None)

            elif msg["type"] == "error":
                logger.error(f"Received error message for pane '{deck_name}': {msg['message']}")
                messagebox.showerror("Error", msg["message"])
                pane.start_button.config(state=tk.NORMAL)
                pane.progress_label.config(text="Error!")
                pane.progress_bar["value"] = 0
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_import_queue)

    def reset_progress(self, pane):
        if pane.winfo_exists():
            pane.progress_label.config(text="")
            pane.progress_bar["value"] = 0


class ImportResultsWindow(Toplevel):
    def __init__(self, parent, results, action_queue, style_engine):
        super().__init__(parent)
        self.action_queue = action_queue
        self.style = style_engine # Use the passed style engine
        self.title(f"Import Results for '{results['deck_name']}'")
        self.transient(parent)
        self.grab_set()
        self.geometry("850x650") # Slightly larger

        # Use app's fonts
        self.title_font = font.Font(family="Helvetica", size=12, weight="bold") # Slightly smaller for sections
        self.label_font = font.Font(family="Arial", size=10)
        self.button_font = font.Font(family="Arial", size=9) # Smaller for action buttons
        self.text_font = font.Font(family="Arial", size=10)


        main_frame = ttk.Frame(self, padding=15) # Increased padding
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Style configurations for this window
        # Ensure these are unique and don't clash with global styles if not intended
        self.style.configure("ResultsWindow.TLabelFrame", padding=8, relief="groove", borderwidth=1)
        self.style.configure("ResultsWindow.TLabelFrame.Label", font=self.title_font, padding=(0,4))
        self.style.configure("ResultsWindow.TButton", font=self.button_font, padding=3) # Renamed to avoid conflict if main TButton style is different
        self.style.configure("ResultsWindow.Header.TLabel", font=font.Font(family="Helvetica", size=11, weight="bold"))


        counts = results['counts']
        summary_text = (f"Import Summary for '{results['deck_name']}':\n" + "\n".join([f"  - {k.capitalize()}: {v}" for k, v in counts.items()]))
        ttk.Label(main_frame, text=summary_text, justify=tk.LEFT, font=self.label_font, style="ResultsWindow.Header.TLabel").pack(anchor='w', pady=(0,10))
        ttk.Separator(main_frame, orient='horizontal').pack(fill='x', pady=10)

        # Main scrollable area
        canvas_frame = ttk.Frame(main_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame, borderwidth=0, highlightthickness=0) # Removed default border
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, padding=(10,0)) # Add padding inside scrollable area

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")


        if results.get('skipped_cards'):
            skipped_outer_frame = ttk.LabelFrame(scrollable_frame, text="Skipped Cards (Duplicates)", style="ResultsWindow.TLabelFrame")
            skipped_outer_frame.pack(fill=tk.X, expand=True, padx=5, pady=5)
            for card in results['skipped_cards']:
                self.create_skipped_card_frame(skipped_outer_frame, card)

        if results.get('failed_cards'):
            self.create_simple_list_frame(scrollable_frame, "Failed to Add to Anki", results['failed_cards'],
                                          lambda card: f"Line: {card.get('line', card.get('front'))}", style_name="ResultsWindow.TLabelFrame")

        if results.get('unparsable_lines'):
            self.create_simple_list_frame(scrollable_frame, "Unparsable Lines", results['unparsable_lines'],
                                          lambda line: f"Line: {line.strip()}", style_name="ResultsWindow.TLabelFrame")

    def create_simple_list_frame(self, parent, title, items, formatter, style_name):
        frame = ttk.LabelFrame(parent, text=title, style=style_name, padding=10) # style_name is now "ResultsWindow.TLabelFrame"
        frame.pack(fill=tk.X, expand=True, padx=5, pady=(10,5)) # Added more vertical padding

        # Use a Text widget for better layout and potential scrollability if needed, but keep it simple
        # For better visual appeal, use a Label per item or a more structured list (TreeView) for many items.
        # Here, sticking to Text for simplicity of change, but with font.
        text_content = "\n".join(formatter(item) for item in items)

        # If many items, consider a scrollbar for this specific text widget too.
        # For now, just make it expand and rely on main scrollbar. Max height to keep it from being too tall.
        height = min(len(items) + 1, 8) # +1 for a bit of space, max 8 lines visible initially
        text_widget = Text(frame, wrap=tk.WORD, height=height, font=self.text_font,
                           relief=tk.SOLID, borderwidth=1, padx=5, pady=5) # Added padding inside Text
        text_widget.insert("1.0", text_content)
        text_widget.config(state=tk.DISABLED, bg="#f0f0f0") # Light gray background for read-only
        text_widget.pack(fill=tk.X, expand=True, pady=(5,0))


    def create_skipped_card_frame(self, parent, card_data):
        # Using a standard Frame here for tighter packing, style applied to parent LabelFrame
        card_frame = ttk.Frame(parent, padding=(5,8), relief="groove", borderwidth=1) # Added border and more padding
        card_frame.pack(fill=tk.X, padx=5, pady=5, expand=True)

        # Card Front as a header for this small section
        front_label = ttk.Label(card_frame, text=f"Card: {card_data['front']}", font=font.Font(family="Arial", size=10, weight="bold"))
        front_label.pack(anchor="w", pady=(0,5))

        content_frame = ttk.Frame(card_frame)
        content_frame.pack(fill=tk.X, expand=True, pady=(0,8)) # Adjusted padding

        # Current Back
        ttk.Label(content_frame, text="Current Back in Anki / Reason:", font=self.label_font).grid(row=0, column=0, sticky='nw', pady=(0,2))
        current_back_text = Text(content_frame, wrap=tk.WORD, height=3, width=35, font=self.text_font, relief="flat", bg=self.cget('bg'))
        current_back_text.insert("1.0", card_data['back_old'])
        current_back_text.config(state=tk.DISABLED)
        current_back_text.grid(row=1, column=0, sticky='nsew', pady=(0, 10))

        # New Back
        ttk.Label(content_frame, text="New Back from Input:", font=self.label_font).grid(row=0, column=1, sticky='nw', padx=(15, 0), pady=(0,2))
        new_back_text = Text(content_frame, wrap=tk.WORD, height=3, width=35, font=self.text_font, relief="flat", bg=self.cget('bg'))
        new_back_text.insert("1.0", card_data['back_new'])
        new_back_text.config(state=tk.DISABLED)
        new_back_text.grid(row=1, column=1, sticky='nsew', padx=(15, 0), pady=(0, 10))

        content_frame.grid_columnconfigure(0, weight=1, minsize=200) # Ensure columns have minsize
        content_frame.grid_columnconfigure(1, weight=1, minsize=200)

        if card_data.get('note_id'):
            action_frame = ttk.Frame(card_frame)
            action_frame.pack(fill=tk.X, pady=(5,0))
            buttons = []

            def run_task_in_thread(target_func, *args):
                for btn in buttons:
                    if btn.winfo_exists(): btn.config(state=tk.DISABLED)
                # Show some visual feedback on the button or frame itself
                # e.g., card_frame.config(relief="sunken")

                def worker():
                    try:
                        target_func(*args)
                        # Remove the specific card frame on success
                        self.action_queue.put({"type": "destroy_widget", "widget": card_frame})
                    except Exception:
                        logger.error("Exception in skipped card action thread", exc_info=True)
                        # Re-enable buttons on error if the frame is not destroyed
                        if card_frame.winfo_exists():
                            for btn_ in buttons:
                                if btn_.winfo_exists(): btn_.config(state=tk.NORMAL)
                            # card_frame.config(relief="groove") # Reset relief
                    finally:
                        # If the frame is destroyed, no need to re-enable,
                        # otherwise, ensure buttons are re-enabled if an error occurred and frame still exists
                        pass


                threading.Thread(target=worker, daemon=True).start()

            def on_append():
                updated_back = f"{card_data['back_old']}<br><hr>{card_data['back_new']}" # Added <hr> for visual separation
                anki_utils.update_note_fields(card_data['note_id'], {"Back": updated_back})
                anki_utils.reset_cards([card_data['note_id']])

            def on_reset():
                anki_utils.reset_cards([card_data['note_id']])

            def on_modify():
                anki_utils.open_editor_for_note(card_data['note_id'])
                # Resetting after modification might be desired if changes were made to scheduling
                anki_utils.reset_cards([card_data['note_id']])

            # Using ttk.Button and applying style
            append_btn = ttk.Button(action_frame, text="Append & Reset", command=lambda: run_task_in_thread(on_append), style="ResultsWindow.TButton")
            reset_btn = ttk.Button(action_frame, text="Just Reset", command=lambda: run_task_in_thread(on_reset), style="ResultsWindow.TButton")
            modify_btn = ttk.Button(action_frame, text="Modify & Reset", command=lambda: run_task_in_thread(on_modify), style="ResultsWindow.TButton")

            buttons.extend([append_btn, reset_btn, modify_btn])
            for btn in buttons: btn.pack(side=tk.LEFT, padx=(0,8)) # Adjusted padding


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
