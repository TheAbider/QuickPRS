# Contributing to QuickPRS

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/TheAbider/QuickPRS.git
   cd QuickPRS
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install pytest
   ```

3. Optional GUI dependencies:
   ```bash
   pip install sv-ttk darkdetect windnd
   ```

## Running Tests

```bash
python -m pytest tests/ -q
```

Note: Test PRS data files are not included in this repository (gitignored). Tests that require `.PRS` files skip gracefully when the test data directory is empty.

## Project Structure

- `quickprs/` -- Main package (parser, writer, CLI, GUI, validation, etc.)
- `tests/` -- Test suite (26 test files, 3,265+ tests)
- `dist/` -- Built executable (gitignored)
- `local/` -- Developer scratch files (gitignored)

## Submitting Issues

- Use the [GitHub Issues](https://github.com/TheAbider/QuickPRS/issues) page
- Include the QuickPRS version (`quickprs --version`)
- For file parsing issues, include the output of `quickprs dump <file>` (redact sensitive system info if needed)
- For validation issues, include the output of `quickprs validate <file>`

## Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-change`)
3. Run the full test suite and ensure all tests pass
4. Submit a pull request with a clear description of the change

## Code Style

- Follow existing code conventions (PEP 8, type hints where practical)
- Add tests for new features
- Keep CLI help text clear and include usage examples
