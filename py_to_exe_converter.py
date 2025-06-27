import os
import shutil
import subprocess
import sys

# --- Project Structure Setup ---
# Assumes this script is in the project root, alongside main_gui.py and icon.ico
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = SCRIPT_DIR  # Project root where main_gui.py is located

MAIN_SCRIPT_NAME = "main_gui.py"
EXE_NAME = "AnkiAuto"

# --- Output Directories (relative to SOURCE_DIR) ---
DIST_DIR_NAME = "dist"
BUILD_DIR_NAME = "build"
FINAL_RELEASE_DIR_NAME = "release_builds"

OUTPUT_DIST_PATH = os.path.join(SOURCE_DIR, DIST_DIR_NAME)
OUTPUT_BUILD_PATH = os.path.join(SOURCE_DIR, BUILD_DIR_NAME)
OUTPUT_FINAL_DIR_PATH = os.path.join(SOURCE_DIR, FINAL_RELEASE_DIR_NAME)

# --- PyInstaller Options ---
ONEFILE = True
WINDOWED = True
ICON_NAME = "icon.ico"
ICON_PATH = os.path.join(SOURCE_DIR, ICON_NAME)


def clean_previous_builds():
    """Removes PyInstaller's temporary 'build' and 'dist' directories, and the .spec file."""
    print("--- Cleaning up previous build artifacts ---")

    # Paths are now defined relative to SOURCE_DIR
    spec_file_path = os.path.join(SOURCE_DIR, f"{EXE_NAME}.spec")

    for path_to_remove in [OUTPUT_DIST_PATH, OUTPUT_BUILD_PATH, spec_file_path]:
        if os.path.exists(path_to_remove):
            if os.path.isdir(path_to_remove):
                shutil.rmtree(path_to_remove)
                print(f"Removed directory: {path_to_remove}")
            else:
                os.remove(path_to_remove)
                print(f"Removed file: {path_to_remove}")
    print("Cleanup complete.\n")


def check_dependencies():
    """Checks if PyInstaller is installed and if the main script exists."""
    print("--- Performing pre-build checks ---")
    try:
        subprocess.run(["pyinstaller", "--version"], check=True, capture_output=True, text=True)
        print("PyInstaller is installed.")
    except FileNotFoundError:
        print("Error: PyInstaller command not found.")
        print("Please install it using: pip install pyinstaller")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error checking PyInstaller version: {e}")
        print("Please ensure PyInstaller is correctly installed and accessible in your PATH.")
        sys.exit(1)

    # Check if the source directory exists
    if not os.path.isdir(SOURCE_DIR):
        print(f"Error: Source directory '{SOURCE_DIR}' not found.")
        print("Please ensure 'SOURCE_DIR' is set correctly and exists.")
        sys.exit(1)

    # Check if the main script exists within the source directory
    main_script_full_path = os.path.join(SOURCE_DIR, MAIN_SCRIPT_NAME)
    if not os.path.isfile(main_script_full_path):
        print(f"Error: Main script '{main_script_full_path}' not found.")
        print("Please ensure 'MAIN_SCRIPT_NAME' is correct and located within 'SOURCE_DIR'.")
        sys.exit(1)
    print(f"Main script '{main_script_full_path}' found.")
    print("Pre-build checks passed.\n")


def build_executable():
    """Constructs and executes the PyInstaller command."""
    print("--- Starting PyInstaller build process ---")

    main_script_full_path = os.path.join(SOURCE_DIR, MAIN_SCRIPT_NAME)

    command = [
        "pyinstaller",
        main_script_full_path,
        "--distpath", OUTPUT_DIST_PATH,
        "--workpath", OUTPUT_BUILD_PATH,
        "--specpath", SOURCE_DIR,  # Place .spec file in the source directory
    ]

    if ONEFILE:
        command.append("--onefile")

    if WINDOWED:
        command.append("--windowed")

    if EXE_NAME:
        command.extend(["--name", EXE_NAME])

    # ICON_PATH is now an absolute path
    if os.path.isfile(ICON_PATH):
        command.extend(["--icon", ICON_PATH])
        print(f"Using icon: {ICON_PATH}")
    else:
        # ICON_NAME is the filename, ICON_PATH is the full expected path.
        print(f"Warning: Icon file '{ICON_PATH}' (looking for '{ICON_NAME}') not found. Skipping icon setting.")

    print(f"\nExecuting PyInstaller command:\n{' '.join(command)}\n")

    try:
        subprocess.run(command, check=True, shell=False)
        print("\nPyInstaller build successful.")

    except subprocess.CalledProcessError as e:
        print(f"\nError: PyInstaller failed with exit code {e.returncode}")
        print(f"Command executed: {' '.join(e.cmd)}")
        if e.stdout:
            print(f"PyInstaller Output (stdout):\n{e.stdout.decode()}")
        if e.stderr:
            print(f"PyInstaller Errors (stderr):\n{e.stderr.decode()}")
        print("\nPlease review the PyInstaller output above for details on the error.")
        sys.exit(1)
    except Exception as e:
        print(f"\nAn unexpected error occurred during PyInstaller execution: {e}")
        sys.exit(1)


def move_final_executable():
    """Moves the built executable to the specified output directory."""
    print("\n--- Moving final executable ---")

    # PyInstaller's output is now directed to OUTPUT_DIST_PATH
    if sys.platform == "win32":
        final_exe_name = f"{EXE_NAME}.exe"
    else:
        final_exe_name = EXE_NAME

    expected_exe_path = os.path.join(OUTPUT_DIST_PATH, final_exe_name)

    if not os.path.exists(expected_exe_path):
        print(f"Error: Expected executable not found at '{expected_exe_path}'.")
        print("PyInstaller might have failed or created it with a different name/path.")
        sys.exit(1)

    os.makedirs(OUTPUT_FINAL_DIR_PATH, exist_ok=True) # Use new path variable

    final_target_path = os.path.join(OUTPUT_FINAL_DIR_PATH, final_exe_name) # Use new path variable

    try:
        shutil.move(expected_exe_path, final_target_path)
        print(f"Successfully moved executable to: {final_target_path}")
    except Exception as e:
        print(f"Error moving executable from '{expected_exe_path}' to '{final_target_path}': {e}")
        sys.exit(1)


if __name__ == "__main__":
    clean_previous_builds()
    check_dependencies()
    build_executable()
    move_final_executable()

    print("\n--- Script finished successfully ---")
    # OUTPUT_FINAL_DIR_PATH is already an absolute path if SOURCE_DIR is derived from abspath
    print(f"Your application is ready at: {OUTPUT_FINAL_DIR_PATH}")
