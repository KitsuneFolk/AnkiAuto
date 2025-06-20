import logging
import sys
from logging.handlers import RotatingFileHandler

LOG_FILENAME = "logs.txt"


def handle_exception(exc_type, exc_value, exc_traceback):
    """
    Custom exception hook to log unhandled exceptions to the file.
    """
    # Don't log KeyboardInterrupt
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logging.critical("Unhandled exception:", exc_info=(exc_type, exc_value, exc_traceback))


def setup_logging():
    """
    Configures logging to write to a rotating file and sets the custom exception hook.
    """
    # Configure the root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)  # Set the lowest level to capture

    # Create a formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Create a rotating file handler to prevent the log file from growing indefinitely
    # 1MB per file, keeping the last 5 logs.
    file_handler = RotatingFileHandler(LOG_FILENAME, maxBytes=1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # Add the handler to the root logger
    logger.addHandler(file_handler)

    # Also log to console for immediate feedback during development
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    # Set the global exception handler
    sys.excepthook = handle_exception

    logging.info("Logging configured successfully. Application starting.")