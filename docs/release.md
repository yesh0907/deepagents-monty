# Release Process

1. Update the version in `pyproject.toml`.
2. Update `src/deepagents_monty/__init__.py`.
3. Update `CHANGELOG.md`.
4. Run the checks:

   ```bash
   uv sync --all-extras
   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   uv run pyright
   ```

5. Build the distributions:

   ```bash
   uv build --clear
   uvx twine check dist/*
   ```

6. Publish to TestPyPI first for a new release flow:

   ```bash
   uv publish --publish-url https://test.pypi.org/legacy/
   ```

7. Publish to PyPI:

   ```bash
   uv publish
   ```

8. Create a GitHub release from the tag and include the changelog notes.
