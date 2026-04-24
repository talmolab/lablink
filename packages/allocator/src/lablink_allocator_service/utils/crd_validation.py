import logging
import re


logger = logging.getLogger(__name__)


_CRD_CODE_ALLOWED = re.compile(r"[A-Za-z0-9_/\-]+")


def _strip_matched_quotes(value: str) -> str:
    """Strip a single pair of matching leading/trailing quotes from a
    value. Google's copy-pasteable CRD command wraps the code in double
    quotes; users commonly submit it verbatim."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def check_crd_input(crd_command: str) -> bool:
    """Check if the CRD command is valid.

    Matches the client's parsing exactly (plain whitespace split, then
    argparse-style extraction of ``--code=<value>`` / ``--code <value>``)
    so that anything accepted here will also parse safely on the client.
    A single pair of matching surrounding quotes is stripped from the
    extracted value to accept Google's copy-pasteable command format.
    The remaining value must match a conservative allowlist; shell
    metacharacters, whitespace, embedded quotes, and ``=`` are rejected.
    """
    if crd_command is None:
        logger.error("CRD command is None.")
        return False

    tokens = crd_command.split()

    code_values: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--code":
            if i + 1 >= len(tokens):
                logger.error("Invalid CRD command: --code requires a value.")
                return False
            code_values.append(tokens[i + 1])
            i += 2
            continue
        if tok.startswith("--code="):
            code_values.append(tok[len("--code=") :])
        i += 1

    if len(code_values) != 1:
        logger.error(
            "Invalid CRD command: expected exactly one --code flag, "
            "found %d.",
            len(code_values),
        )
        return False

    value = _strip_matched_quotes(code_values[0])
    if not value or not _CRD_CODE_ALLOWED.fullmatch(value):
        logger.error("Invalid CRD command: --code value failed allowlist check.")
        return False

    return True
