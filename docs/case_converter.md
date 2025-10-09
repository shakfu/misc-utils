# Case Converter

A comprehensive Python utility for converting between various naming case formats in source code files.

## Features

- **Multiple case format support:**
  - `camelCase` - e.g., `firstName`, `lastName`
  - `PascalCase` - e.g., `FirstName`, `LastName`
  - `snake_case` - e.g., `first_name`, `last_name`
  - `SCREAMING_SNAKE_CASE` - e.g., `FIRST_NAME`, `LAST_NAME`
  - `kebab-case` - e.g., `first-name`, `last-name`
  - `SCREAMING-KEBAB-CASE` - e.g., `FIRST-NAME`, `LAST-NAME`

- **Flexible file processing:**
  - Process single files or entire directories
  - Recursive directory traversal
  - File extension filtering
  - Dry run mode for safe previewing

- **Advanced filtering and transformation:**
  - **Prefix/Suffix support** - Add custom prefixes or suffixes to converted identifiers
  - **Glob pattern filtering** - Target specific files using glob patterns (e.g., `*test*.py`)
  - **Word filtering** - Apply regex filters to selectively convert only matching identifiers

## Usage

### Basic Syntax

```bash
./src/case_converter.py --from-<format> --to-<format> [options] <path>
```

Format flags:
- `--from-camel` / `--to-camel` - camelCase
- `--from-pascal` / `--to-pascal` - PascalCase
- `--from-snake` / `--to-snake` - snake_case
- `--from-screaming-snake` / `--to-screaming-snake` - SCREAMING_SNAKE_CASE
- `--from-kebab` / `--to-kebab` - kebab-case
- `--from-screaming-kebab` / `--to-screaming-kebab` - SCREAMING-KEBAB-CASE

### Examples

#### Convert camelCase to snake_case
```bash
./src/case_converter.py --from-camel --to-snake myfile.py
```

#### Convert PascalCase to kebab-case recursively
```bash
./src/case_converter.py --from-pascal --to-kebab -r src/
```

#### Dry run to preview changes
```bash
./src/case_converter.py --from-snake --to-camel -d src/
```

#### Specify file extensions
```bash
./src/case_converter.py --from-camel --to-snake -r -e .py .js .ts src/
```

#### Add prefix to converted identifiers
```bash
./src/case_converter.py --from-camel --to-snake --prefix old_ src/
# firstName -> old_first_name
```

#### Add suffix to converted identifiers
```bash
./src/case_converter.py --from-snake --to-camel --suffix New src/
# first_name -> firstNameNew
```

#### Filter files using glob patterns
```bash
./src/case_converter.py --from-camel --to-snake -r --glob '*test*.py' src/
# Only processes files matching *test*.py pattern
```

#### Filter words using regex patterns
```bash
./src/case_converter.py --from-camel --to-snake --word-filter '^get.*' src/
# Only converts identifiers starting with 'get' (e.g., getName -> get_name)
```

#### Combine multiple features
```bash
./src/case_converter.py --from-camel --to-snake -r \
  --glob 'utils/*.py' \
  --word-filter '^(get|set).*' \
  --prefix old_ \
  src/
# Only converts getters/setters in utils/*.py files, adding 'old_' prefix
```

### Options

- `-r, --recursive` - Process files recursively in subdirectories
- `-d, --dry-run` - Preview changes without modifying files
- `-e, --extensions` - Specify file extensions to process (default: `.c`, `.h`, `.py`, `.md`, `.js`, `.ts`, `.java`, `.cpp`, `.hpp`)
- `--prefix` - Prefix to add to all converted words
- `--suffix` - Suffix to add to all converted words
- `--glob` - Glob pattern to filter which files get processed
- `--word-filter` - Regex pattern to filter which words get converted
- `-h, --help` - Show help message

## Class Architecture

The `CaseConverter` class provides the core functionality:

### Class Attributes

```python
FILE_EXTENSIONS = ['.c', '.h', '.py', '.md', '.js', '.ts', '.java', '.cpp', '.hpp']

# Regex patterns for identifying different case formats
PAT_CAMEL_CASE = re.compile(r'\b[a-z]+(?:[A-Z][a-z0-9]*)+\b')
PAT_PASCAL_CASE = re.compile(r'\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b')
PAT_SNAKE_CASE = re.compile(r'\b[a-z]+(?:_[a-z0-9]+)+\b')
PAT_SCREAMING_SNAKE_CASE = re.compile(r'\b[A-Z]+(?:_[A-Z0-9]+)+\b')
PAT_KEBAB_CASE = re.compile(r'\b[a-z]+(?:-[a-z0-9]+)+\b')
PAT_SCREAMING_KEBAB_CASE = re.compile(r'\b[A-Z]+(?:-[A-Z0-9]+)+\b')
```

