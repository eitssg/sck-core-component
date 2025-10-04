# Copilot Instructions (Submodule: sck-core-component)

## Plan → Approval → Execute (Mandatory)
All non-trivial actions require plan + approval prior to execution. Root policy supersedes earlier proactive guidance.

- Tech: Python package.
- Precedence: Local file first; then root instructions in `../../.github/`.
- Backend conventions: Reuse standards in `../sck-core-ui/docs/backend-code-style.md`.

## Google Docstring Requirements
**MANDATORY**: All docstrings must use Google-style format for Sphinx documentation generation:
- Use Google-style docstrings with proper Args/Returns/Example sections
- Napoleon extension will convert Google format to RST for Sphinx processing
- Avoid direct RST syntax (`::`, `:param:`, etc.) in docstrings - use Google format instead
- Example sections should use `>>>` for doctests or simple code examples
- This ensures proper IDE interpretation while maintaining clean Sphinx documentation

## Contradiction Detection
- Compare with backend standards and root precedence.
- If conflict, warn with quote + source, offer options, give example.
- Example: "Direct S3 client for bucket ops conflicts with MagicS3Bucket guidance; use MagicS3Bucket for bucket operations, boto3 client for presign."

## Standalone clone note
If cloned standalone, see:
- UI/backend conventions: https://github.com/eitssg/simple-cloud-kit/tree/develop/sck-core-ui/docs
- Root Copilot guidance: https://github.com/eitssg/simple-cloud-kit/blob/develop/.github/copilot-instructions.md
 
