import tkinter as tk
from tkinter import ttk
import os
import sqlite3
import nltk
import spacy
from threading import Thread
from queue import Queue, Empty
import logging
import ast

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load English tokenizer, tagger, parser, NER, and word vectors from spaCy
nltk.download('stopwords')
nlp = spacy.load("en_core_web_sm")

# Define directories and files to ignore
IGNORE_DIRS = {
    '.vscode',  # Configuration files for Visual Studio Code
    '.env',  # Environment variable files
    '__pycache__',  # Compiled Python files
    '.idea',  # Configuration files for JetBrains IDEs like PyCharm
    '.git',  # Git version control system directory
    'node_modules',  # Node.js modules (if combining Python with Node.js in the project)
    'build',  # Directory commonly used for build outputs
    'dist',  # Directory for distribution files, often seen in Python packages
    'venv', 'env',  # Virtual environment directories
    '__MACOSX',  # Folder created in macOS file compressions
    '.pytest_cache',  # Cache directory for pytest
    '.mypy_cache',  # Cache directory for mypy type checks
    '.jupyter',  # Jupyter notebook configurations
    'logs',  # Log files and directories
    '.docker'  # Docker configuration files
}


# Create a thread-safe queue
queue = Queue()

def insert_files_into_db(files_to_insert):
    """Insert multiple files into the SQLite database."""
    with sqlite3.connect('file_structure.db') as conn:
        cursor = conn.cursor()
        insert_stmt = "INSERT INTO file_structure (file_name, file_path, vector) VALUES (?, ?, ?)"
        cursor.executemany(insert_stmt, files_to_insert)
        conn.commit()

def should_ignore(file_path):
    """Check if the file should be ignored. Only include .py and .md files."""
    base_name = os.path.basename(file_path)
    _, ext = os.path.splitext(base_name)

    # Ignore directories
    if os.path.isdir(file_path):
        return base_name in IGNORE_DIRS

    # Include only .py and .md files
    return ext not in ('.py', '.md')


