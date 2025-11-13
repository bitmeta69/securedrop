# SecureDrop API v2 Test Data

This directory contains test data for end-to-end testing of client-side write operations against the SecureDrop API v2 endpoints.

## Directory Structure

```
securedrop/tests/data/
├── README.md                           # This file
├── reply_test.yaml                     # Test data for reply creation tests
├── star_test.yaml                      # Test data for star/unstar tests
├── seen_test.yaml                      # Test data for item seen tests
├── item_deletion_test.yaml             # Test data for item deletion tests
├── source_deletion_test.yaml           # Test data for source deletion tests
├── conversation_deletion_test.yaml     # Test data for conversation deletion tests
├── keys/                               # PGP keys for test sources
│   ├── F6283AE2A3C92F8C910946FA3BE7DFE991FC8A87.pub
│   ├── F6283AE2A3C92F8C910946FA3BE7DFE991FC8A87.secret
│   ├── 6E0B59448DD8DA2CFEF61B8F926290C5880A6D62.pub
│   ├── 6E0B59448DD8DA2CFEF61B8F926290C5880A6D62.secret
│   ├── 1D5EED3E722A21361FB1609436AA2DFBDC429CA1.pub
│   └── 1D5EED3E722A21361FB1609436AA2DFBDC429CA1.secret
└── items/                              # Pre-encrypted item files
    ├── f53f43d9-41fa-42a6-88b0-6529aaacc599.gpg
    ├── 48256b37-2761-4695-8a1a-282601dc3c87.gpg
    └── ... (18 encrypted files total)
```

## Test Data Files

### 1. reply_test.yaml
**Purpose**: Test creating replies to sources

**Contains**:
- 1 journalist (journalist)
- 1 source (test reply source)
- 1 message item (for replying to)

**Source UUID**: `a0a49b24-1a75-4daf-b0fa-125c1ce0d723`

---

### 2. star_test.yaml
**Purpose**: Test starring and unstarring sources

**Contains**:
- 1 journalist (journalist)
- 1 source (test star source)
- 1 message item

**Source UUID**: `b0b49b24-1a75-4daf-b0fa-125c1ce0d724`

---

### 3. seen_test.yaml
**Purpose**: Test marking conversation items as seen

**Contains**:
- 2 journalists (journalist, dellsberg)
- 1 source (test seen source)
- 3 items (1 message, 1 file, 1 reply) - all initially unseen

**Source UUID**: `c0c49b24-1a75-4daf-b0fa-125c1ce0d725`

---

### 4. item_deletion_test.yaml
**Purpose**: Test deleting individual items

**Contains**:
- 1 journalist (journalist)
- 1 source (test delete item source)
- 2 items (1 message, 1 file)

**Source UUID**: `d0d49b24-1a75-4daf-b0fa-125c1ce0d726`

---

### 5. source_deletion_test.yaml
**Purpose**: Test deleting entire sources

**Contains**:
- 1 journalist (journalist)
- 1 source (test delete source)
- 2 items (1 message, 1 file)

**Source UUID**: `e0e49b24-1a75-4daf-b0fa-125c1ce0d727`

---

### 6. conversation_deletion_test.yaml
**Purpose**: Test deleting source conversations while preserving source

**Contains**:
- 2 journalists (journalist, dellsberg)
- 1 source (test conversation delete)
- 3 items (2 messages, 1 reply)

**Source UUID**: `f0f49b24-1a75-4daf-b0fa-125c1ce0d728`

---

## Loading Test Data

Test data is loaded using the `loadfixeddata.py` script with the `--skip-empty-check` flag:

```python
import subprocess
from pathlib import Path

def load_test_data(yaml_filename: str) -> None:
    """Load test data from YAML file."""
    yaml_path = Path(__file__).parent / "data" / yaml_filename
    subprocess.run(
        [
            "python",
            "securedrop/loadfixeddata.py",
            "--yaml-path", str(yaml_path),
            "--skip-empty-check",
        ],
        check=True,
        cwd=Path(__file__).parent.parent.parent,
    )

# Usage in fixtures
load_test_data("reply_test.yaml")
```

## Data Origin

- **PGP Keys**: Copied from `securedrop-client/app/server_tests/data/keys/`
- **Encrypted Items**: Copied from `securedrop-client/app/server_tests/data/items/`
- **YAML Structure**: Based on `securedrop-client/app/server_tests/data/data.yaml`

This ensures consistency between client-side and server-side tests.

## Journalist Credentials

All test files use the same test journalist:

- **Username**: `journalist`
- **UUID**: `be726875-1290-49d4-922d-2fc0901c9266`
- **Passphrase**: `correct horse battery staple profanity oil chewy`
- **OTP Secret**: `JHCOGO7VCER3EJ4L`
- **Is Admin**: `true`

Some tests also include a second journalist:

- **Username**: `dellsberg`
- **UUID**: `72eb04dc-7596-4bc0-a9b1-a0f5648f04f0`
- **Passphrase**: `correct horse battery staple profanity oil chewy`
- **OTP Secret**: `JHCOGO7VCER3EJ4L`
- **Is Admin**: `false`

## Notes

- All source UUIDs are unique to avoid conflicts when loading multiple test files
- All encrypted item files are pre-generated to ensure reproducible test results
- Each test file contains the minimal data needed for its specific test scenario
- The `--skip-empty-check` flag allows loading data into non-empty databases for test isolation
