import builtins

_open = builtins.open


def _utf8_open(file, mode="r", *args, encoding=None, errors=None, **kwargs):
    if encoding is None and "b" not in mode:
        encoding = "utf-8"
        errors = errors or "replace"
    return _open(file, mode, *args, encoding=encoding, errors=errors, **kwargs)


builtins.open = _utf8_open
