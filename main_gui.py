# main_gui.py
import tkinter as tk
from tkinter import ttk, messagebox, Toplevel, Frame, Label, Button
import config
import anki_utils
import parsers


class AnkiImporterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Anki Card Importer")
        self.root.geometry("800x600")

        # --- Main Layout ---
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Create two panes for Passive and Active cards
        self.passive_frame = self.create_listbox_frame(main_frame, "Passive Cards", config.PASSIVE_INPUT_FILE,
                                                       "parse_passive_line")
        self.passive_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.active_frame = self.create_listbox_frame(main_frame, "Active Cards", config.ACTIVE_INPUT_FILE,
                                                      "parse_active_line")
        self.active_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        # --- Buttons ---
        button_frame = ttk.Frame(root, padding="10")
        button_frame.pack(fill=tk.X)

        passive_button = ttk.Button(button_frame, text="Import Passive Cards", command=self.import_passive_cards)
        passive_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))

        active_button = ttk.Button(button_frame, text="Import Active Cards", command=self.import_active_cards)
        active_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))

    def create_listbox_frame(self, parent, title, file_path, parser_func_name):
        frame = ttk.LabelFrame(parent, text=title, padding="10")
        listbox = tk.Listbox(frame)
        listbox.pack(fill=tk.BOTH, expand=True)

        # Store parsed data in a dictionary associated with the frame
        frame.parsed_cards = self.load_cards_into_listbox(listbox, file_path, parser_func_name)
        return frame

    def load_cards_into_listbox(self, listbox, file_path, parser_func_name):
        parsed_cards = []
        try:
            parser_func = getattr(parsers, parser_func_name)
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    front, back, tag_suffix = parser_func(line)
                    if front and back:
                        listbox.insert(tk.END, f"{front}  ->  {back}")
                        parsed_cards.append({"front": front, "back": back, "tag_suffix": tag_suffix})
        except FileNotFoundError:
            listbox.insert(tk.END, f"ERROR: '{file_path}' not found.")
        except Exception as e:
            listbox.insert(tk.END, f"ERROR parsing file: {e}")
        return parsed_cards

    def import_passive_cards(self):
        deck_config = next(c for c in config.PROCESSING_CONFIGS if c["deck_name"] == config.PASSIVE_DECK_NAME)
        self.run_import_process(
            deck_name=deck_config["deck_name"],
            cards_to_process=self.passive_frame.parsed_cards,
            tag_func=deck_config["tag_generation_func"]
        )

    def import_active_cards(self):
        deck_config = next(c for c in config.PROCESSING_CONFIGS if c["deck_name"] == config.ACTIVE_DECK_NAME)
        self.run_import_process(
            deck_name=deck_config["deck_name"],
            cards_to_process=self.active_frame.parsed_cards,
            tag_func=deck_config["tag_generation_func"]
        )

    def run_import_process(self, deck_name, cards_to_process, tag_func):
        if not anki_utils.ensure_deck_exists(deck_name):
            messagebox.showerror("Error", f"Could not create or find Anki deck: {deck_name}")
            return

        added, skipped, failed = [], [], []

        for card_data in cards_to_process:
            tags = tag_func(card_data["tag_suffix"])
            status, note_id = anki_utils.add_card(
                deck_name, config.MODEL_NAME, card_data["front"], card_data["back"], tags
            )
            if status == "added":
                added.append(card_data)
            elif status == "failed":
                failed.append(card_data)
            elif status == "skipped":
                card_data['note_id'] = note_id
                skipped.append(card_data)

        # Display results window
        if skipped:
            SkippedCardsWindow(self.root, deck_name, added, skipped, failed)
        else:
            summary = f"Import for '{deck_name}' complete!\n\n"
            summary += f"Successfully Added: {len(added)}\n"
            summary += f"Skipped (Duplicates): {len(skipped)}\n"
            summary += f"Failed: {len(failed)}"
            messagebox.showinfo("Import Complete", summary)


class SkippedCardsWindow(Toplevel):
    def __init__(self, parent, deck_name, added, skipped, failed):
        super().__init__(parent)
        self.title(f"Skipped Cards in '{deck_name}'")
        self.transient(parent)
        self.grab_set()

        summary_frame = ttk.Frame(self, padding=10)
        summary_frame.pack(fill=tk.X)
        summary_text = (
            f"Import Summary:\n"
            f"  - Added: {len(added)}\n"
            f"  - Failed: {len(failed)}\n"
            f"  - Skipped: {len(skipped)} (duplicates found)"
        )
        ttk.Label(summary_frame, text=summary_text).pack(anchor='w')
        ttk.Separator(summary_frame, orient='horizontal').pack(fill='x', pady=10)
        ttk.Label(summary_frame, text="Choose an action for each skipped card:", font=("", 10, "bold")).pack(anchor='w')

        for card in skipped:
            self.create_card_frame(card)

    def create_card_frame(self, card_data):
        frame = ttk.LabelFrame(self, text=f"Card: {card_data['front']}", padding=10)
        frame.pack(fill=tk.X, padx=10, pady=5)

        note_id = card_data['note_id']
        new_back = card_data['back']

        def on_append():
            info = anki_utils.get_note_info(note_id)
            if info and info.get('result'):
                old_back = info['result'][0]['fields']['Back']['value']
                # Append with a line break
                updated_back = f"{old_back}<hr>{new_back}"
                anki_utils.update_note_fields(note_id, {"Back": updated_back})
                anki_utils.reset_cards([note_id])
                messagebox.showinfo("Success", f"Appended content to and reset card:\n{card_data['front']}")
                frame.destroy()

        def on_reset():
            anki_utils.reset_cards([note_id])
            messagebox.showinfo("Success", f"Reset card:\n{card_data['front']}")
            frame.destroy()

        def on_modify():
            anki_utils.open_editor_for_note(note_id)
            # We can also reset it, assuming the user will make changes and want to review
            anki_utils.reset_cards([note_id])
            messagebox.showinfo("Action", f"Opened editor for '{card_data['front']}' and reset it.")
            frame.destroy()

        Button(frame, text="Append & Reset", command=on_append).pack(side=tk.LEFT, padx=5)
        Button(frame, text="Just Reset", command=on_reset).pack(side=tk.LEFT, padx=5)
        Button(frame, text="Modify & Reset", command=on_modify).pack(side=tk.LEFT, padx=5)


if __name__ == "__main__":
    # Ensure Anki is connected before launching GUI
    if anki_utils.anki_request('version') is None:
        messagebox.showerror("Anki Connection Error",
                             "Could not connect to Anki.\nPlease ensure Anki is running with the AnkiConnect add-on installed.")
    else:
        root = tk.Tk()
        app = AnkiImporterApp(root)
        root.mainloop()