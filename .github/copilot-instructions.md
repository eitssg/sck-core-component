# Copilot Instructions (Submodule: sck-core-component)

- Tech: Python package.
- Precedence: Local file first; then root instructions in `../../.github/`.
- Backend conventions: Reuse standards in `../sck-core-ui/docs/backend-code-style.md`.

## RST Documentation Requirements
**MANDATORY**: All docstrings must be RST-compatible for Sphinx documentation generation:
- Use proper RST syntax: `::` for code blocks (not markdown triple backticks)
- Code blocks must be indented 4+ spaces relative to preceding text
- Add blank line after `::` before code content
- Bullet lists must end with blank line before continuing text
- Use RST field lists for parameters: `:param name: description`
- Use RST directives: `.. note::`, `.. warning::`, etc.
- Test docstrings with Sphinx build - code is source of truth, not docstrings

## Contradiction Detection
- Compare with backend standards and root precedence.
- If conflict, warn with quote + source, offer options, give example.
- Example: "Direct S3 client for bucket ops conflicts with MagicS3Bucket guidance; use MagicS3Bucket for bucket operations, boto3 client for presign."

## Standalone clone note
If cloned standalone, see:
- UI/backend conventions: https://github.com/eitssg/simple-cloud-kit/tree/develop/sck-core-ui/docs
- Root Copilot guidance: https://github.com/eitssg/simple-cloud-kit/blob/develop/.github/copilot-instructions.md
 