def scan_subdirectories_and_create_index():
    """Scan subdirectories and create an index of file structure and vectors."""
    try:
        files_to_insert = []
        batch_size = 100
        with sqlite3.connect('file_structure.db') as conn:
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS file_structure
                            (id INTEGER PRIMARY KEY, file_name TEXT, file_path TEXT, vector TEXT)''')
            conn.commit()

            for dirpath, dirnames, filenames in os.walk('.'):
                dirnames[:] = [d for d in dirnames if not should_ignore(d)]  # Filter out ignored directories
                for file in filenames:
                    if should_ignore(file):
                        continue  # Skip ignored files
                    doc = nlp(file)
                    vector = doc.vector
                    files_to_insert.append((file, os.path.join(dirpath, file), str(vector.tolist())))
                    if len(files_to_insert) >= batch_size:
                        insert_files_into_db(files_to_insert)
                        files_to_insert.clear()
                    queue.put((os.path.join(dirpath, file), file))
            if files_to_insert:
                insert_files_into_db(files_to_insert)
    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        queue.put(None)

def check_queue():
    """Check the queue for new items and update the GUI accordingly."""
    try:
        while True:
            item = queue.get_nowait()
            if item is None:
                update_scan_button_state(False)
                break
            file_path, file_name = item
            file_tree.insert('', 'end', text=file_name, values=(file_path,))
    except Empty:
        root.after(100, check_queue)

def update_scan_button_state(is_scanning):
    """Update the scan button's state based on whether scanning is in progress."""
    scan_button.config(text="Scanning..." if is_scanning else "Scan Directories and Index", state=tk.DISABLED if is_scanning else tk.NORMAL)

def threaded_scan_subdirectories():
    """Start the scanning process in a separate thread."""
    update_scan_button_state(True)
    thread = Thread(target=scan_subdirectories_and_create_index, daemon=True)
    thread.start()

def parse_python_file(file_path):
    """Parse a Python file and extract class and function names along with their line numbers."""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            file_content = file.read()
        tree = ast.parse(file_content)
        classes = [(node.name, node.lineno) for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        functions = [(node.name, node.lineno) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        return classes, functions
    except Exception as e:
        logging.error(f"Error parsing file {file_path}: {e}")
        return [], []

def jump_to_line(listbox, line_numbers):
    """Jump to the line in the code_text widget based on the selection in the listbox."""
    selection = listbox.curselection()
    if selection:
        name = listbox.get(selection[0])
        line_number = line_numbers.get(name)
        if line_number:
            code_text.see(f"{line_number}.0")  # Scroll to the line
            code_text.tag_add("highlight", f"{line_number}.0", f"{line_number}.end")
            code_text.tag_config("highlight", background="yellow")
            
def on_file_select(event):
    """Handle file selection in the Treeview and update GUI components."""
    logging.info("File selection event triggered.")
    selected_item = file_tree.focus()
    file_name = file_tree.item(selected_item, 'text')
    logging.info(f"Selected item: {file_name}")
    file_path_entry.delete(0, tk.END)
    vector_value_text.config(state=tk.NORMAL)
    vector_value_text.delete('1.0', tk.END)
    classes_listbox.delete(0, tk.END)
    functions_listbox.delete(0, tk.END)
    code_text.delete('1.0', tk.END)
    code_text.tag_remove("highlight", "1.0", tk.END)

    try:
        logging.info("Connecting to the database.")
        with sqlite3.connect('file_structure.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT file_path, vector FROM file_structure WHERE file_name=?", (file_name,))
            row = cursor.fetchone()

        if row:
            file_path, vector = row
            file_path_entry.insert(0, file_path)
            vector_value_text.insert('1.0', str(vector))
            vector_value_text.config(state=tk.DISABLED)
            logging.info(f"Selected File: {file_path}")

            logging.info("Parsing the selected Python file.")
            classes, functions = parse_python_file(file_path)
            class_line_numbers = {cls_name: cls_line for cls_name, cls_line in classes}
            function_line_numbers = {func_name: func_line for func_name, func_line in functions}

            logging.info("Populating the classes listbox.")
            for cls_name, _ in classes:
                classes_listbox.insert(tk.END, cls_name)

            if not classes:
                classes_listbox.insert(tk.END, "[NO CLASSES IN FILE]")

            logging.info("Populating the functions listbox.")
            for func_name, _ in functions:
                functions_listbox.insert(tk.END, func_name)

            if not functions:
                functions_listbox.insert(tk.END, "[NO FUNCTIONS IN FILE]")

            logging.info("Binding listbox selection events.")
            classes_listbox.bind('<<ListboxSelect>>', lambda e: jump_to_line(classes_listbox, class_line_numbers))
            functions_listbox.bind('<<ListboxSelect>>', lambda e: jump_to_line(functions_listbox, function_line_numbers))

            logging.info("Reading the selected file content.")
            with open(file_path, 'r', encoding='utf-8') as file:
                file_content = file.read()
                code_text.config(state=tk.NORMAL)
                code_text.delete('1.0', tk.END)  # Clear existing content
                code_text.insert('1.0', file_content)  # Insert new content
                code_text.config(state=tk.DISABLED)

    except Exception as e:
        logging.error(f"An error occurred while selecting file {file_name}: {e}")
        vector_value_text.config(state=tk.DISABLED)


# Main application GUI setup
root = tk.Tk()
root.title("CODE DB INDEX.PY")

# Create PanedWindow for resizable panes
paned_window = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
paned_window.pack(fill=tk.BOTH, expand=True)

# Left frame for the file tree and scan button
left_frame = ttk.Frame(paned_window, width=200)
paned_window.add(left_frame, weight=1)

# File tree setup
file_tree = ttk.Treeview(left_frame)
file_tree.pack(expand=True, fill=tk.BOTH, side=tk.TOP)

# Bind the Treeview selection event to on_file_select function
file_tree.bind('<<TreeviewSelect>>', on_file_select)

# Scan button setup
scan_button = tk.Button(left_frame, text="Scan Directories and Index", command=threaded_scan_subdirectories)
scan_button.pack(side=tk.BOTTOM, fill=tk.X)

# Right frame for the rest of the GUI elements
right_frame = ttk.Frame(paned_window, width=600)
paned_window.add(right_frame, weight=4)

# Create a vertical PanedWindow inside the right frame
vertical_paned_window = ttk.PanedWindow(right_frame, orient=tk.VERTICAL)
vertical_paned_window.pack(fill=tk.BOTH, expand=True)

# Label and Entry for displaying the selected file path
file_path_frame = ttk.Frame(vertical_paned_window)
file_path_label = tk.Label(file_path_frame, text="File Path")  # Create a label for the file path
file_path_label.pack(side=tk.TOP, fill=tk.X)  # Place the label in the pack layout
file_path_entry = tk.Entry(file_path_frame)  # Create an entry widget for displaying the file path
file_path_entry.pack(side=tk.TOP, fill=tk.X)  # Place the entry widget in the pack layout
vertical_paned_window.add(file_path_frame)

# Text widget with Scrollbar for displaying vector values
vector_value_frame = ttk.Frame(vertical_paned_window)
vector_value_text = tk.Text(vector_value_frame, height=4, wrap='word')  # Create a text widget for displaying vector values
vector_value_scrollbar = tk.Scrollbar(vector_value_frame, command=vector_value_text.yview, width=5)  # Create a scrollbar for the text widget
vector_value_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)  # Place the text widget in the pack layout
vector_value_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)  # Place the scrollbar in the pack layout
vector_value_text['yscrollcommand'] = vector_value_scrollbar.set  # Connect the scrollbar to the text widget
vector_value_text.config(state='disabled')  # Make the text widget read-only
vertical_paned_window.add(vector_value_frame)

# Text Box for additional description or notes
description_frame = ttk.Frame(vertical_paned_window)
description_label = tk.Label(description_frame, text="Description")  # Create a label for the description
description_label.pack(side=tk.TOP, fill=tk.X)  # Place the label in the pack layout
description_text = tk.Text(description_frame, height=5)  # Create a text widget for entering the description
description_text.pack(side=tk.TOP, fill=tk.X)  # Place the text widget in the pack layout
vertical_paned_window.add(description_frame)

# PanedWindow for classes and functions listbox to allow resizing
listbox_pane = ttk.PanedWindow(vertical_paned_window, orient=tk.HORIZONTAL)
vertical_paned_window.add(listbox_pane)

# Setup for class listbox
classes_frame = ttk.Frame(listbox_pane)
classes_label = tk.Label(classes_frame, text="Code Classes", fg="blue")
classes_label.pack(side=tk.TOP, fill=tk.X)  # Use pack instead of grid
classes_listbox = tk.Listbox(classes_frame, bg='lightgray')
classes_listbox.pack(side=tk.TOP, fill=tk.BOTH, expand=True)  # Use pack instead of grid
listbox_pane.add(classes_frame, weight=1)

# Setup for functions listbox
functions_frame = ttk.Frame(listbox_pane)
functions_label = tk.Label(functions_frame, text="Functions in Class", fg="green")
functions_label.pack(side=tk.TOP, fill=tk.X)  # Use pack instead of grid
functions_listbox = tk.Listbox(functions_frame, bg='lightyellow')
functions_listbox.pack(side=tk.TOP, fill=tk.BOTH, expand=True)  # Use pack instead of grid
listbox_pane.add(functions_frame, weight=1)

# Text Box for displaying the code content of the selected file
code_frame = ttk.Frame(vertical_paned_window)
code_label = tk.Label(code_frame, text="Code")  # Create a label for the code
code_label.pack(side=tk.TOP, fill=tk.X, pady=(10, 0))  # Place the label in the pack layout
code_text = tk.Text(code_frame, height=15)  # Create a text widget for displaying the code
code_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)  # Place the text widget in the pack layout
vertical_paned_window.add(code_frame)

# Set up a periodic check of the queue for new items to update the GUI
root.after(100, check_queue)  # Schedule the check_queue function to run after 100 milliseconds

# Start the Tkinter event loop
root.mainloop()  # Start the Tkinter event loop to handle user interactions
