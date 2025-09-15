# Copilot Instructions (Submodule: sck-core-component)

- Tech: Python package.
- Precedence: Local file first; then root instructions in `../../.github/`.
- Backend conventions: Reuse standards in `../sck-core-ui/docs/backend-code-style.md`.

## Contradiction Detection
- Compare with backend standards and root precedence.
- If conflict, warn with quote + source, offer options, give example.
- Example: "Direct S3 client for bucket ops conflicts with MagicS3Bucket guidance; use MagicS3Bucket for bucket operations, boto3 client for presign."

## Standalone clone note
If cloned standalone, see:
- UI/backend conventions: https://github.com/eitssg/simple-cloud-kit/tree/develop/sck-core-ui/docs
- Root Copilot guidance: https://github.com/eitssg/simple-cloud-kit/blob/develop/.github/copilot-instructions.md
 
