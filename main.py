# main.py
import anki_utils
import config
import parsers


def get_parser_function(func_name):
    """Dynamically retrieves a parsing function from the parsers module."""
    if hasattr(parsers, func_name) and callable(getattr(parsers, func_name)):
        return getattr(parsers, func_name)
    else:
        raise AttributeError(f"Parser function '{func_name}' not found in parsers.py")


def main():
    """Main function to read files and add cards to Anki."""
    print("--- Starting Anki Card Importer ---")

    anki_version_response = anki_utils.anki_request('version')
    if anki_version_response is None:
        print("Exiting due to AnkiConnect connection error.")
        return
    print(f"Connected to AnkiConnect version {anki_version_response.get('result')}")

    # Process each configured file
    for config_item in config.PROCESSING_CONFIGS:
        file_path = config_item["file_path"]
        deck_name = config_item["deck_name"]
        parser_func_name = config_item["parser_func_name"]
        tag_generation_func = config_item["tag_generation_func"]

        print(f"\n--- Processing '{file_path}' for deck '{deck_name}' ---")

        # Ensure deck exists before processing its file
        if not anki_utils.ensure_deck_exists(deck_name):
            print(f"Skipping processing for '{file_path}' as deck '{deck_name}' could not be created/found.")
            continue

        try:
            # Dynamically get the parser function
            parser_func = get_parser_function(parser_func_name)
        except AttributeError as e:
            print(f"Error: {e}. Skipping processing for '{file_path}'.")
            continue

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"Error: Input file '{file_path}' not found. Skipping this file.")
            continue  # Skip this file and proceed to the next one

        newly_added_count = 0
        skipped_due_to_duplicate_count = 0
        failed_to_add_count = 0
        unparsable_lines_count = 0

        for i, line_content in enumerate(lines):
            line_content = line_content.strip()
            if not line_content:
                continue

            front, back, card_specific_tag = parser_func(line_content)

            if front and back:
                current_tags = tag_generation_func(card_specific_tag)

                status = anki_utils.add_card(deck_name, config.MODEL_NAME, front, back, current_tags)

                if status == "added":
                    newly_added_count += 1
                elif status == "skipped":
                    skipped_due_to_duplicate_count += 1
                elif status == "failed":
                    failed_to_add_count += 1
            else:
                print(f"  ! Warning: Could not parse line {i + 1} in '{file_path}': '{line_content}'")
                unparsable_lines_count += 1

        # Print statistics for the current deck/file
        print(f"\n--- Summary for '{deck_name}' (from '{file_path}') ---")
        print(f"  Newly added cards: {newly_added_count}")
        print(f"  Skipped (already exist or reported as duplicate): {skipped_due_to_duplicate_count}")
        print(f"  Failed to add (due to error): {failed_to_add_count}")
        print(f"  Unparsable lines: {unparsable_lines_count}")

    print("\n--- All Imports Complete ---")


if __name__ == "__main__":
    main()