### Methods

- `convert(name: str) -> str` - Convert a single string between formats
- `process_file(filepath: str | Path)` - Process a single file
- `process_directory()` - Process all files in a directory

## Examples

### Convert a Python file from camelCase to snake_case

Before:
```python
def getUserName():
    firstName = "John"
    lastName = "Doe"
    emailAddress = "john@example.com"
    return firstName, lastName
```

Command:
```bash
./src/case_converter.py myfile.py camelCase snake_case
```

After:
```python
def get_user_name():
    first_name = "John"
    last_name = "Doe"
    email_address = "john@example.com"
    return first_name, last_name
```

### Convert JavaScript constants from snake_case to SCREAMING_SNAKE_CASE

Before:
```javascript
const api_key = "abc123";
const user_token = "xyz789";
```

Command:
```bash
./src/case_converter.py config.js snake_case SCREAMING_SNAKE_CASE
```

After:
```javascript
const API_KEY = "abc123";
const USER_TOKEN = "xyz789";
```

## Programmatic Usage

```python
from case_converter import CaseConverter

# Basic usage
converter = CaseConverter(
    directory_path="./src",
    from_format="camelCase",
    to_format="snake_case",
    recursive=True,
    dry_run=False
)

# Process all files
converter.process_directory()

# Convert a single string
result = converter.convert("firstName")  # Returns "first_name"
```

### Advanced Usage

```python
# With prefix and suffix
converter = CaseConverter(
    directory_path="./src",
    from_format="camelCase",
    to_format="snake_case",
    prefix="old_",
    suffix="_v1"
)
result = converter.convert("userName")  # Returns "old_user_name_v1"

# With glob pattern filtering
converter = CaseConverter(
    directory_path="./src",
    from_format="camelCase",
    to_format="snake_case",
    glob_pattern="*test*.py",
    recursive=True
)
converter.process_directory()  # Only processes files matching *test*.py

# With word filtering
converter = CaseConverter(
    directory_path="./src",
    from_format="camelCase",
    to_format="snake_case",
    word_filter="^get.*"  # Only convert getters
)
converter.process_directory()

# Combining all features
converter = CaseConverter(
    directory_path="./src",
    from_format="camelCase",
    to_format="snake_case",
    recursive=True,
    prefix="legacy_",
    glob_pattern="utils/*.py",
    word_filter="^(get|set).*",
    dry_run=True
)
converter.process_directory()
```

## Testing

The converter includes comprehensive test coverage:

```bash
python3 -m pytest tests/test_case_converter.py -v
```

Test coverage includes:
- All case format conversions (18 tests)
- Pattern matching for each format (6 tests)
- File and directory processing (5 tests)
- Edge cases and error handling (5 tests)
- Prefix and suffix functionality (6 tests)
- Word filtering with regex (3 tests)
- Glob pattern filtering (3 tests)
- Combined features (2 tests)

**Total: 48 tests, all passing**

## Real-World Use Cases

### Migrating legacy code with prefixes
When refactoring old code, mark legacy identifiers while converting:

```bash
# Mark old getters as legacy while converting to snake_case
./src/case_converter.py --from-camel --to-snake \
  --word-filter '^get.*' \
  --prefix legacy_ \
  -r legacy_code/
```

### Updating test files only
Convert naming conventions only in test files:

```bash
./src/case_converter.py --from-pascal --to-snake \
  --glob 'test_*.py' \
  -r tests/
```

### Selective conversion for API compatibility
When updating code but maintaining compatibility, add suffixes:

```bash
# Create v2 versions of all snake_case identifiers
./src/case_converter.py --from-snake --to-camel \
  --suffix V2 \
  --dry-run \
  api/
```

### Converting only specific patterns
Convert only setter/getter methods in a codebase:

```bash
./src/case_converter.py --from-camel --to-snake \
  --word-filter '^(get|set|is|has)[A-Z].*' \
  -r src/
```

### Gradual refactoring
Use glob patterns to refactor one module at a time:

```bash
# Refactor utils module first
./src/case_converter.py --from-camel --to-snake \
  --glob 'utils/**/*.py' \
  -r src/

# Then services module
./src/case_converter.py --from-camel --to-snake \
  --glob 'services/**/*.py' \
  -r src/
```

## Notes

- The converter uses regex patterns to identify and convert case formats
- Only identifiers matching the source format pattern will be converted
- The tool is designed to be safe - use dry run mode to preview changes first
- Single word identifiers may not be converted as they don't match multi-word patterns
- Complex acronyms (e.g., `getHTMLContent`) are split character by character
- Glob patterns support shell-style wildcards: `*` (any chars), `?` (single char), `**` (recursive)
- Word filters use standard Python regex syntax
- Prefix/suffix are applied after case conversion
